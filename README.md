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

The original pilot report is preserved at [the historical weather report](http://127.0.0.1:8769/original-weather-report.html). It includes three histograms, selectable scatterplots, descriptive weighted correlations, region and season filters, life stage filters, Fahrenheit and Celsius, coverage counts, an observation-level CSV, and PNG and PDF figures. The full seven-day weather lab now occupies the main URL. Running `weather_report` reproduces the original page. Run `weather_full_explorer` afterward to restore the full weather lab. Keep the server running while viewing either report. All chart assets are cached locally.

[Daymet V4 R1](https://daymet.ornl.gov/overview) provides daily minimum and maximum temperature estimates at 1 km. The temperature metrics are the lowest daily minimum and highest daily maximum over the exact 14 days before the observation, excluding the observation date. Complete coverage of all 14 dates is required. Daymet omits December 31 in leap years, so windows crossing that missing date are excluded without interpolation. Locations outside the Daymet mask remain unavailable. These are interpolated weather-station estimates, not direct measurements at each observation.

[MODIS MOD16A2GF V061](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD16A2GF) provides actual evapotranspiration at nominal 500 m resolution in eight-day composites. The AET metric is the total ET in the two most recent fully completed composites divided by their combined duration. This is usually 16 days, ending one to eight days before the observation. Year-end windows can be shorter. This is deliberately different from an exact 14-day daily AET median. No composite contains the observation date or a later day, although gap filling uses retrospective annual inputs. Both composites must have valid nonnegative ET, a good MODLAND quality bit, and science quality category 0 or 1. Values use the 0.1 scale factor and are reported in millimeters per day. Urban and other land-cover masks and failed quality flags stay missing, and the point is never moved to a nearby vegetated pixel.

Per-observation results, complete daily temperature windows, AET composite dates and quality flags, sampling strata, and original service responses are cached under `runs/weather-pilot`. Re-running resumes pending records. `--retry-errors` also retries saved request failures. `--limit 12` runs a small smoke test without changing the sample. To run a different sample or `--all`, choose a new output directory. The report refuses an unfinished run unless `--preview` explicitly labels it partial.

The weights correct the sampling design, not observer effort or missing weather data. AET masking can strongly change the geographic composition of complete cases, especially in urban coastal locations. Neither an empty histogram bin nor a Pearson correlation establishes a breeding threshold or temperature causation. The next inferential step would require comparable available conditions, such as matched background dates and locations, and explicit treatment of season, latitude, host plants, repeated observations, and detection effort.

The completed pilot has 595 complete temperature windows and 311 usable AET windows. Three sampled locations fall outside Daymet coverage and two windows cross the omitted leap-year date. Twelve of the 595 complete temperature windows reach freezing or below, and 15 reach at least 100 degrees Fahrenheit. Their sampling-weighted shares are about 1.08 and 1.75 percent. These describe associations among sampled observations, not survival limits. AET is available for only 18 of 110 California coastal records, compared with 252 of 408 eastern records and 41 of 82 other western records. Urban masks account for 246 missing AET windows, including 90 on the California coast.

The optional audit joins existing alive/dead annotations and checks extreme Daymet windows against ERA5-Land through Open-Meteo at about 9 km. It checks windows reaching freezing, 100 degrees Fahrenheit, or a daily temperature range of at least 40 degrees Celsius. The pilot has three records annotated dead, including the coldest pupa record. Of 26 weather windows cross-checked, one has a minimum or maximum differing by at least 10 degrees Celsius. Observation 180392679 has a Daymet minimum of -9.12 degrees Celsius and an ERA5-Land minimum of 12.4 degrees Celsius for the same dates. This is flagged for review. Original values remain unchanged, and the interactive report can exclude known-dead records or large weather disagreements. The screening rule is exploratory, not a validated error cutoff. The remaining 574 temperature windows were not independently cross-checked.

### Full weather lab

[The weather lab](http://127.0.0.1:8769/) now uses all 113,634 retained observations from the completed seven-day point run. The habitat comparison shows 55,600 developed and 16,416 natural-cover observations. Another 7,961 agricultural records and 33,657 records without land cover remain available through the habitat filter. Complete weather is available for 97,547 observations. There are 84 incomplete windows, 198 observations with failed weather lookups, 510 outside geographic weather coverage, and 15,295 outside available weather years. Land cover is available for 79,977 observations. These are observation counts, not distinct animals or habitat preference estimates.

```sh
uv run python -m monarch_phenology.weather_full_explorer
uv run python -m http.server 8769 --bind 127.0.0.1 --directory runs/weather-pilot
```

The builder reads `runs/weather-full-7d/observations.sqlite` without modifying it. It requires all lookups to have reached a terminal status and final CSV exports to be current. It publishes the lab at the existing URL and preserves the previous pilot at `pilot-weather-lab.html`. It makes no new weather or land-cover calls. The default output uses the pilot's cached geography and Plotly assets. Rebuilding the historical pilot or report replaces the main page, so run `weather_full_explorer` afterward to restore the full lab.

[All observations](http://127.0.0.1:8769/#all) opens an ungrouped view with all observation filters cleared, including habitat and coordinate uncertainty. The matching preset keeps the chosen axes and units, combines every record into one plot group, and hides the habitat comparison bars. Agriculture and unavailable land cover remain included. Records missing a selected weather variable still cannot appear in that weather plot.

The default full-data plot now shows coldest daily minimum on the horizontal axis and hottest daily minimum on the vertical axis. [Overnight extremes](http://127.0.0.1:8769/#overnight) opens this ungrouped view directly. Hottest daily minimum is `max(tmin)` over the seven preceding days, not `max(tmax)`. It is derived from the cached daily lows when the lab is built and requires a complete temperature window. The source archive remains unchanged. The lab's complete and filtered summary CSV downloads include the new metric. The full CSV field is `tmin_highest_7d` in Celsius.

The default plot shows five discrete density bands within the 99% highest-density region. Individual points and the outline are hidden. Cells below the 99% region cutoff are masked, leaving a white exterior without gridlines. The five Esri Blue 10 colors occupy equal-width density intervals from the cutoff to the peak. Color interpolation and display smoothing are disabled, so cells and levels remain distinct. The Plot layers control also offers density with fine points, a 95% density region with fine points, both overlays, and points alone. All valid selected pairs contribute with equal weight to one pooled surface, even when point colors show categories. Density uses bilinear binning and a separable Gaussian kernel with a standard deviation of 1.5 cells, on an 80, 128, or 192 cell square grid. Padding preserves the mass. The selected 95% or 99% boundary follows the density cutoff obtained by accumulating the highest-density cells until they contain that percentage of the smoothed mass. Separate islands are possible. This is approximate smoothed coverage, not a confidence interval or a claim that exactly that percentage of raw observations lie inside the polygon. Fewer than 20 pairs or a constant axis produce points without a density region.

The color scale uses the official [Esri Blue 10 ramp](https://developers.arcgis.com/javascript/latest/visualization/symbols-color-ramps/esri-color-ramps/), from `#eee2cf` through `#dbd0b9`, `#aabdb5`, and `#74a2b3` to `#3b758c`. Density intensity is relative to the peak of the current selection. Point size and density detail are adjustable. Dashed reference lines mark freezing at 32°F and heat at 100°F on each absolute-temperature axis. The values convert to 0°C and approximately 37.8°C when Celsius is selected. Temperature guides can be hidden and do not appear on non-temperature or temperature-range axes. Axis ranges include both guides when enabled. Fine points remain selectable above either layer. The density math checks run with `node --test tests/test_weather_density.cjs` and verify mass conservation, the 95% cutoff, unit-conversion invariance, separated clusters, and sparse or degenerate input.

The full lab uses only D−7 through D−1 and equal observation weights. Counts are the default, with within-group percentages available. All 19,850 records with unknown coordinate uncertainty are retained by default. The unknown-only filter isolates them, and every numeric uncertainty filter excludes them. The pilot ERA5 audit is not presented as an audit of the full run. Missing weather and land cover remain explicitly unavailable.

Every matching observation contributes to charts, summaries, correlations, and filtered exports. The scatterplot uses WebGL, the table displays 100 rows per page, and daily series load from local compressed files when inspected. The initial compressed summary payload is about 14 MiB. Daily data stay out of that initial payload. Full compressed CSV downloads use the completed archive exports, with the hottest daily minimum appended to the lab summary download from cached daily values. Join their `point_key` fields and the seven-day date window to associate the normalized daily rows with observations. The filtered CSV uses the chosen temperature units. The original 600-point pilot keeps its 14-day summaries and sampling weights.

Validation includes 61 Python tests, archive-to-viewer checks for daily dates and values, and browser checks of full-data filters, unknown uncertainty, percentages, presets, pagination, filtered downloads, and mobile layout.

### Historical expanded pilot explorer

Open [the preserved pilot explorer](http://127.0.0.1:8769/pilot-weather-lab.html) for the same fixed 600-observation sample with all seven Daymet variables and year-matched USGS land cover. AET is omitted. The default axes show the median daily minimum and median daily maximum over the preceding 14 days, grouped by developed versus natural cover. These are medians across the daily weather values for each observation, not medians across observations. The observed day is excluded. A seven-day alternative uses the same cached daily data.

The simple habitat comparison combines all four developed classes, NLCD codes 21 through 24, including developed open space such as lawns and parks. Natural cover combines the recognized forest, shrub, grassland, wetland, water, snow, and barren classes. Pasture/hay and cultivated crops remain Agriculture, not natural cover. Missing categories remain Unavailable. The initial comparison displays 364 developed and 96 natural-cover observations. The habitat filter can include the 40 agricultural and 100 unavailable records, or show any group alone. A prominent two-bar chart shows raw observation counts for developed and natural cover in the current selection. It always uses unweighted counts, independent of weather distribution weighting. Agricultural and unavailable records are reported separately below the chart. These describe mapped observation locations, not habitat availability or preference. Original categories remain available, and the summary and filtered CSV exports include `habitat_group`.

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

### Full seven-day point archive

The active full run uses point lookups and retrieves only D−7 through D−1 for each eligible observation. It includes all seven daily Daymet variables, seven-day summaries, exact-year USGS land-cover categories, and the developed/natural/agriculture grouping. It does not invoke the full-year archive command below. The run finished on November 2, 2026, with remaining request errors explicitly recorded. The full weather lab is published at the existing explorer URL, and the 600-observation pilot is preserved separately.

```sh
uv run python -m monarch_phenology.weather_full --workers 64 --interval 0.015625
uv run python -m monarch_phenology.weather_full --plan-only
uv run python -m monarch_phenology.weather_full --retry-errors --workers 4 --interval 1
uv run python -m monarch_phenology.weather_full --export-only
```

The output directory is `runs/weather-full-7d`. [The local progress page](http://127.0.0.1:8770/) refreshes every 15 seconds and displays retrieval progress, partial habitat counts, and storage use. The background downloader was started with `caffeinate -i` to prevent idle system sleep while it runs. It needs this Mac and its network connection to remain available. Progress is checkpointed after each result. The same command resumes after an interruption. An exclusive run lock prevents competing downloaders from writing the same directory. The progress server can be restarted with `uv run python -m http.server 8770 --bind 127.0.0.1 --directory runs/weather-full-7d`.

The November 2 plan retains 113,634 public, unambiguous larva/pupa observations under the atlas filter. This includes 19,850 with unknown coordinate uncertainty, explicitly identified. It excludes 7,808 with uncertainty above 1 km, 15,439 obscured/private observations, and four disputed stage annotations. Seven-day weather dates are eligible for 98,339 records. Land-cover years are eligible for 98,326. The remaining records are retained with unavailable-year statuses rather than dropped. A January 1, 2026 observation can still have a valid weather window entirely in 2025, although its 2026 land-cover year is unavailable. Land-cover geographic coverage is determined by the point service, with NoData preserved.

There are 95,167 distinct weather requests and 93,238 distinct coordinate/year land-cover requests before cache reuse. The pilot supplied 595 reusable weather requests and 598 land-cover requests. Duplicate coordinates and identical requested periods share a result. The accelerated run has 64 parallel workers per provider, 128 total. The initial one-second shared request interval was conservative and imposed a roughly 26-hour lower bound. The accelerated run uses `--workers 64 --interval 0.015625`, allowing up to 64 request starts per second per provider. Workers and request rates are bounded at 64 per provider. This is an operational setting, not a published provider allowance. Staged tests checked 2, 4, 8, 16, 24, 32, 48, and 64 workers with corresponding request caps. The last 7,000-lookup trial averaged 27.8 useful weather completions and 57.1 useful land-cover completions per second, including startup and final exports. It had no failed lookups or HTTP 429/503 responses. Useful completions include explicit coverage outcomes and exclude request failures. There was no clear throughput drop-off at 64. Tuning stopped there because the measured rate already met the roughly one-hour remaining-time target. Trial logs and summaries are saved under `runs/weather-full-7d/trial-*`. The observed rate, rather than the target rate, drives the progress-page estimate. HTTP 429 or 503 responses impose a provider-wide cooldown, honor Retry-After, and double that provider's request spacing. Three consecutive server errors also slow the provider. The known temporary USGS gateway route-404 response is retried as a service failure, not treated as geographic NoData. Responses already in flight extend the shared cooldown but multiply spacing only once per failure burst. Retry-After still extends the pause. After 100 successful responses, spacing gradually returns toward the configured target. Recorded adaptive slowdowns and outstanding cooldowns are restored when restarting from a checkpoint, so tuning does not reset a provider backoff. Transient failures are retried, then recorded for an explicit `--retry-errors` pass. Existing persistent weather errors are retained separately while remaining new lookups finish. Retry them separately at conservative concurrency, since a batch of known failing points can otherwise consume all workers and trigger repeated provider backoff. Runtime settings, code fingerprints, HTTP response counts, and measured throughput are recorded. The progress page estimates remaining time from completed lookups per second. Later retries, provider slowdowns, and interruptions can extend that estimate.

`observations.sqlite` is the authoritative archive. `observations` stores IDs, dates, stages, coordinates, location uncertainty, human alive/dead annotations, and links to enrichment requests. `weather_daily` stores all seven daily variables once per exact coordinate and date. `weather_summaries` stores seven-day metrics once per unique request. `landcover_results` stores original categories and simplified habitat groups. `requests` contains parameters, result status, attempt count, retrieval time, compressed original responses, error details, and cache provenance. `metadata` records configuration, source fingerprint, product information, units, and pipeline fingerprint. `excluded_observations` records excluded IDs and reasons. `enriched_observations` is a convenient joined SQL view. No sampling weights are needed for this full census of the retained atlas records.

The daily weather units are degrees Celsius for minimum and maximum temperature, millimeters per day for precipitation, pascals for vapor pressure, watts per square meter averaged over daylight for radiation, kilograms per square meter for snow water equivalent, and seconds per day for daylight duration. Temperature summaries use Celsius. Snow and rain zeros remain valid. Missing values and omitted leap-year dates are not interpolated. Metrics require all seven constituent dates. Original pilot responses can contain 14 days, but only the seven requested days are inserted into this run's daily table and summaries. Original cached response provenance is retained.

The downloader creates `observations.csv.gz` and `weather-daily.csv.gz` at the end of an invocation. The progress page states when a CSV snapshot was generated. These snapshots are not updated after each observation. `--export-only` regenerates them when no downloader owns the directory. SQLite uses a write-ahead journal while active. Use a read-only SQLite connection for live analysis and the SQLite backup API for a consistent live backup. Do not copy only the main database file while a writer is active. Closing the downloader checkpoints committed data. The directory is excluded from Git, so code commits are not data backups.

For daily weather aligned to individual observations, join on `point_key` and restrict dates to the observation's own window. This preserves separate observations that share a location while avoiding duplicated weather storage.

```sql
SELECT o.id, o.observed_on, d.*
FROM observations AS o
JOIN weather_daily AS d ON d.point_key = o.point_key
WHERE d.date >= date(o.observed_on, '-7 days')
  AND d.date < o.observed_on;
```

At most 688,373 daily observation-date records are needed before deduplicating overlapping locations and windows. This is about 50 times fewer than the earlier full-year plan. The actual daily table will be smaller. The storage estimate is hundreds of megabytes for the structured archive, rather than continental raster volumes. The starting SQLite file, which includes the complete request plan, is approximately 192 MiB. Final size depends on responses and SQLite allocation. The implementation passed 58 Python tests, including shared cooldown and restart behavior, and a desktop/mobile progress-page browser check.

### Earlier full-year Daymet archive prototype

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

## Interactive research notes

The [MDX note experiment](experiments/mdx-notes/README.md) combines narrative prose with a live weather figure and controls for life stage and temperature units. The weather lab accepts `?embed=plot&stage=pupa&units=C#overnight` for a compact figure that can also be embedded directly in an ordinary Obsidian Markdown note. The experiment includes build and startup instructions. Local servers must be running to use the interactive figures. The accompanying Notes vault discussion retains a static figure for offline reading.

## License

MIT License - See LICENSE file for details
