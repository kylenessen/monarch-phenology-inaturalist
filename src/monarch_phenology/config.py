from __future__ import annotations

from dataclasses import dataclass
from os import getenv


def _get_int(name: str, default: int) -> int:
    value = getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = getenv(name)
    if value is None or value == "":
        return default
    return float(value)


@dataclass(frozen=True)
class Settings:
    database_url: str

    inat_taxon_id: int
    inat_place_id: int
    inat_quality_grade: str
    inat_per_page: int
    inat_backfill_days: int
    inat_overlap_hours: int
    inat_sleep_seconds: float
    inat_max_pages_per_run: int
    inat_max_retries: int
    inat_retry_backoff_seconds: float

    openrouter_api_key: str | None
    openrouter_model: str | None
    prompt_version: str
    prompt_path: str
    classify_max_workers: int
    classify_notes_max_chars: int
    classify_max_attempts: int

    run_ingest_every_seconds: int
    run_classify_every_seconds: int
    log_level: str


def load_settings() -> Settings:
    return Settings(
        database_url=getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/monarch"),
        inat_taxon_id=_get_int("INAT_TAXON_ID", 48662),
        inat_place_id=_get_int("INAT_PLACE_ID", 62068),
        inat_quality_grade=getenv("INAT_QUALITY_GRADE", "research"),
        inat_per_page=_get_int("INAT_PER_PAGE", 200),
        inat_backfill_days=_get_int("INAT_BACKFILL_DAYS", 7),
        inat_overlap_hours=_get_int("INAT_OVERLAP_HOURS", 24),
        inat_sleep_seconds=_get_float("INAT_SLEEP_SECONDS", 0.5),
        inat_max_pages_per_run=_get_int("INAT_MAX_PAGES_PER_RUN", 0),
        inat_max_retries=_get_int("INAT_MAX_RETRIES", 5),
        inat_retry_backoff_seconds=_get_float("INAT_RETRY_BACKOFF_SECONDS", 2.0),
        openrouter_api_key=getenv("OPENROUTER_API_KEY") or None,
        openrouter_model=getenv("OPENROUTER_MODEL") or None,
        prompt_version=getenv("PROMPT_VERSION", "v1"),
        prompt_path=getenv("PROMPT_PATH", "prompts/v1.txt"),
        classify_max_workers=_get_int("CLASSIFY_MAX_WORKERS", 2),
        classify_notes_max_chars=_get_int("CLASSIFY_NOTES_MAX_CHARS", 2000),
        classify_max_attempts=_get_int("CLASSIFY_MAX_ATTEMPTS", 8),
        run_ingest_every_seconds=_get_int("RUN_INGEST_EVERY_SECONDS", 86400),
        run_classify_every_seconds=_get_int("RUN_CLASSIFY_EVERY_SECONDS", 10),
        log_level=getenv("LOG_LEVEL", "INFO"),
    )


def validate_settings(s: Settings) -> None:
    if not s.database_url:
        raise ValueError("DATABASE_URL is required")
    if s.inat_per_page <= 0 or s.inat_per_page > 200:
        raise ValueError("INAT_PER_PAGE must be between 1 and 200")
    if s.inat_backfill_days < 0:
        raise ValueError("INAT_BACKFILL_DAYS must be >= 0")
    if s.inat_overlap_hours < 0:
        raise ValueError("INAT_OVERLAP_HOURS must be >= 0")
    if s.inat_sleep_seconds < 0:
        raise ValueError("INAT_SLEEP_SECONDS must be >= 0")
    if s.inat_max_pages_per_run < 0:
        raise ValueError("INAT_MAX_PAGES_PER_RUN must be >= 0 (0 means unlimited)")
    if s.inat_max_retries < 0:
        raise ValueError("INAT_MAX_RETRIES must be >= 0")
    if s.inat_retry_backoff_seconds < 0:
        raise ValueError("INAT_RETRY_BACKOFF_SECONDS must be >= 0")
    if s.classify_max_workers <= 0:
        raise ValueError("CLASSIFY_MAX_WORKERS must be >= 1")
    if s.classify_notes_max_chars < 0:
        raise ValueError("CLASSIFY_NOTES_MAX_CHARS must be >= 0")
    if s.classify_max_attempts <= 0:
        raise ValueError("CLASSIFY_MAX_ATTEMPTS must be >= 1")
