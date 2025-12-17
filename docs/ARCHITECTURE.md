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

### What we send to the AI (v1)

For each photo, the AI should see:
- the image
- the observation text / notes (if present)

A simple prompt pattern is:
- “Observer notes: …” followed by the user-provided description (or blank if none)

Practical safety note:
- Observation notes can be very long or contain sensitive info. In v1, we can **truncate** what we send to the model (for example, first 2,000 characters) and avoid sending obvious personal details (emails/phone numbers) if they appear. We can still store the full original text in the database.

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
  - **core metadata we care about explicitly**:
    - observation time/date (when it was observed)
    - latitude / longitude (and any accuracy/uncertainty fields)
    - place info (for filtering/summary)
    - observer info (username / user id)
    - notes/description text
    - iNaturalist “research grade” / quality flags
    - life stage annotation (when iNaturalist provides it)
  - raw JSON blob from the API (so we don’t lose fields)

- `photos`
  - `photo_id` (unique)
  - `observation_id` (links back)
  - photo URLs
  - license info + attribution (still store this, even if we don’t filter on it in v1)
  - optional: a local file path / checksum if we download/cache images

- `classifications`
  - links to `photo_id` (and `observation_id` for convenience)
  - the labels we produced (nectaring/mating/etc.)
  - **how it was produced** (model name/version, prompt version, timestamp)
  - raw model response (useful for debugging and future improvements)

Important rule:
- Don’t create duplicates. If the same `observation_id` or `photo_id` shows up again, update the existing row instead of inserting a second copy.

### Classification history (don’t overwrite)

When we improve the prompt or change models, we should **not overwrite** old results.

Simple rule:
- each time we classify a photo, we create a **new** row in `classifications` with:
  - `photo_id`
  - `model` (name/version/provider)
  - `prompt_version`
  - `created_at`

Then we can:
- query “latest classification per photo” for day-to-day analysis
- keep older results for comparison and reproducibility

### Duplicate observations (same butterfly, different people)

In v1, we will **not try to deduplicate** across different iNaturalist observations, even if they might be the same butterfly in the same place/time. We will classify what iNaturalist gives us.

Later, if we want, we can add analysis to group observations by location/time to study clustering or reduce repeated individuals.

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

Two-mode approach (important difference between “what we store” and “what we publish”):

- **Build mode (v1 default)**
  Don’t filter by photo license when ingesting or classifying (this keeps the dataset much larger). Still store license/attribution fields.

- **Publish mode (when sharing data)**
  When we publish, we can export a “safe to share” dataset. For example:
  - always okay: observation IDs/links + your derived labels + attribution fields
  - only sometimes okay: republishing the actual images (depends on the license)

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

## 9.1) Model choice, cost, and speed (v1 assumptions)

Current plan:
- Use a **free (or very cheap) OpenRouter vision model** (example: a free Gemma model, or similar) to keep costs near zero.
- Speed is not critical. It’s okay if building the dataset takes days/weeks/months.

Even if speed isn’t critical, we still want to be polite and stable:
- Add a **rate limit** (a configurable “max requests per minute”).
- Add **small concurrency** (a few workers at most) and tune it after we confirm the API limits.
- Add backoff/retries so temporary issues don’t break the service.

If model quality is not good enough:
- Improve the prompt and label definitions first.
- Try a different model (still via OpenRouter).
- Optionally move to a local model later (workstation) if we want more control.

## 9.2) Quality and validation (v1 approach)

We’ll keep validation lightweight at the start so we can get moving.

What we can use as “pretty good ground truth”:
- iNaturalist often has human-provided **life stage** annotations (egg/larva/pupa/adult). These are a strong reference for that one label category.

What’s harder:
- behaviors (nectaring/mating/clustering/ovipositing) usually won’t have clean ground truth.

Practical v1 plan:
- Start scraping + classifying and aim for the first ~**1,000 photos**.
- Review a small sample by hand to see how the model is doing.
- Later (separate effort), create a hand-labeled set for the trickier behaviors.

## 9.3) Failure handling (v1 approach)

Common things that will go wrong and how we’ll handle them:

- **Temporary API problems** (timeouts, 5xx errors, rate limiting):
  - retry a few times with increasing delays
  - if we keep getting blocked, slow down automatically

- **Model provider down**:
  - mark the classification attempt as “failed for now”
  - try again later (for example, after an hour)

- **Missing/deleted/corrupt photos**:
  - record that the photo couldn’t be downloaded
  - don’t keep retrying forever (avoid a stuck queue)

Important: store failures in the database so we know what happened and can re-try later.

## 9.4) Basic monitoring (how we’ll know it’s working)

We don’t need anything fancy to start. In v1, we should at least be able to answer:

- how many observations we ingested today
- how many photos we classified today
- how many photos are waiting to be classified (backlog)
- how many failures happened (and why)
- roughly how long it takes from “ingested” to “classified”

This can be simple logs + a few database queries.

## 10) Filtering specification (v1)

### Starting filters (recommended)

- **Species filter**: Monarch (Danaus plexippus)
- **Data quality**: start with **research-grade** only (humans verified)
- **Geography**: start with the **California Floristic Province** (or a practical proxy like California) and expand later
- **Captive/cultivated**: default to excluding captive if the source provides that flag
- **Update schedule**: daily is fine to start; can move to hourly later
- **Cloud policy**: v1 “build mode” (don’t filter by photo license for classification)
- **Image caching**: start by storing URLs (no large local image cache), add caching later if needed

### Concrete iNaturalist example

This URL shows the shape of the query we want to replicate in the API:

`https://www.inaturalist.org/observations?place_id=62068&quality_grade=research&subview=map&taxon_id=48662`

Notes:
- `taxon_id=48662` is Monarch (Danaus plexippus).
- `place_id=62068` is used as the California Floristic Province filter (we’ll confirm it’s the exact place we want).

### Still-open choices

- How exactly we define “California Floristic Province” in the source filters (place ID vs bounding box/polygon).
- Whether we want to include needs-ID/casual later for completeness.
 - How many times we retry a failing photo before we “park” it (example: 5–10 attempts, then stop retrying until we manually reset it).

## 11) Glossary (no-jargon)

- **Observation ID**: the unique number for an iNaturalist observation.
- **Photo ID**: the unique number for an iNaturalist photo.
- **Don’t duplicate work**: if we already saved/classified something, re-running the program shouldn’t redo it.
- **Prompt version**: a simple label like “v1 / v2 / v3” for the text instructions we give the AI.
- **Model version**: the specific AI model name we used (so results are reproducible later).
