# Jev monarch pilot results

Completed November 2, 2026. Jev 1.14.0 matched the existing iNaturalist life stage annotation on 387 of 400 photos, or 96.75 percent. The approximate 95 percent Wilson interval is 94.52 to 98.09 percent. All 400 requests succeeded. These are annotation agreement results, not accuracy against manually verified photo labels.

## Main life stage classification

Each photo was evaluated separately. The fixed Choice question allowed egg, larva, pupa, adult or unknown. No annotations or observation metadata were sent to the model.

| Reference stage | Matched out of 100 | Precision | Recall 95 percent interval |
| --- | --- | --- | --- |
| Egg | 94 | 100.0% | 87.5% to 97.2% |
| Larva | 99 | 96.1% | 94.6% to 99.8% |
| Pupa | 96 | 97.0% | 90.2% to 98.4% |
| Adult | 98 | 100.0% | 93.0% to 99.4% |

Six predictions were unknown. They remain in the denominator as disagreements. The remaining seven disagreements selected a different life stage.

## Independent stage presence questions

Four separate yes/no questions were evaluated against each image in the same request. The probability threshold was fixed at 0.5. Each stage had 100 reference positives and 300 reference negatives. The counts below assume the observation annotation fully describes the selected photo, which is not always true.

| Stage | True positives | False positives | False negatives | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| Egg | 91 | 2 | 9 | 97.8% | 91.0% | 94.3% |
| Larva | 100 | 17 | 0 | 85.5% | 100.0% | 92.2% |
| Pupa | 97 | 24 | 3 | 80.2% | 97.0% | 87.8% |
| Adult | 97 | 1 | 3 | 99.0% | 97.0% | 98.0% |

The independent questions overcalled larvae and pupae relative to the reference labels. Their precision was lower than the main Choice classifier. These probabilities should not be treated as interchangeable with the Choice distribution. Thresholds were not tuned on this pilot.

## Sampling and reproducibility

The sample contains one prepared photo from each of 400 distinct observations by 261 observers. The source filter was monarch, research grade, non-captive, California Floristic Province. Each stage used a seeded shuffle of the newest 1,000 matching observation IDs. The seed was 42. Conflicting or disputed annotations were excluded. There were no download failures. This is a regional convenience sample, not a random sample of all monarch photographs.

The first usable photo was selected from each observation. Images were downloaded at the iNaturalist large size, rotated upright and normalized to the documented Jev image limits. Exact prepared-image duplicates were excluded. Near duplicates and repeated butterflies may remain. Repeated observers and individuals also limit the independence assumption behind the confidence intervals.

All responses resolved to `jev-1.14.0`. The run used 1,104,239 input tokens. The four-photo smoke test is separate and is not included in these totals. The prompt, raw responses, image hashes and source annotations are retained in the local run directory. A second invocation reused all 400 successful responses.

The run fingerprint is `270bf966303711d73af0585035313a62059dce2c83ffcd822180d19b7b459c03`. The local manifest SHA-256 is `c7271c74a0e8b6ec23c9f52362bae1fd37104877c944925ecbd4b59a793588c3`.

## Review before expansion

The review CSV contains 54 photos flagged for a Choice disagreement, Choice confidence below 0.7 or an independent-question disagreement. These categories overlap. No labels were changed after reviewing the output.

Two spot-checked disagreements illustrate why the reference labels need review. Observation [345010378](https://www.inaturalist.org/observations/345010378) is annotated pupa, but the selected photo shows a hanging striped caterpillar. Observation [334238909](https://www.inaturalist.org/observations/334238909) is also annotated pupa, but the selected photo shows caterpillars on a plant. Jev chose larva for both. These visual checks are not a full adjudication of the dataset.

Two egg-to-unknown disagreements also show whole plants with no readily discernible egg at the prepared resolution. The selected photos are from observations [177011235](https://www.inaturalist.org/observations/177011235) and [88649181](https://www.inaturalist.org/observations/88649181). A photo-level review should determine whether the target is present and visible before calling these model errors.

Before a larger unannotated run, manually adjudicate the review set and a random sample of agreements. Keep any revised labels separate from the original annotations. Retain unknown outcomes and plan a separate manual audit of unannotated observations, since stage frequencies and image quality can differ. The pilot does not establish accuracy or precision on that population.

## Local artifacts

The local `runs/jev-pilot` directory contains `manifest.json`, `results.json`, `summary.json`, `predictions.csv`, `review.csv`, frozen candidates and cached images. Credentials, images and run artifacts are ignored by Git. The script and this report are committed. See [the benchmark instructions](JEV_BENCHMARK.md) for commands and metric definitions.
