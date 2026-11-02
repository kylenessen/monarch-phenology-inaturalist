# Monarch Phenology iNaturalist

Building the most complete phenological dataset of monarch butterflies in North America by extracting life history information from iNaturalist observations using AI classification.

## Overview

This project aims to:
- Leverage existing iNaturalist observations of monarch butterflies
- Automatically classify observations into life history stages
- Maintain a continuously updated phenological dataset
- Enable research on monarch migration patterns, timing, and behavior

## Project Notes / Architecture

See `docs/ARCHITECTURE.md` for the current plan, data sources, pipeline, database approach, and licensing notes.

## Getting Started (uv + Postgres)

This repo uses `uv` for Python dependency management.

### Local (run the CLI)

- Create a Postgres database and set `DATABASE_URL`.
- Install deps: `uv sync`
- Initialize tables: `uv run monarch init-db`
- Ingest iNaturalist observations: `uv run monarch ingest`
- Classify a small batch (requires OpenRouter): `uv run monarch classify --max-items 25`
- Check progress/backlog: `uv run monarch stats`

Environment variables live in `.env` (copy from `.env.example`).

### Docker (background service)

- Copy config: `cp .env.example .env` (then set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`)
- Start: `docker compose up --build`

The container runs `monarch run` (periodic ingest + continuous classify).

## Status

The standalone [Jev life stage pilot](docs/JEV_BENCHMARK.md) downloads 100 annotated photos per stage and scores each photo independently. Run `uv run python -m monarch_phenology.benchmark_jev` with `TYPESAFE_API_KEY` in `.env`. It requires no database and saves resumable results under `runs/jev-pilot`.

The [first 400-photo pilot results](docs/JEV_PILOT_RESULTS.md) show 96.75 percent agreement with existing life stage annotations. The report also includes independent stage detection metrics and examples that need photo-level label review.

Early development. Project structure and data pipeline under construction.

## License

MIT License - See LICENSE file for details
