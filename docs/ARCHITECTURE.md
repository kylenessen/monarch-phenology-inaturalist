# Monarch Phenology Project — Architecture Notes

This document captures the current shared understanding of the project so we can pause and restart later without losing momentum.

## 1) Goal (plain language)

Build a dataset of Monarch butterfly observations (from iNaturalist) and use an AI vision model to label what’s happening in the photo (life stage + behaviors). Store everything in a database so we can:

- keep the dataset growing over time (“background service”)
- avoid re-processing the same observation/photo
- re-run classification later with improved prompts/models and keep history
- publish/share a clean dataset version

## 2) What we want the AI to label (first pass)

These are the categories we discussed. Each category should allow an “unknown / can’t tell” value.

- **Life stage**: egg, larva (caterpillar), pupa/chrysalis, adult
- **Adult behaviors**: nectaring, mating, clustering/roosting, ovipositing, flying
- **Larva detail (optional)**: early vs late instar (roughly “small” vs “large”)
- **Optional extras** (only if it works well): sex, wing condition (fresh vs worn)

Notes:
- We can start with fewer labels and add more later.
- Observation text (description/notes) may contain useful hints and can be included in the AI input.

## 3) Data sources (where records come from)

### Primary: iNaturalist API (recommended for “freshness”)

- Use iNaturalist’s public API to fetch observations and photos.
- Each observation has an `observation_id`. Each photo has a `photo_id`.
- We store those IDs so we can safely re-run the pipeline without duplicating work.

### Optional: GBIF (recommended for bulk + licensing clarity)

GBIF republishes iNaturalist **research-grade** observations and can be a good way to do big, repeatable pulls, especially when you want a “publishable” slice.

Tradeoffs:
- Pros: built for large downloads; clearer media licensing; stable export workflows.
- Cons: tends to be research-grade only; can lag behind iNaturalist; may include fewer iNat-specific fields.

We can use both:
- iNat API for “keep it fresh”
- GBIF for “big baseline import” and/or “public dataset export”

## 4) High-level pipeline (how data flows)

Think of this as two loops running in the background:

1) **Ingest loop (fast)**
   - Regularly asks: “Any new or updated Monarch observations since last time?”
   - Saves observations + photo records into Postgres.
   - Marks new photos as “needs classification”.

2) **Classify loop (slow, controlled)**
   - Picks the next photo that needs classification.
   - Downloads the image (or uses a direct image URL) and sends it to the vision model.
   - Saves the labels + details about how the labels were produced.

Key idea: ingestion is lightweight; classification is the bottleneck and we throttle it on purpose.

## 5) Running “in the background” (Docker)

Target setup:
- A Docker container (or a couple containers) runs on the home lab machine 24/7.
- It periodically syncs new observations and slowly works through classification work.

Likely Docker Compose services:
- `db`: Postgres
- `app`: Python service (does ingestion + classification; can be one process or two)

Scheduling options:
- simplest: the app runs an internal loop and sleeps between runs
- alternative: cron-like scheduler in the container

## 6) Database approach (what we store)

We want the database to answer questions like:

- “Have we already seen this observation/photo?”
- “Which photos still need classification?”
- “What labels did we assign, and with which model/prompt?”
- “If we re-run with a new prompt, can we keep the old results too?”

Suggested tables (high level):

- `observations`
  - `observation_id` (unique)
  - core metadata (dates, place, coordinates, etc.)
  - raw JSON blob from the API (so we don’t lose fields)

- `photos`
  - `photo_id` (unique)
  - `observation_id` (links back)
  - photo URLs + license info + attribution
  - optional: a local file path / checksum if we download/cache images

- `classifications`
  - links to `photo_id` (and `observation_id` for convenience)
  - the labels we produced (nectaring/mating/etc.)
  - **how it was produced** (model name/version, prompt version, timestamp)
  - raw model response (useful for debugging and future improvements)

Important rule:
- Don’t create duplicates. If the same `observation_id` or `photo_id` shows up again, update the existing row instead of inserting a second copy.

## 7) Tracking “how the AI result was produced” (important for later)

For each classification, store at least:
- when it ran
- which model was used (example: “OpenRouter + model X”)
- which prompt version was used (example: “prompt v3”)
- the output labels (structured JSON is fine)
- optionally, the full raw model output (for audits/debugging)

This lets us:
- re-run later with a better prompt/model
- compare versions
- publish a dataset with clear provenance (“these labels came from model X using prompt v3 on date Y”)

## 8) Licensing and publishing (practical approach)

Goal: publish/share results widely without creating avoidable licensing problems.

Two-mode approach:

- **Safe mode (recommended default when using cloud models)**
  Only send photos to the cloud model if the photo license clearly allows reuse (for example CC licenses that permit redistribution). Store everything else in the database, but skip cloud classification for restricted photos.

- **Everything mode (for private/internal analysis)**
  You can ingest everything, but you should assume you can’t republish the images, and you may decide not to send restricted images to third-party APIs.

What we can publish even in safe mode:
- observation IDs/links
- derived labels (nectaring/mating/etc.)
- metadata that’s allowed by the source terms
- attribution and license fields

## 9) Initial “v1” implementation choices (current preference)

- Language: **Python**
- Storage: **Postgres**
- Containerization: **Docker / Docker Compose**
- Vision model: **cloud (OpenRouter)** first, because it’s fastest to iterate
- Focus: get the end-to-end pipeline working on a small sample before scaling

## 10) Open questions (to decide soon)

- Geography: what counts as “North America” for filtering?
- Data quality: include research-grade only, or include needs-ID/casual?
- Update schedule: hourly vs daily sync?
- Cloud policy: in v1, do we classify only clearly licensed photos, or attempt more?
- Image caching: do we download and store images locally, or only store URLs?

## 11) Glossary (no-jargon)

- **Observation ID**: the unique number for an iNaturalist observation.
- **Photo ID**: the unique number for an iNaturalist photo.
- **Don’t duplicate work**: if we already saved/classified something, re-running the program shouldn’t redo it.
- **Prompt version**: a simple label like “v1 / v2 / v3” for the text instructions we give the AI.
- **Model version**: the specific AI model name we used (so results are reproducible later).
