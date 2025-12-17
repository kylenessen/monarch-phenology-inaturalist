from __future__ import annotations

import logging
import signal
import time

import typer
from dotenv import load_dotenv

from .classify_openrouter import classify_openrouter
from .config import load_settings, validate_settings
from .db import connect, ensure_schema
from .ingest_inat import ingest_inat
from .logging_utils import setup_logging

app = typer.Typer(add_completion=False)
logger = logging.getLogger(__name__)


@app.command()
def init_db() -> None:
    """Create tables (safe to run multiple times)."""
    load_dotenv()
    s = load_settings()
    setup_logging(level=s.log_level)
    validate_settings(s)
    with connect(s.database_url) as conn:
        ensure_schema(conn)
    typer.echo("ok")


@app.command()
def ingest() -> None:
    """Fetch iNaturalist observations into Postgres."""
    load_dotenv()
    s = load_settings()
    setup_logging(level=s.log_level)
    validate_settings(s)
    with connect(s.database_url) as conn:
        stats = ingest_inat(
            conn=conn,
            taxon_id=s.inat_taxon_id,
            place_id=s.inat_place_id,
            quality_grade=s.inat_quality_grade,
            per_page=s.inat_per_page,
            backfill_days=s.inat_backfill_days,
            overlap_hours=s.inat_overlap_hours,
            sleep_seconds=s.inat_sleep_seconds,
            max_pages_per_run=s.inat_max_pages_per_run,
            max_retries=s.inat_max_retries,
            retry_backoff_seconds=s.inat_retry_backoff_seconds,
        )
    typer.echo(f"observations={stats['observations']} photos={stats['photos']}")


@app.command()
def classify(max_items: int = typer.Option(25, help="Max photos to classify this run.")) -> None:
    """Classify photos via OpenRouter (writes results to Postgres)."""
    load_dotenv()
    s = load_settings()
    setup_logging(level=s.log_level)
    validate_settings(s)
    if not s.openrouter_api_key or not s.openrouter_model:
        raise typer.BadParameter("Set OPENROUTER_API_KEY and OPENROUTER_MODEL.")

    with connect(s.database_url) as conn:
        stats = classify_openrouter(
            conn=conn,
            api_key=s.openrouter_api_key,
            model=s.openrouter_model,
            prompt_version=s.prompt_version,
            prompt_path=s.prompt_path,
            notes_max_chars=s.classify_notes_max_chars,
            max_workers=s.classify_max_workers,
            max_attempts=s.classify_max_attempts,
            max_items=max_items,
        )
    typer.echo(f"succeeded={stats['succeeded']} failed={stats['failed']}")


@app.command()
def run() -> None:
    """Run ingestion periodically and classification continuously."""
    load_dotenv()
    s = load_settings()
    setup_logging(level=s.log_level)
    validate_settings(s)
    if not s.openrouter_api_key or not s.openrouter_model:
        logger.warning("OPENROUTER_API_KEY/OPENROUTER_MODEL not set; classification will fail until configured.")

    shutting_down = False

    def _handle_signal(_signum: int, _frame) -> None:  # type: ignore[no-untyped-def]
        nonlocal shutting_down
        shutting_down = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    next_ingest = 0.0
    while not shutting_down:
        now = time.time()
        if now >= next_ingest:
            try:
                with connect(s.database_url) as conn:
                    ingest_inat(
                        conn=conn,
                        taxon_id=s.inat_taxon_id,
                        place_id=s.inat_place_id,
                        quality_grade=s.inat_quality_grade,
                        per_page=s.inat_per_page,
                        backfill_days=s.inat_backfill_days,
                        overlap_hours=s.inat_overlap_hours,
                        sleep_seconds=s.inat_sleep_seconds,
                        max_pages_per_run=s.inat_max_pages_per_run,
                        max_retries=s.inat_max_retries,
                        retry_backoff_seconds=s.inat_retry_backoff_seconds,
                    )
            except Exception as e:
                logger.exception("ingest error: %s", e)

            next_ingest = now + max(60, s.run_ingest_every_seconds)

        try:
            if s.openrouter_api_key and s.openrouter_model:
                with connect(s.database_url) as conn:
                    classify_openrouter(
                        conn=conn,
                        api_key=s.openrouter_api_key,
                        model=s.openrouter_model,
                        prompt_version=s.prompt_version,
                        prompt_path=s.prompt_path,
                        notes_max_chars=s.classify_notes_max_chars,
                        max_workers=s.classify_max_workers,
                        max_attempts=s.classify_max_attempts,
                        max_items=5,
                    )
        except Exception as e:
            logger.exception("classify error: %s", e)

        time.sleep(max(1, s.run_classify_every_seconds))

    logger.info("shutdown requested; exiting")


@app.command()
def stats() -> None:
    """Show basic counts (backlog, failures, recent throughput)."""
    load_dotenv()
    s = load_settings()
    setup_logging(level=s.log_level)
    validate_settings(s)

    with connect(s.database_url) as conn:
        ensure_schema(conn)

        total_obs = conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"]
        total_photos = conn.execute("SELECT count(*) AS n FROM photos").fetchone()["n"]
        classified_ok = conn.execute("SELECT count(*) AS n FROM classifications WHERE status = 'succeeded'").fetchone()["n"]
        failed = conn.execute("SELECT count(*) AS n FROM classifications WHERE status = 'failed'").fetchone()["n"]
        permanent_failed = conn.execute("SELECT count(*) AS n FROM classifications WHERE status = 'permanent_failed'").fetchone()["n"]

        backlog = conn.execute(
            """
            SELECT count(*) AS n
            FROM photos p
            LEFT JOIN classifications c
              ON c.photo_id = p.photo_id
             AND c.model_provider = 'openrouter'
             AND c.model = %s
             AND c.prompt_version = %s
            WHERE COALESCE(p.url_large, p.url_square, p.url_original) IS NOT NULL
              AND (
                c.classification_id IS NULL
                OR (c.status = 'failed' AND (c.retry_after IS NULL OR c.retry_after <= now()))
              )
            """,
            (s.openrouter_model or "", s.prompt_version),
        ).fetchone()["n"]

        ingested_last_24h = conn.execute(
            "SELECT count(*) AS n FROM observations WHERE last_seen_at >= now() - interval '24 hours'"
        ).fetchone()["n"]
        classified_last_24h = conn.execute(
            "SELECT count(*) AS n FROM classifications WHERE updated_at >= now() - interval '24 hours' AND status = 'succeeded'"
        ).fetchone()["n"]

    typer.echo(
        " ".join(
            [
                f"observations={total_obs}",
                f"photos={total_photos}",
                f"classified={classified_ok}",
                f"failed={failed}",
                f"permanent_failed={permanent_failed}",
                f"backlog={backlog}",
                f"ingested_24h={ingested_last_24h}",
                f"classified_24h={classified_last_24h}",
            ]
        )
    )
