# Jev life stage pilot

Run the pilot from the repository root with uv. It needs no database. Put `TYPESAFE_API_KEY` in the ignored local `.env` file, then run the following command.

```sh
uv run python -m monarch_phenology.benchmark_jev
```

The default selects 100 egg, 100 larva, 100 pupa and 100 adult photos. It uses research-grade, non-captive monarch observations in the California Floristic Province, place 62068. Each stage is a seeded shuffle of up to the newest 1,000 matching observation IDs. This is a convenience sample of recent submissions, not a random sample of all monarch observations. Set `--place-id 0` for worldwide sampling. Set `--pool-size` to change the candidate pool and `--seed` to change the shuffle. Use a new `--output` directory for different sampling settings or models.

The script rejects conflicting life stage annotations and annotations with disagreement votes. It selects the first usable photo from each observation. It excludes repeated observation IDs, photo IDs and identical prepared image hashes. It does not identify near duplicates or repeated observations of the same individual. Download failures are logged and replaced from the frozen candidate list before any model scoring. A shortfall stops the run rather than silently reducing the target sample.

Each photo is sent separately to `jev-1.14.0`. The request contains image pixels and fixed questions. It contains no annotation, observation notes, source URL, source filename, date or locality. Images are rotated upright, stripped of metadata, resized to at most 1568 pixels and padded to at least 280 pixels per dimension. Image handling follows the current [TypeSafe image API](https://docs.typesafe.ai/images).

One Choice question selects egg, larva, pupa, adult or unknown. Four independent Noul questions ask whether each stage is visible. These are all evaluated against the same image in one request. They do not depend on the Choice answer. Independent binary decisions use a fixed probability threshold of 0.5 by default. `--threshold` changes the reporting threshold without repeating successful model requests. Choice confidence is a separate vendor statistic and is not treated as a stage probability. See the [Choice](https://docs.typesafe.ai/primitives/choice) and [Noul](https://docs.typesafe.ai/primitives/noul) references.

To download without making model requests, use the following command.

```sh
uv run python -m monarch_phenology.benchmark_jev --prepare-only
```

To limit new model requests, use `--max-items 4`. Rerun without the limit to finish. Successful responses are checkpointed after each photo and reused. Failed responses are retried on a later run. Changes to model, questions or sample identity are rejected when a results file already exists. A four-photo smoke test in its own directory can be run as follows.

```sh
uv run python -m monarch_phenology.benchmark_jev --per-stage 1 --pool-size 10 --output runs/jev-smoke
```

The ignored `runs/jev-pilot` directory contains the frozen candidates, `manifest.json`, prepared images, `results.json`, `predictions.csv`, `review.csv` and `summary.json`. The manifest records image hashes, observation links, annotations, observer IDs, dates, licenses and attribution. Results retain the request questions, requested and resolved model versions, raw responses, token usage and elapsed time. The review CSV includes incorrect, unknown, failed and low-confidence Choice predictions, plus disagreements from the independent questions. Each row gives its review reasons. Independent stage probabilities are in both CSV exports.

The summary reports Choice accuracy, balanced accuracy, per-stage precision, recall and F1, a confusion matrix and approximate 95 percent Wilson intervals. Unknown predictions count as incorrect. API failures are reported separately from scored images, and pending photos are explicit. Per-stage recall is the fraction of that stage's successfully scored images classified correctly. Independent questions have separate true positive, false positive, false negative and true negative counts, plus precision, recall and F1. Precision reflects this artificially balanced sample and should not be assumed to transfer to the natural stage distribution.

iNaturalist annotations belong to observations, not individual photos. Some observations contain photos of different stages, and an annotation can be wrong. Research grade supports the species identification rather than guaranteeing the stage label. Review disagreements against the images before treating them as model errors. Wilson intervals also assume independent samples, which repeated observers or butterflies can violate. Performance on annotated observations does not establish performance on unannotated observations. A later unannotated run should retain uncertain outcomes and include manual review of a separate sample. This prototype does not write predictions back to iNaturalist.

Photo licenses and attribution are retained without filtering, consistent with this repository's build-mode policy. Cached photos and credentials stay out of Git. iNaturalist queries follow its [API guidance](https://www.inaturalist.org/pages/developers) with at least a second between metadata requests and bounded retries for transient failures.

Run the offline checks with `uv run pytest -q`. They cover disputed labels, image limits, request metadata isolation, malformed responses, metric denominators, transient retries and resume behavior.
