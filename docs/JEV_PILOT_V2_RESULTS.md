# Expanded Jev phenology pilot

Completed November 2, 2026. The second pilot scored 400 new photos, with 100 observation annotations each for egg, larva, pupa and adult. All requests succeeded. No observation ID, photo ID or prepared-image SHA-256 overlaps the first pilot or its smoke test. The sampling region remains the California Floristic Province. Research-grade, non-captive observations were drawn from up to 1,000 recent observation IDs per stage using seed 43.

## Life stage agreement

The expanded prompt matched the iNaturalist life stage on 379 of 400 images, or 94.75 percent. Its approximate 95 percent Wilson interval is 92.11 to 96.54 percent. Unknown predictions remain in the denominator. This run uses different photos and a different prompt from the first pilot, so the change from 96.75 percent does not isolate the effect of the prompt.

| Reference stage | Matched out of 100 |
| --- | --- |
| Egg | 86 |
| Larva | 99 |
| Pupa | 96 |
| Adult | 98 |

## Larval development

For the 100 observations annotated as larvae, the coarse predictions were as follows. These are size and development groups, not exact instar assignments. No independent instar reference labels are available.

| Group | Photos |
| --- | --- |
| Small / early | 6 |
| Large / late | 79 |
| Intermediate or uncertain | 15 |

Across all 400 photos the model returned 19 small/early, 90 large/late, 16 intermediate/uncertain and 275 not-applicable answers. These totals differ from the annotated-larva group because the questions are independent and some photos contain additional subjects or contradictory answers. Review them before using them in a phenology series. The prompt asks for credible relative scale and visible developmental cues. A close crop or a large number of image pixels does not establish a large caterpillar.

## Additional tags

Each tag is an independent yes/no probability. A probability of at least 0.7 is positive, at most 0.3 is negative, and the interval between is uncertain. Labels can coexist. These counts describe model output and are not accuracy, precision or recall measurements.

| Tag | Positive | Uncertain | Negative |
| --- | --- | --- | --- |
| Empty chrysalis | 9 | 27 | 364 |
| No obvious monarch | 11 | 69 | 320 |
| Dead remains | 1 | 8 | 391 |
| Clustering adults | 4 | 1 | 395 |
| Nectaring adults | 6 | 28 | 366 |

Empty chrysalis means a visibly empty emerged casing, including a casing beside an adult. It does not imply mortality. Dead remains means recognizable dead bodies or body parts. The no-obvious-monarch label requires no identifiable organism, empty chrysalis or recognizable dead remains in the supplied image. Clustering is defined as a resting aggregation of at least three adults. Nectaring requires visible feeding evidence rather than simply being near a flower. Clustering and nectaring preserve adult life stage.

The separate evidence Choice returned 372 monarch-visible, 9 empty-chrysalis-only, 8 no-obvious-monarch, 3 dead-remnants-only and 8 uncertain answers. These are separate questions, so their counts need not equal the independent tag totals.

## Using the output for phenology

The raw `prediction` remains available for auditing and annotation agreement. `phenology_stage` is a provisional derived field. It retains a known stage only when the evidence Choice says an identifiable organism is visible. Empty-chrysalis-only, dead-remnants-only, no-obvious-monarch and uncertain-evidence results receive no provisional living stage. This does not prove that retained organisms are alive. It only separates obvious remains or absent evidence from the provisional series.

`phenology_larval_development` is populated only for provisional larvae with a small/early or large/late prediction. Intermediate and uncertain larvae retain their larval life stage without a finer developmental assignment. Nine images had an empty-chrysalis-only or no-obvious-monarch answer alongside a known raw life stage. These contradictions are flagged and do not enter the provisional living-stage series.

The review CSV flags 249 images. The HTML reviewer includes all 400 so reviewers can inspect negative predictions as well as positives and disagreements. Review all new-label positives and uncertain cases, and an independent sample of negatives, before measuring the new categories or using their counts for ecological inference. Only one dead-remains positive and four clustering positives were found, so this batch cannot establish performance on those categories.

## Cost and artifacts

The run used 1,652,249 input tokens, including the four smoke-test requests that were resumed rather than repeated. At the published rate of $0.042 per million input tokens, the estimated model charge is $0.0694, about seven cents. This is a usage-based estimate rather than a verified bill. [TypeSafe pricing](https://docs.typesafe.ai/models).

The requested and resolved model was `jev-1.14.0`. The prompt version is `v2`. The run fingerprint is `4e8f691249409a41819c7683b17facc2bdf26a8dbd34f7e56433fd6f42b9152b`.

Local artifacts are in `runs/jev-pilot-v2`. They include the frozen candidates, manifest, cached images, raw responses, predictions CSV, review CSV and summary JSON. The HTML review is served at `http://127.0.0.1:8767/review.html`. Its JSON and CSV exports retain manual life stage, five extra tags, larval development, notes and review timestamps separately from model output. The existing first-run reviewer remains available on port 8766.

All 16 automated tests pass. The tests cover exclusion of prior observations, photo IDs and identical images, preservation of adult stage under behavior tags, separation of empty casings from dead remains, validation of expanded answers and prevention of empty-case-only images entering the provisional pupa series. Browser checks verified filters, additional review controls, saving, reload persistence and CSV export. Temporary test reviews were cleared.
