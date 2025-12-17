from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row


SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS observations (
      observation_id BIGINT PRIMARY KEY,
      inat_url TEXT,
      taxon_id BIGINT,
      taxon_name TEXT,
      taxon_preferred_common_name TEXT,
      quality_grade TEXT,
      captive BOOLEAN,
      license_code TEXT,
      observed_at TIMESTAMPTZ,
      observed_on DATE,
      created_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ,
      latitude DOUBLE PRECISION,
      longitude DOUBLE PRECISION,
      positional_accuracy INTEGER,
      place_guess TEXT,
      user_id BIGINT,
      user_login TEXT,
      description TEXT,
      first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      raw JSONB NOT NULL
    );
    """,
    "ALTER TABLE observations ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now();",
    "ALTER TABLE observations ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now();",
    "CREATE INDEX IF NOT EXISTS observations_updated_at_idx ON observations (updated_at);",
    "CREATE INDEX IF NOT EXISTS observations_last_seen_at_idx ON observations (last_seen_at);",
    "CREATE INDEX IF NOT EXISTS observations_observed_on_idx ON observations (observed_on);",
    "CREATE INDEX IF NOT EXISTS observations_place_guess_idx ON observations (place_guess);",
    """
    CREATE TABLE IF NOT EXISTS photos (
      photo_id BIGINT PRIMARY KEY,
      observation_id BIGINT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
      position INTEGER,
      url_square TEXT,
      url_large TEXT,
      url_original TEXT,
      license_code TEXT,
      attribution TEXT,
      first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      raw JSONB NOT NULL
    );
    """,
    "ALTER TABLE photos ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now();",
    "ALTER TABLE photos ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now();",
    "CREATE INDEX IF NOT EXISTS photos_observation_id_idx ON photos (observation_id);",
    "CREATE INDEX IF NOT EXISTS photos_last_seen_at_idx ON photos (last_seen_at);",
    """
    CREATE TABLE IF NOT EXISTS classifications (
      classification_id BIGSERIAL PRIMARY KEY,
      photo_id BIGINT NOT NULL REFERENCES photos(photo_id) ON DELETE CASCADE,
      observation_id BIGINT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
      model_provider TEXT NOT NULL DEFAULT 'openrouter',
      model TEXT NOT NULL,
      prompt_version TEXT NOT NULL,
      prompt_hash TEXT,
      status TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_attempt_at TIMESTAMPTZ,
      attempt_count INTEGER NOT NULL DEFAULT 0,
      retry_after TIMESTAMPTZ,
      input_image_url TEXT,
      input_notes TEXT,
      input_notes_truncated BOOLEAN NOT NULL DEFAULT FALSE,
      output JSONB,
      raw_response JSONB,
      error TEXT
    );
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS classifications_unique_config_idx
    ON classifications (photo_id, model_provider, model, prompt_version);
    """,
    "CREATE INDEX IF NOT EXISTS classifications_status_idx ON classifications (status);",
    "CREATE INDEX IF NOT EXISTS classifications_retry_after_idx ON classifications (retry_after);",
    """
    CREATE TABLE IF NOT EXISTS sync_state (
      key TEXT PRIMARY KEY,
      value TEXT,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
]


@contextmanager
def connect(database_url: str):
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        yield conn


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)
    conn.commit()


def get_state(conn: psycopg.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = %s", (key,)).fetchone()
    return None if row is None else row["value"]


def set_state(conn: psycopg.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO sync_state (key, value, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        (key, value),
    )
    conn.commit()


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def dumps_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def chunked(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
