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

    openrouter_api_key: str | None
    openrouter_model: str | None
    prompt_version: str
    classify_max_workers: int
    classify_notes_max_chars: int

    run_ingest_every_seconds: int
    run_classify_every_seconds: int


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
        openrouter_api_key=getenv("OPENROUTER_API_KEY") or None,
        openrouter_model=getenv("OPENROUTER_MODEL") or None,
        prompt_version=getenv("PROMPT_VERSION", "v1"),
        classify_max_workers=_get_int("CLASSIFY_MAX_WORKERS", 2),
        classify_notes_max_chars=_get_int("CLASSIFY_NOTES_MAX_CHARS", 2000),
        run_ingest_every_seconds=_get_int("RUN_INGEST_EVERY_SECONDS", 86400),
        run_classify_every_seconds=_get_int("RUN_CLASSIFY_EVERY_SECONDS", 10),
    )

