from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .db import ensure_schema, utcnow
from .openrouter_client import OpenRouterClient, OpenRouterConfig, prompt_hash


DEFAULT_PROMPT = """You are labeling monarch butterfly photos for a research dataset.

Return ONLY valid JSON.

Labels:
- life_stage: one of ["egg","larva","pupa","adult","unknown"]
- adult_behaviors: array of zero or more of ["nectaring","mating","clustering","ovipositing","flying"]
- larva_stage: one of ["early","late","unknown"] (only if life_stage is larva, else "unknown")

Rules:
- If you cannot tell from the photo, use "unknown".
- Use observer notes only as supporting context; prefer what is visible in the image.
"""


@dataclass(frozen=True)
class WorkItem:
    photo_id: int
    observation_id: int
    image_url: str
    notes: str


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
          o.description AS notes
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
) -> None:
    retry_after = utcnow() + timedelta(seconds=retry_after_seconds)
    conn.execute(
        """
        UPDATE classifications
        SET status = 'failed',
            updated_at = now(),
            last_attempt_at = now(),
            attempt_count = attempt_count + 1,
            retry_after = %s,
            error = %s
        WHERE photo_id = %s AND model_provider = %s AND model = %s AND prompt_version = %s
        """,
        (retry_after, error, item.photo_id, model_provider, model, prompt_version),
    )


def classify_openrouter(
    *,
    conn,
    api_key: str,
    model: str,
    prompt_version: str,
    notes_max_chars: int,
    max_workers: int,
    max_items: int,
    sleep_seconds: float = 0.0,
) -> dict[str, int]:
    ensure_schema(conn)

    model_provider = "openrouter"
    prompt = DEFAULT_PROMPT
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
                try:
                    raw = fut.result()
                    content = raw["choices"][0]["message"]["content"]
                    output = json.loads(content) if isinstance(content, str) else content
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
                except Exception as e:  # noqa: BLE001
                    _mark_failed(
                        conn=conn,
                        item=item,
                        model_provider=model_provider,
                        model=model,
                        prompt_version=prompt_version,
                        error=str(e),
                        retry_after_seconds=3600,
                    )
                    failed += 1

                conn.commit()
                if sleep_seconds:
                    time.sleep(sleep_seconds)

        return {"succeeded": succeeded, "failed": failed}
    finally:
        pass
