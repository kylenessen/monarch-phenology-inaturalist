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

The [second 400-photo pilot](docs/JEV_PILOT_V2_RESULTS.md) uses fresh observations and adds empty chrysalis, no obvious monarch, dead remains, clustering, nectaring and coarse early-versus-late larval development. Its expanded reviewer supports manual correction of each label.

### Weekly monarch atlas

The standalone map downloads all available North American monarch observations with community larva or pupa annotations. It uses observation dates, excludes eggs and adults, and makes no model calls. Downloads are resumable and cached under `runs/phenology-map`. The first download takes several minutes because requests are paced below 60 per minute. Metadata is fetched without downloading photos.

```sh
uv run python -m monarch_phenology.phenology_map
uv run python -m http.server 8768 --bind 127.0.0.1 --directory runs/phenology-map
```

Open [the local atlas](http://127.0.0.1:8768/). Keep the server running while using the map. The page supports play and pause, weekly scrubbing, individual years, an all-years seasonal cycle, stage filters, location-accuracy filters, and every H3 resolution from 0 through 15. It starts at resolution 4, averaging about 1,770 square kilometers per cell. Resolutions 5 and 6 average about 253 and 36 square kilometers. Cell size is independent of map zoom. Click a hexagon to inspect its observation links.

The yellow-to-orange colors count unique observations per hexagon per week, not animals or population density. Color thresholds stay fixed across time, year filters, stage filters, and zoom. Coarser resolutions use higher thresholds. Legend values mark the lower bound of each color bin. The seasonal view pools counts across years without normalizing observer effort. Individual years use seven-day windows starting January 1, with a short final window. Seasonal pooling aligns month and day on a leap-year calendar, so February 26 through March 3 spans six days in non-leap years. The current year stops at the snapshot date.

The source query includes all quality grades and photo observations not marked captive. It uses iNaturalist's North America place, 97394, and monarch taxon 48662 including its descendants. Conflicting or disputed stage annotations and obscured or private coordinates are excluded. The default accuracy filter accepts reported uncertainty up to 1 km and unstated uncertainty. A stricter option removes unstated accuracy. High H3 resolutions do not imply equally precise coordinates. Community labels are not independently audited, and a pupa annotation alone does not distinguish an occupied chrysalis from an empty one.

Use `--build-only` to regenerate the page from a completed cache. Use a different `--output` directory for a fresh snapshot. `--fetch-only` downloads metadata without building. `--build-only --preview` builds an explicitly marked partial preview during a download. A normal build refuses incomplete downloads. The HTML embeds its dataset and uses adjacent, versioned Leaflet and H3 assets. Only the OpenStreetMap background tiles need a network connection during viewing. Source pages, query parameters, fetch dates, and exclusion counts remain in the output directory for auditing.

Early development. Project structure and data pipeline under construction.

## License

MIT License - See LICENSE file for details
