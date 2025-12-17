from __future__ import annotations

import logging
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta
from json import JSONDecodeError
from typing import Any

import httpx

from .db import ensure_schema, utcnow
from .openrouter_client import OpenRouterClient, OpenRouterConfig, prompt_hash
from .prompts import load_prompt


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkItem:
    photo_id: int
    observation_id: int
    image_url: str
    notes: str
    attempt_count: int


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        parts = stripped.split("\n")
        if len(parts) >= 2 and parts[0].startswith("```"):
            stripped = "\n".join(parts[1:])
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()
            stripped = stripped[: -len("```")].rstrip()
    return stripped.strip()


def _extract_first_json_object(text: str) -> str:
    text = _strip_code_fences(text)
    start = text.find("{")
    if start == -1:
        raise JSONDecodeError("no '{' found", text, 0)

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise JSONDecodeError("unterminated object", text, start)


def _parse_model_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise TypeError(f"unexpected content type: {type(content).__name__}")

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except JSONDecodeError:
        pass

    candidate = _extract_first_json_object(content)
    parsed2 = json.loads(candidate)
    if not isinstance(parsed2, dict):
        raise JSONDecodeError("not a JSON object", candidate, 0)
    return parsed2


def _select_next_work(
    *,
    conn,
    model_provider: str,
    model: str,
    prompt_version: str,
    limit: int,
) -> list[WorkItem]:
    rows = conn.execute(
        """
        SELECT
          p.photo_id,
          p.observation_id,
          COALESCE(p.url_large, p.url_square, p.url_original) AS image_url,
          o.description AS notes,
          COALESCE(c.attempt_count, 0) AS attempt_count
        FROM photos p
        JOIN observations o ON o.observation_id = p.observation_id
        LEFT JOIN classifications c
          ON c.photo_id = p.photo_id
         AND c.model_provider = %s
         AND c.model = %s
         AND c.prompt_version = %s
        WHERE COALESCE(p.url_large, p.url_square, p.url_original) IS NOT NULL
          AND (
            c.classification_id IS NULL
            OR (c.status = 'failed' AND (c.retry_after IS NULL OR c.retry_after <= now()))
          )
        ORDER BY p.photo_id ASC
        LIMIT %s
        """,
        (model_provider, model, prompt_version, limit),
    ).fetchall()

    items: list[WorkItem] = []
    for r in rows:
        items.append(
            WorkItem(
                photo_id=int(r["photo_id"]),
                observation_id=int(r["observation_id"]),
                image_url=str(r["image_url"]),
                notes=str(r["notes"] or ""),
                attempt_count=int(r["attempt_count"] or 0),
            )
        )
    return items


def _upsert_pending(
    *,
    conn,
    item: WorkItem,
    model_provider: str,
    model: str,
    prompt_version: str,
    prompt_hash_value: str,
    input_notes: str,
    input_notes_truncated: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO classifications (
          photo_id, observation_id, model_provider, model, prompt_version, prompt_hash,
          status, input_image_url, input_notes, input_notes_truncated
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s)
        ON CONFLICT (photo_id, model_provider, model, prompt_version) DO UPDATE SET
          updated_at = now(),
          status = 'pending',
          prompt_hash = EXCLUDED.prompt_hash,
          input_image_url = EXCLUDED.input_image_url,
          input_notes = EXCLUDED.input_notes,
          input_notes_truncated = EXCLUDED.input_notes_truncated,
          error = NULL
        """,
        (
            item.photo_id,
            item.observation_id,
            model_provider,
            model,
            prompt_version,
            prompt_hash_value,
            item.image_url,
            input_notes,
            input_notes_truncated,
        ),
    )


def _mark_success(
    *,
    conn,
    item: WorkItem,
    model_provider: str,
    model: str,
    prompt_version: str,
    output: dict[str, Any],
    raw_response: dict[str, Any],
) -> None:
    conn.execute(
        """
        UPDATE classifications
        SET status = 'succeeded',
            updated_at = now(),
            last_attempt_at = now(),
            attempt_count = attempt_count + 1,
            retry_after = NULL,
            output = %s::jsonb,
            raw_response = %s::jsonb,
            error = NULL
        WHERE photo_id = %s AND model_provider = %s AND model = %s AND prompt_version = %s
        """,
        (json.dumps(output), json.dumps(raw_response), item.photo_id, model_provider, model, prompt_version),
    )


def _mark_failed(
    *,
    conn,
    item: WorkItem,
    model_provider: str,
    model: str,
    prompt_version: str,
    error: str,
    retry_after_seconds: int,
    max_attempts: int,
    raw_response: dict[str, Any] | None = None,
) -> None:
    retry_after = utcnow() + timedelta(seconds=retry_after_seconds)
    conn.execute(
        """
        UPDATE classifications
        SET status = CASE WHEN attempt_count + 1 >= %s THEN 'permanent_failed' ELSE 'failed' END,
            updated_at = now(),
            last_attempt_at = now(),
            attempt_count = attempt_count + 1,
            retry_after = CASE WHEN attempt_count + 1 >= %s THEN NULL ELSE %s END,
            raw_response = COALESCE(%s::jsonb, raw_response),
            error = %s
        WHERE photo_id = %s AND model_provider = %s AND model = %s AND prompt_version = %s
        """,
        (
            max_attempts,
            max_attempts,
            retry_after,
            None if raw_response is None else json.dumps(raw_response),
            error,
            item.photo_id,
            model_provider,
            model,
            prompt_version,
        ),
    )


def _mark_permanent_failed(
    *,
    conn,
    item: WorkItem,
    model_provider: str,
    model: str,
    prompt_version: str,
    error: str,
    raw_response: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        UPDATE classifications
        SET status = 'permanent_failed',
            updated_at = now(),
            last_attempt_at = now(),
            attempt_count = attempt_count + 1,
            retry_after = NULL,
            raw_response = COALESCE(%s::jsonb, raw_response),
            error = %s
        WHERE photo_id = %s AND model_provider = %s AND model = %s AND prompt_version = %s
        """,
        (
            None if raw_response is None else json.dumps(raw_response),
            error,
            item.photo_id,
            model_provider,
            model,
            prompt_version,
        ),
    )


def _retry_seconds_for_attempt(attempt: int, base: int, cap: int) -> int:
    # attempt is 1-based
    return min(cap, base * (2 ** max(0, attempt - 1)))


def _classify_retry_policy(error: Exception, *, attempt: int) -> tuple[bool, int, str]:
    """
    Returns (permanent, retry_after_seconds, message).
    """
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            retry_after = error.response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                return False, int(retry_after), f"http {status} rate limited"
            return False, _retry_seconds_for_attempt(attempt, base=10, cap=300), f"http {status} rate limited"
        if 500 <= status < 600:
            return False, _retry_seconds_for_attempt(attempt, base=30, cap=1800), f"http {status} server error"
        # Most 4xx errors are permanent for the current model/prompt/input.
        return True, 0, f"http {status} client error"

    if isinstance(error, (httpx.TimeoutException, httpx.RequestError)):
        return False, _retry_seconds_for_attempt(attempt, base=10, cap=600), "network error"

    if isinstance(error, JSONDecodeError):
        # Usually means the model didn't return valid JSON. Retry a couple times, then stop.
        return False, _retry_seconds_for_attempt(attempt, base=60, cap=1800), "invalid JSON response"

    return False, _retry_seconds_for_attempt(attempt, base=60, cap=3600), "unexpected error"


def classify_openrouter(
    *,
    conn,
    api_key: str,
    model: str,
    prompt_version: str,
    prompt_path: str,
    notes_max_chars: int,
    max_workers: int,
    max_attempts: int,
    max_items: int,
    sleep_seconds: float = 0.0,
) -> dict[str, int]:
    ensure_schema(conn)

    # Note: only the main thread writes to the database connection. Worker threads
    # only call the OpenRouter API and return results to the main thread.
    model_provider = "openrouter"
    prompt = load_prompt(prompt_path)
    p_hash = prompt_hash(prompt)

    try:
        succeeded = failed = 0
        items = _select_next_work(conn=conn, model_provider=model_provider, model=model, prompt_version=prompt_version, limit=max_items)
        if not items:
            return {"succeeded": 0, "failed": 0}

        prepared: list[tuple[WorkItem, str, bool]] = []
        for item in items:
            notes = item.notes
            truncated = False
            if notes_max_chars and len(notes) > notes_max_chars:
                notes = notes[:notes_max_chars]
                truncated = True
            prepared.append((item, notes, truncated))

            _upsert_pending(
                conn=conn,
                item=item,
                model_provider=model_provider,
                model=model,
                prompt_version=prompt_version,
                prompt_hash_value=p_hash,
                input_notes=notes,
                input_notes_truncated=truncated,
            )
        conn.commit()

        def _worker(item_: WorkItem, notes_: str) -> dict[str, Any]:
            client = OpenRouterClient(OpenRouterConfig(api_key=api_key, model=model))
            try:
                return client.classify_image(image_url=item_.image_url, observer_notes=notes_, prompt=prompt)
            finally:
                client.close()

        max_workers = max(1, int(max_workers))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_worker, item, notes): (item, notes) for (item, notes, _tr) in prepared}
            for fut in as_completed(futures):
                item, notes = futures[fut]
                raw: dict[str, Any] | None = None
                try:
                    raw = fut.result()
                    content = raw["choices"][0]["message"]["content"]
                    output = _parse_model_json(content)
                    _mark_success(
                        conn=conn,
                        item=item,
                        model_provider=model_provider,
                        model=model,
                        prompt_version=prompt_version,
                        output=output,
                        raw_response=raw,
                    )
                    succeeded += 1
                except Exception as e:
                    attempt = item.attempt_count + 1
                    permanent, retry_seconds, reason = _classify_retry_policy(e, attempt=attempt)
                    msg = f"{reason}: {e}"
                    if permanent or attempt >= max_attempts:
                        _mark_permanent_failed(
                            conn=conn,
                            item=item,
                            model_provider=model_provider,
                            model=model,
                            prompt_version=prompt_version,
                            error=msg,
                            raw_response=raw,
                        )
                    else:
                        _mark_failed(
                            conn=conn,
                            item=item,
                            model_provider=model_provider,
                            model=model,
                            prompt_version=prompt_version,
                            error=msg,
                            retry_after_seconds=retry_seconds,
                            max_attempts=max_attempts,
                            raw_response=raw,
                        )
                    failed += 1
                    logger.warning("classification failed photo_id=%s attempt=%s: %s", item.photo_id, attempt, msg)

                conn.commit()
                if sleep_seconds:
                    time.sleep(sleep_seconds)

        return {"succeeded": succeeded, "failed": failed}
    finally:
        pass
