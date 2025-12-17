from __future__ import annotations

import time

import typer
from dotenv import load_dotenv

from .classify_openrouter import classify_openrouter
from .config import load_settings
from .db import connect, ensure_schema
from .ingest_inat import ingest_inat

app = typer.Typer(add_completion=False)


@app.command()
def init_db() -> None:
    """Create tables (safe to run multiple times)."""
    load_dotenv()
    s = load_settings()
    with connect(s.database_url) as conn:
        ensure_schema(conn)
    typer.echo("ok")


@app.command()
def ingest() -> None:
    """Fetch iNaturalist observations into Postgres."""
    load_dotenv()
    s = load_settings()
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
        )
    typer.echo(f"observations={stats['observations']} photos={stats['photos']}")


@app.command()
def classify(max_items: int = typer.Option(25, help="Max photos to classify this run.")) -> None:
    """Classify photos via OpenRouter (writes results to Postgres)."""
    load_dotenv()
    s = load_settings()
    if not s.openrouter_api_key or not s.openrouter_model:
        raise typer.BadParameter("Set OPENROUTER_API_KEY and OPENROUTER_MODEL.")

    with connect(s.database_url) as conn:
        stats = classify_openrouter(
            conn=conn,
            api_key=s.openrouter_api_key,
            model=s.openrouter_model,
            prompt_version=s.prompt_version,
            notes_max_chars=s.classify_notes_max_chars,
            max_workers=s.classify_max_workers,
            max_items=max_items,
        )
    typer.echo(f"succeeded={stats['succeeded']} failed={stats['failed']}")


@app.command()
def run() -> None:
    """Run ingestion periodically and classification continuously."""
    load_dotenv()
    s = load_settings()
    if not s.openrouter_api_key or not s.openrouter_model:
        typer.echo("OPENROUTER_API_KEY/OPENROUTER_MODEL not set; classification will fail until configured.")

    next_ingest = 0.0
    while True:
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
                    )
            except Exception as e:  # noqa: BLE001
                typer.echo(f"ingest error: {e}")

            next_ingest = now + max(60, s.run_ingest_every_seconds)

        try:
            if s.openrouter_api_key and s.openrouter_model:
                with connect(s.database_url) as conn:
                    classify_openrouter(
                        conn=conn,
                        api_key=s.openrouter_api_key,
                        model=s.openrouter_model,
                        prompt_version=s.prompt_version,
                        notes_max_chars=s.classify_notes_max_chars,
                        max_workers=s.classify_max_workers,
                        max_items=5,
                    )
        except Exception as e:  # noqa: BLE001
            typer.echo(f"classify error: {e}")

        time.sleep(max(1, s.run_classify_every_seconds))
