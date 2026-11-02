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

The November 2, 2026 snapshot fetched 136,885 observations. It retained 121,442 after excluding 15,439 obscured or private locations and four conflicting or disputed stage annotations. The retained dataset contains 109,163 larvae and 12,279 pupae across 43 represented years. The default accuracy filter displays 113,634 observations. Another 7,808 have reported uncertainty greater than 1 km. Of the retained observations, 19,850 have unstated accuracy. These totals describe observation records, not independently verified animals.

### Antecedent weather pilot

The weather pilot selects 600 reproducible observations from 81,214 eligible records in 2001–2025 with known coordinate accuracy no worse than 1 km. Sampling covers 24 region, season, and stage combinations. Each stratum receives at least eight samples, with the remaining allocation proportional to its population. Sampling weights are retained so the report can show either raw counts or weighted percentages within each region. The California coastal region is inside California and within 50 km of the Natural Earth coastline. Eastern North America is east of 100 degrees west. Other western observations form the third group.

```sh
uv run python -m monarch_phenology.weather_pilot
uv run python -m monarch_phenology.weather_audit
uv run python -m monarch_phenology.weather_report
uv run python -m http.server 8769 --bind 127.0.0.1 --directory runs/weather-pilot
```

The original pilot report is preserved at [the historical weather report](http://127.0.0.1:8769/original-weather-report.html). It includes three histograms, selectable scatterplots, descriptive weighted correlations, region and season filters, life stage filters, Fahrenheit and Celsius, coverage counts, an observation-level CSV, and PNG and PDF figures. The expanded explorer below now occupies the main URL. Running `weather_report` reproduces the original page. Run `weather_explorer` afterward to restore the expanded page. Keep the server running while viewing either report. All chart assets are cached locally.

[Daymet V4 R1](https://daymet.ornl.gov/overview) provides daily minimum and maximum temperature estimates at 1 km. The temperature metrics are the lowest daily minimum and highest daily maximum over the exact 14 days before the observation, excluding the observation date. Complete coverage of all 14 dates is required. Daymet omits December 31 in leap years, so windows crossing that missing date are excluded without interpolation. Locations outside the Daymet mask remain unavailable. These are interpolated weather-station estimates, not direct measurements at each observation.

[MODIS MOD16A2GF V061](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD16A2GF) provides actual evapotranspiration at nominal 500 m resolution in eight-day composites. The AET metric is the total ET in the two most recent fully completed composites divided by their combined duration. This is usually 16 days, ending one to eight days before the observation. Year-end windows can be shorter. This is deliberately different from an exact 14-day daily AET median. No composite contains the observation date or a later day, although gap filling uses retrospective annual inputs. Both composites must have valid nonnegative ET, a good MODLAND quality bit, and science quality category 0 or 1. Values use the 0.1 scale factor and are reported in millimeters per day. Urban and other land-cover masks and failed quality flags stay missing, and the point is never moved to a nearby vegetated pixel.

Per-observation results, complete daily temperature windows, AET composite dates and quality flags, sampling strata, and original service responses are cached under `runs/weather-pilot`. Re-running resumes pending records. `--retry-errors` also retries saved request failures. `--limit 12` runs a small smoke test without changing the sample. To run a different sample or `--all`, choose a new output directory. The report refuses an unfinished run unless `--preview` explicitly labels it partial.

The weights correct the sampling design, not observer effort or missing weather data. AET masking can strongly change the geographic composition of complete cases, especially in urban coastal locations. Neither an empty histogram bin nor a Pearson correlation establishes a breeding threshold or temperature causation. The next inferential step would require comparable available conditions, such as matched background dates and locations, and explicit treatment of season, latitude, host plants, repeated observations, and detection effort.

The completed pilot has 595 complete temperature windows and 311 usable AET windows. Three sampled locations fall outside Daymet coverage and two windows cross the omitted leap-year date. Twelve of the 595 complete temperature windows reach freezing or below, and 15 reach at least 100 degrees Fahrenheit. Their sampling-weighted shares are about 1.08 and 1.75 percent. These describe associations among sampled observations, not survival limits. AET is available for only 18 of 110 California coastal records, compared with 252 of 408 eastern records and 41 of 82 other western records. Urban masks account for 246 missing AET windows, including 90 on the California coast.

The optional audit joins existing alive/dead annotations and checks extreme Daymet windows against ERA5-Land through Open-Meteo at about 9 km. It checks windows reaching freezing, 100 degrees Fahrenheit, or a daily temperature range of at least 40 degrees Celsius. The pilot has three records annotated dead, including the coldest pupa record. Of 26 weather windows cross-checked, one has a minimum or maximum differing by at least 10 degrees Celsius. Observation 180392679 has a Daymet minimum of -9.12 degrees Celsius and an ERA5-Land minimum of 12.4 degrees Celsius for the same dates. This is flagged for review. Original values remain unchanged, and the interactive report can exclude known-dead records or large weather disagreements. The screening rule is exploratory, not a validated error cutoff. The remaining 574 temperature windows were not independently cross-checked.

### Expanded weather and land-cover explorer

Open [the expanded explorer](http://127.0.0.1:8769/) for the same fixed 600-observation sample with all seven Daymet variables and year-matched USGS land cover. AET is omitted. The default axes show the median daily minimum and median daily maximum over the preceding 14 days. These are medians across the daily weather values for each observation, not medians across observations. The observed day is excluded. A seven-day alternative uses the same cached daily data.

```sh
uv run python -m monarch_phenology.weather_expand
uv run python -m monarch_phenology.landcover_pilot
uv run python -m monarch_phenology.weather_explorer
uv run python -m http.server 8769 --bind 127.0.0.1 --directory runs/weather-pilot
```

Both enrichment commands resume completed files, accept `--limit`, and accept `--retry-errors`. All seven Daymet variables are requested together. Expanded weather records live in `runs/weather-pilot/expanded`, land-cover results and raw responses in `runs/weather-pilot/landcover`, and original Daymet responses in the existing cache. The sample manifest and original pilot results are unchanged. The full continental and full observation downloads are not started by these commands.

The explorer supports arbitrary variable pairs, histogram and cumulative distributions, weighted quantile boxes, monthly medians, and individual daily-weather charts. Presets cover typical temperatures, cold extremes, rainfall and moisture, seasonal light, and land cover. Filters include region, stage, season, month, year range, land-cover category or availability, location uncertainty, alive/dead annotation, and the existing temperature audit. Comparisons can be grouped by region, stage, season, land cover, or life status. Users can choose raw counts or sampling-weighted distributions. Monthly summaries require at least three valid records in a group. Click a scatter point or table row to inspect the observation and its iNaturalist link. Tables and charts retain missing values as unavailable.

Daily variables support median, mean, and extreme temperatures, mean daily temperature range, days reaching freezing or 100 degrees Fahrenheit, rainfall totals, median rainfall, wettest day, wet days of at least 1 mm, median vapor pressure, mean daily solar energy, median daylight radiation, median and maximum snow water equivalent, and median day length. Latitude, seasonal day, and observation year are also available as axes. Solar energy uses daylight duration, not a 24-hour multiplier. Temperature range converts to Fahrenheit without adding 32. Each metric requires complete dates for its constituent variables. Missing leap-year December 31 is not interpolated, including in daily temperature charts.

[USGS Annual NLCD Collection 1.2](https://www.usgs.gov/data/annual-national-land-cover-database-nlcd-collection-1-products-ver-12-june-2026) supplies annual 30 m categories through 2025 for the contiguous U.S. The pipeline queries the official [MRLC land-cover WMS](https://www.mrlc.gov/data-services-page) at the reported point and exact observation year, using a 30 m request in EPSG 5070. It stores the native category code, label, query, year, retrieval time, product, and resolution. The service's NoData category 250 is unavailable, never a habitat. No prior-year substitution or movement to a nearby valid pixel is used. The available-year capabilities document is cached. Canada, Mexico, and other uncovered areas have no category. The 30 m uncertainty filter helps assess point-location sensitivity, but these categories do not measure nearby habitat composition or milkweed presence.

The completed expansion has 594 complete 14-day windows for all seven weather variables. Three points are outside Daymet coverage and two cross its omitted leap-year date. One expanded request repeatedly returns a server error. Its valid temperatures from the original pilot are retained with a `temperature_only_cached` status, leaving the five new variables unavailable. Thus 595 observations have complete 14-day temperature medians. At seven days, 596 have all seven variables. Land cover is available for 500 points, including all 110 California coastal points, 331 of 408 eastern points, and 59 of 82 other western points. The remaining 100 are outside coverage or NoData. Of the full sample, 419 have reported location uncertainty at most 30 m.

`expanded-observations.csv` contains both seven-day and 14-day summaries, source/status fields, original sampling weights, land-cover categories, and audit flags. Its temperatures are Celsius. `expanded-daily.csv` retains daily values in Daymet units, documented in the viewer. The filtered CSV follows the selected window and display units. The HTML embeds all data and uses a local Plotly asset, so it does not fetch observations or weather while browsing. `--preview` is required to build when observation enrichment files are still missing. Permanent coverage gaps and request failures remain explicitly counted in a completed report.

Validation includes 54 Python tests and a Chromium browser check of presets, metric choices, cumulative distributions, filtering, empty selections, individual daily charts, CSV download, and a 390-pixel mobile viewport. No browser script errors were observed. Median summaries reduce the influence of individual extremes but do not correct model errors, observer bias, seasonal confounding, or missing land cover.

### Full Daymet archive without AET

The new archive collects all seven Daymet variables together in one request per exact coordinate. These are daily minimum and maximum temperature, precipitation, vapor pressure, shortwave radiation, snow water equivalent, and day length. The [Daymet service](https://daymet.ornl.gov/web_services) supports multiple years in the same request. The archive saves complete required years, original CSV responses, metadata including elevation and software version, and parsed daily values with units. Repeated coordinates share a request. Coordinates are not rounded or merged using approximate grid cells. No MODIS, AET, Jev, or ERA5 requests are made by this command.

```sh
uv run python -m monarch_phenology.daymet_archive
uv run python -m monarch_phenology.daymet_archive --fetch --limit 3
uv run python -m monarch_phenology.daymet_archive --fetch
```

The first command prepares an offline plan. The second tests three pending requests. The third downloads all pending points. Results resume under `runs/daymet-full`, and `--retry-errors` retries saved request failures. The default four workers share the existing Daymet request pacing and retry logic. Keep the original pilot directory separate. Its completed AET results remain historical and its older command still requests AET.

The default archive follows the atlas accuracy filter, retaining public coordinates with reported uncertainty no greater than 1 km or unstated uncertainty. Unknown accuracy remains identifiable for sensitivity filters. `--strict-accuracy` removes it. The year cutoff defaults to 2025, the latest completed year used for this analysis. The old 2001 MODIS restriction no longer applies. Observations must have a full 60-day lookback within Daymet's 1980 onward coverage. Required preceding years are downloaded as well, allowing later 7, 14, 30, and 60-day analyses without new requests. Complete observation years include dates after the observation. Subsequent antecedent analyses must select only dates before it. Geographic coverage is evaluated during download. A planned observation does not guarantee usable weather data.

The November 2 plan contains 98,327 observations, including 17,097 with unknown accuracy, at 92,620 exact coordinates across 95,276 coordinate-year combinations. Counts exclude 16,153 records outside the selected dates or lookback, 6,962 with uncertainty over 1 km, 15,439 private or obscured records, and four disputed stage annotations. Exclusions are sequential. Three live point requests passed with all seven variables and complete requested Daymet years. The large download has not been started.

Daymet's [variable definitions](https://daymet.ornl.gov/overview) distinguish actual vapor pressure in pascals from relative humidity or vapor pressure deficit. Shortwave radiation is a daylight average in watts per square meter. Multiplying by day length in seconds and dividing by one million gives daily megajoules per square meter. Vapor pressure, radiation, and snowpack are modeled using the primary temperature and precipitation inputs, so they are not independent measurements. Missing values remain null. Daymet's missing leap-year December 31 is not interpolated. Daily data will support rainfall totals, wet-day counts, day-length summaries, and temperature accumulation without additional service calls, but biological thresholds still require a separate analysis choice.

Early development. Project structure and data pipeline under construction.

## License

MIT License - See LICENSE file for details
