"""A resumable, database-free benchmark against iNaturalist life stage annotations."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import time

from dotenv import load_dotenv
import httpx

from .jev_client import QUESTIONS, STAGES, classify_image, prepare_image, request_with_retry


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def annotation_stage(observation: dict) -> str | None:
    annotations = [a for a in observation.get("annotations", []) if a["controlled_attribute_id"] == 1]
    # Reject conflicting or disputed labels, even if another annotation has a positive score.
    if any(
        (a.get("vote_score") or 0) < 0
        or any(v.get("vote_flag") is False for v in a.get("votes", []))
        for a in annotations
    ):
        return None
    values = {a["controlled_value_id"] for a in annotations}
    return next((stage for stage, value in STAGES.items() if values == {value}), None)


def collect_candidates(client: httpx.Client, stage: str, args: argparse.Namespace) -> list[dict]:
    candidates = []
    seen = set()
    last_id = None
    while len(seen) < args.pool_size:
        params = {
            "taxon_id": 48662, "quality_grade": "research", "photos": "true",
            "captive": "false", "term_id": 1, "term_value_id": STAGES[stage],
            "per_page": min(200, args.pool_size - len(seen)), "order_by": "id", "order": "desc",
        }
        if args.place_id:
            params["place_id"] = args.place_id
        if last_id is not None:
            params["id_below"] = last_id
        response = request_with_retry(client, "GET", "https://api.inaturalist.org/v1/observations", params=params)
        observations = response.json()["results"]
        time.sleep(1.05)
        if not observations:
            break
        new_ids = {o["id"] for o in observations} - seen
        if not new_ids:
            raise ValueError("iNaturalist pagination did not advance")
        for observation in observations:
            if observation["id"] in seen:
                continue
            seen.add(observation["id"])
            if annotation_stage(observation) != stage:
                continue
            # Use the first displayed usable photo. Never choose a photo using model output.
            photo = next((p for p in observation.get("photos", []) if p.get("url") and not p.get("hidden")), None)
            if not photo:
                continue
            url = photo["url"].replace("/square.", "/large.")
            if url == photo["url"] and "/square" in url:
                continue
            candidates.append({
                "observation_id": observation["id"], "photo_id": photo["id"],
                "expected_stage": stage, "photo_url": url,
                "observation_url": f"https://www.inaturalist.org/observations/{observation['id']}",
                "observed_on": observation.get("observed_on"),
                "observer_id": observation.get("user", {}).get("id"),
                "license_code": photo.get("license_code"), "attribution": photo.get("attribution"),
                "life_stage_annotations": [a for a in observation["annotations"] if a["controlled_attribute_id"] == 1],
            })
        last_id = min(o["id"] for o in observations)
        if len(observations) < params["per_page"]:
            break
    random.Random(f"{args.seed}-{stage}").shuffle(candidates)
    print(f"{stage} has {len(candidates)} eligible candidates from {len(seen)} observations", flush=True)
    return candidates


def prepare_dataset(args: argparse.Namespace) -> dict:
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / "images").mkdir(exist_ok=True)
    config = {"per_stage": args.per_stage, "pool_size": args.pool_size, "seed": args.seed, "place_id": args.place_id}
    path = output / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {
        "config": config, "created_at": datetime.now(timezone.utc).isoformat(),
        "sampling": "Seeded shuffle of the newest observation IDs per stage. First usable photo per observation.",
        "samples": [], "download_failures": [],
    }
    if manifest["config"] != config:
        raise ValueError("Sampling settings changed. Use a different output directory.")
    samples = manifest["samples"]
    seen_photos = {s["photo_id"] for s in samples}
    seen_observations = {s["observation_id"] for s in samples}
    seen_hashes = {s["sha256"] for s in samples}
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "monarch-phenology/0.1.0"}) as client:
        for stage in STAGES:
            count = sum(s["expected_stage"] == stage for s in samples)
            if count >= args.per_stage:
                continue
            candidate_path = output / f"candidates-{stage}.json"
            if candidate_path.exists():
                candidates = json.loads(candidate_path.read_text())
            else:
                candidates = collect_candidates(client, stage, args)
                write_json(candidate_path, candidates)
                write_json(path, manifest)
            for candidate in candidates:
                if count >= args.per_stage:
                    break
                if candidate["photo_id"] in seen_photos or candidate["observation_id"] in seen_observations:
                    continue
                try:
                    raw = request_with_retry(client, "GET", candidate["photo_url"]).content
                    image = prepare_image(raw)
                except (httpx.HTTPError, OSError, ValueError) as exc:
                    manifest["download_failures"].append({"photo_id": candidate["photo_id"], "error": str(exc)})
                    write_json(path, manifest)
                    continue
                image_hash = digest(image)
                if image_hash in seen_hashes:
                    continue
                relative_path = f"images/{candidate['photo_id']}.jpg"
                (output / relative_path).write_bytes(image)
                samples.append({**candidate, "image_path": relative_path, "sha256": image_hash})
                seen_photos.add(candidate["photo_id"])
                seen_observations.add(candidate["observation_id"])
                seen_hashes.add(image_hash)
                count += 1
                write_json(path, manifest)
                if count % 25 == 0 or count == args.per_stage:
                    print(f"Downloaded {stage} {count}/{args.per_stage}", flush=True)
            if count < args.per_stage:
                raise ValueError(f"Only {count}/{args.per_stage} usable {stage} photos. Try a new output directory with a larger pool or --place-id 0.")
    for sample in samples:
        if digest((output / sample["image_path"]).read_bytes()) != sample["sha256"]:
            raise ValueError(f"Cached image changed for photo {sample['photo_id']}")
    return manifest


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def wilson(successes: int, total: int) -> list[float] | None:
    if not total:
        return None
    p, z = successes / total, 1.96
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * ((p * (1 - p) + z * z / (4 * total)) / total) ** 0.5 / (1 + z * z / total)
    return [max(0, center - half), min(1, center + half)]


def evaluate(samples: list[dict], results: dict, threshold: float) -> dict:
    successful = [(s, results[str(s["photo_id"])]) for s in samples if results.get(str(s["photo_id"]), {}).get("status") == "ok"]
    confusion = {stage: dict.fromkeys([*STAGES, "unknown"], 0) for stage in STAGES}
    for sample, result in successful:
        confusion[sample["expected_stage"]][result["prediction"]] += 1
    per_stage = {}
    for stage in STAGES:
        support = sum(confusion[stage].values())
        tp = confusion[stage][stage]
        predicted = sum(row[stage] for row in confusion.values())
        binary_tp = sum(s["expected_stage"] == stage and r["stage_probabilities"][stage] >= threshold for s, r in successful)
        binary_fp = sum(s["expected_stage"] != stage and r["stage_probabilities"][stage] >= threshold for s, r in successful)
        binary_fn = support - binary_tp
        per_stage[stage] = {
            "selected": sum(s["expected_stage"] == stage for s in samples),
            "scored": support, "correct": tp,
            "recall": ratio(tp, support), "recall_95ci": wilson(tp, support),
            "precision": ratio(tp, predicted), "f1": ratio(2 * tp, support + predicted),
            "independent": {
                "tp": binary_tp, "fp": binary_fp, "fn": binary_fn,
                "tn": len(successful) - binary_tp - binary_fp - binary_fn,
                "precision": ratio(binary_tp, binary_tp + binary_fp),
                "recall": ratio(binary_tp, support),
                "f1": ratio(2 * binary_tp, 2 * binary_tp + binary_fp + binary_fn),
            },
        }
    correct = sum(confusion[s][s] for s in STAGES)
    recalls = [v["recall"] for v in per_stage.values() if v["recall"] is not None]
    return {
        "selected": len(samples), "scored": len(successful),
        "failed": sum(r.get("status") == "error" for r in results.values()),
        "pending": len(samples) - len(successful) - sum(r.get("status") == "error" for r in results.values()),
        "accuracy": ratio(correct, len(successful)), "accuracy_95ci": wilson(correct, len(successful)),
        "balanced_accuracy": sum(recalls) / len(STAGES) if len(recalls) == len(STAGES) else None,
        "independent_threshold": threshold, "per_stage": per_stage, "confusion_matrix": confusion,
        "input_tokens": sum(r.get("usage", {}).get("input_tokens", 0) for _, r in successful),
    }


def save_reports(output: Path, manifest: dict, results: dict, threshold: float) -> dict:
    summary = evaluate(manifest["samples"], results, threshold)
    write_json(output / "summary.json", summary)
    fields = ["observation_id", "photo_id", "expected_stage", "prediction", "status", "confidence", "observation_url", "image_path", "error", "review_reasons"]
    fields += [f"p_{s}" for s in STAGES]
    rows = []
    for sample in manifest["samples"]:
        result = results.get(str(sample["photo_id"]), {"status": "pending"})
        row = {key: {**sample, **result}.get(key) for key in fields}
        row.update({f"p_{s}": result.get("stage_probabilities", {}).get(s) for s in STAGES})
        reasons = []
        if result["status"] != "ok":
            reasons.append(result["status"])
        else:
            if result["prediction"] != sample["expected_stage"]:
                reasons.append("choice_disagrees")
            if result["confidence"] < 0.7:
                reasons.append("low_choice_confidence")
            detected = {s for s in STAGES if result["stage_probabilities"][s] >= threshold}
            if detected != {sample["expected_stage"]}:
                reasons.append("independent_questions_disagree")
        row["review_reasons"] = ", ".join(reasons)
        rows.append(row)
    for name, selected in [("predictions.csv", rows), ("review.csv", [r for r in rows if r["review_reasons"]])]:
        with (output / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(selected)
    return summary


def run_benchmark(args: argparse.Namespace, manifest: dict) -> dict:
    api_key = os.getenv("TYPESAFE_API_KEY")
    if not api_key:
        raise ValueError("Photos are ready. Set TYPESAFE_API_KEY in .env and rerun to score them.")
    path = args.output / "results.json"
    identity = {
        "model": args.model, "questions": QUESTIONS,
        "samples": [[s["photo_id"], s["sha256"], s["expected_stage"]] for s in manifest["samples"]],
    }
    fingerprint = digest(json.dumps(identity, sort_keys=True).encode())
    run = json.loads(path.read_text()) if path.exists() else {"fingerprint": fingerprint, "model": args.model, "questions": QUESTIONS, "results": {}}
    if run["fingerprint"] != fingerprint:
        raise ValueError("Model, prompt or samples changed. Use a new output directory.")
    results = run["results"]
    samples = manifest["samples"].copy()
    random.Random(args.seed).shuffle(samples)
    called = 0
    headers = {"Authorization": f"Bearer {api_key}", "TypeSafe-Danger-Zone-Images": "true"}
    with httpx.Client(timeout=90, headers=headers) as client:
        for sample in samples:
            key = str(sample["photo_id"])
            if results.get(key, {}).get("status") == "ok":
                continue
            if args.max_items and called >= args.max_items:
                break
            start = time.monotonic()
            try:
                result = classify_image(client, (args.output / sample["image_path"]).read_bytes(), args.model)
                results[key] = {
                    "status": "ok", **result, "seconds": time.monotonic() - start,
                    "classified_at": datetime.now(timezone.utc).isoformat(),
                }
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                results[key] = {"status": "error", "error": str(exc)}
                write_json(path, run)
                save_reports(args.output, manifest, results, args.threshold)
                # Avoid spending a whole run on a bad key or incompatible API contract.
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (400, 401, 402, 403, 404, 422):
                    raise
            called += 1
            write_json(path, run)
            if called % 25 == 0:
                print(f"Scored {sum(r['status'] == 'ok' for r in results.values())}/{len(samples)}", flush=True)
    return save_reports(args.output, manifest, results, args.threshold)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-stage", type=int, default=100)
    parser.add_argument("--pool-size", type=int, default=1000, help="Newest observations to consider per stage.")
    parser.add_argument("--place-id", type=int, default=62068, help="California Floristic Province. Use 0 for worldwide.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default="jev-1.14.0")
    parser.add_argument("--output", type=Path, default=Path("runs/jev-pilot"))
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--max-items", type=int, default=0, help="Cap new model calls. Zero scores all remaining photos.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Independent yes/no decision threshold.")
    args = parser.parse_args()
    if args.per_stage < 1 or args.pool_size < args.per_stage or args.max_items < 0 or not 0 < args.threshold < 1:
        parser.error("Require 1 <= per-stage <= pool-size, max-items >= 0 and 0 < threshold < 1")
    try:
        manifest = prepare_dataset(args)
        print(f"Prepared {len(manifest['samples'])} photos in {args.output}", flush=True)
        if not args.prepare_only:
            summary = run_benchmark(args, manifest)
            print(json.dumps(summary, indent=2))
            if summary["failed"]:
                raise SystemExit(1)
    except (ValueError, OSError, httpx.HTTPError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
