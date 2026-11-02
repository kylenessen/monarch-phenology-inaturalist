"""Download annotated monarch observations and build a weekly H3 map."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import time
from threading import Lock

import h3
import httpx

from .benchmark_jev import annotation_stage, write_json

API = "https://api.inaturalist.org/v2/observations"
FIELDS = ",".join([
    "id", "observed_on", "location", "positional_accuracy", "geoprivacy", "obscured",
    "quality_grade", "annotations.controlled_attribute_id", "annotations.controlled_value_id",
    "annotations.vote_score", "annotations.votes.vote_flag",
])


def fetch_observations(output: Path) -> dict:
    """Cache each page and resume by descending ID, beyond the 10,000 result window."""
    output.mkdir(parents=True, exist_ok=True)
    pages = output / "pages"
    pages.mkdir(exist_ok=True)
    manifest_path = output / "source.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {
            "started_at": datetime.now(timezone.utc).isoformat(), "complete": False,
            "api": API, "place": "North America", "place_id": 97394,
            "params": {
                "taxon_id": 48662, "place_id": 97394, "term_id": 1, "term_value_id": "4,6",
                "photos": "true", "captive": "false", "quality_grade": "research,needs_id,casual",
                "per_page": 200, "order_by": "id", "order": "desc", "fields": FIELDS,
                "d2": date.today().isoformat(),
            },
        }
        write_json(manifest_path, manifest)
    if manifest["complete"]:
        return manifest
    cached = sorted(pages.glob("[0-9]*.json"))
    last_id = None
    for path in cached:
        page = json.loads(path.read_text())
        if page["results"]:
            last_id = min(row["id"] for row in page["results"])
    if "segments" not in manifest:
        # Existing sequential pages are above last_id. Divide the remainder into
        # disjoint ID intervals so slow responses can overlap without extra load.
        if last_id is None:
            with httpx.Client(timeout=90, follow_redirects=True) as head_client:
                response = head_client.get(API, params={**manifest["params"], "per_page": 1})
                response.raise_for_status()
                head = response.json()
            manifest["initial_total"] = head["total_results"]
            manifest["maximum_id"] = head["results"][0]["id"] if head["results"] else 0
            last_id = manifest["maximum_id"] + 1
            time.sleep(1.1)
        upper = last_id
        bounds = sorted({0, min(100_000_000, upper), min(200_000_000, upper), min(300_000_000, upper), upper})
        manifest["segments"] = [{"lower": a, "upper": b, "complete": False} for a, b in zip(bounds, bounds[1:])]
        write_json(manifest_path, manifest)
    rate_lock, manifest_lock = Lock(), Lock()
    last_request = [0.0]

    def fetch_segment(segment_index: int) -> None:
        segment = manifest["segments"][segment_index]
        if segment["complete"]:
            return
        segment_pages = sorted(pages.glob(f"segment-{segment_index}-*.json"))
        cursor = segment["upper"]
        for path in segment_pages:
            rows = json.loads(path.read_text())["results"]
            if rows:
                cursor = min(row["id"] for row in rows)
        index = len(segment_pages)
        while True:
            params = {**manifest["params"], "id_above": segment["lower"] - 1, "id_below": cursor}
            for attempt in range(8):
                with rate_lock:
                    time.sleep(max(0, 1.1 - (time.monotonic() - last_request[0])))
                    last_request[0] = time.monotonic()
                try:
                    response = client.get(API, params=params)
                    response.raise_for_status()
                    page = response.json()
                    break
                except (httpx.HTTPError, ValueError) as exc:
                    if attempt == 7:
                        raise
                    print(f"Retry {attempt + 1} after {type(exc).__name__}", flush=True)
                    time.sleep(min(60, 2 ** (attempt + 1)))
            rows = page["results"]
            ids = [row["id"] for row in rows]
            if len(set(ids)) != len(ids) or any(i >= cursor or i < segment["lower"] for i in ids):
                raise ValueError("Observation ID pagination did not advance cleanly")
            write_json(pages / f"segment-{segment_index}-{index:05d}.json", page)
            index += 1
            if rows:
                cursor = min(ids)
            with manifest_lock:
                manifest["downloaded"] += len(rows)
                manifest["pages"] += 1
                segment["complete"] = len(rows) < params["per_page"]
                write_json(manifest_path, manifest)
                if manifest["pages"] % 20 == 0:
                    print(f"Fetched {manifest['downloaded']:,} / approximately {manifest.get('initial_total', 0):,} observations", flush=True)
            if segment["complete"]:
                break

    # Reconcile cached pages after a possible interruption between page and
    # manifest writes. The source pages are authoritative for resume counts.
    all_pages = list(pages.glob("*.json"))
    manifest["downloaded"] = sum(len(json.loads(p.read_text())["results"]) for p in all_pages)
    manifest["pages"] = len(all_pages)
    with httpx.Client(timeout=90, follow_redirects=True, headers={"User-Agent": "monarch-phenology/0.1.0"}) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(fetch_segment, range(len(manifest["segments"]))))
    manifest.update(complete=True, completed_at=datetime.now(timezone.utc).isoformat())
    write_json(manifest_path, manifest)
    print(f"Finished downloading {manifest['downloaded']:,} observations", flush=True)
    return manifest


def seasonal_week(observed: date) -> int:
    """Jan 1 anchored seven-day bins on a leap-year calendar, stable across years."""
    return (date(2000, observed.month, observed.day) - date(2000, 1, 1)).days // 7


def normalize_observation(row: dict, cutoff: date) -> tuple[dict | None, str | None]:
    stage = annotation_stage(row)
    if stage not in {"larva", "pupa"}:
        return None, "conflicting_or_disputed_stage"
    if row.get("obscured") or row.get("geoprivacy") in {"obscured", "private"}:
        return None, "obscured_or_private"
    try:
        observed = date.fromisoformat(row["observed_on"])
    except (KeyError, TypeError, ValueError):
        return None, "missing_or_invalid_date"
    if observed > cutoff:
        return None, "future_date"
    try:
        lat, lon = map(float, row["location"].split(","))
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Invalid coordinates")
    except (KeyError, AttributeError, TypeError, ValueError):
        return None, "missing_or_invalid_location"
    accuracy = row.get("positional_accuracy")
    if accuracy is not None and (not isinstance(accuracy, (int, float)) or not math.isfinite(accuracy) or accuracy < 0):
        accuracy = None
    return {
        "id": row["id"], "date": observed.isoformat(), "year": observed.year,
        "week": (observed - date(observed.year, 1, 1)).days // 7,
        "seasonal_week": seasonal_week(observed), "stage": stage, "accuracy": accuracy,
        "quality": row.get("quality_grade"), "cells": [h3.latlng_to_cell(lat, lon, r) for r in (7, 8)],
    }, None


ASSETS = {
    "leaflet.js": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "leaflet.css": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "leaflet.LICENSE": "https://unpkg.com/leaflet@1.9.4/LICENSE",
}


def build_map(output: Path, preview: bool = False) -> Path:
    manifest = json.loads((output / "source.json").read_text())
    if not manifest.get("complete") and not preview:
        raise ValueError("Download is incomplete. Resume it before building the map.")
    seen = set()
    excluded = Counter()
    records = []
    cells = {}
    cutoff = date.fromisoformat(manifest["params"]["d2"])
    for page_path in sorted((output / "pages").glob("*.json")):
        for row in json.loads(page_path.read_text())["results"]:
            if row["id"] in seen:
                raise ValueError(f"Duplicate observation {row['id']} in source pages")
            seen.add(row["id"])
            record, reason = normalize_observation(row, cutoff)
            if record is None:
                excluded[reason] += 1
                continue
            for cell in record["cells"]:
                if cell not in cells:
                    cells[cell] = len(cells)
            records.append([
                record["id"], record["date"], 0 if record["stage"] == "larva" else 1,
                record["accuracy"], *[cells[c] for c in record["cells"]],
                record["week"], record["seasonal_week"], record["quality"],
            ])
    if not preview and len(seen) != manifest["downloaded"]:
        raise ValueError("Cached source page count does not match the manifest")
    if not records:
        raise ValueError("No eligible observations to map")
    stats = {
        "downloaded": len(seen), "mapped": len(records), "excluded": dict(excluded),
        "larvae": sum(r[2] == 0 for r in records), "pupae": sum(r[2] == 1 for r in records),
        "unknown_accuracy": sum(r[3] is None for r in records),
        "accuracy_over_1km": sum(r[3] is not None and r[3] > 1000 for r in records),
        "date_min": min(r[1] for r in records), "date_max": max(r[1] for r in records),
        "years": dict(sorted(Counter(r[1][:4] for r in records).items())),
    }
    geometries = [[cell, [[round(lat, 6), round(lon, 6)] for lat, lon in h3.cell_to_boundary(cell)]] for cell in cells]
    payload = {
        "source": {key: manifest.get(key) for key in ("started_at", "completed_at", "place", "place_id")},
        "preview": not manifest.get("complete"),
        "cutoff": cutoff.isoformat(), "stats": stats, "cells": geometries, "observations": records,
        "columns": ["id", "date", "stage_0_larva_1_pupa", "accuracy_m", "h3_7_index", "h3_8_index", "week", "seasonal_week", "quality_grade"],
    }
    write_json(output / "summary.json", stats)
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for name, url in ASSETS.items():
            target = assets / name
            if not target.exists():
                response = client.get(url)
                response.raise_for_status()
                target.write_bytes(response.content)
    template = Path(__file__).with_name("templates").joinpath("phenology_map.html").read_text()
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    target = output / "index.html"
    temporary = output / "index.html.tmp"
    temporary.write_text(template.replace("__MAP_DATA__", encoded))
    temporary.replace(target)
    print(json.dumps(stats, indent=2), flush=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/phenology-map"))
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--preview", action="store_true", help="Allow an explicitly marked preview of an incomplete download.")
    args = parser.parse_args()
    if not args.build_only:
        fetch_observations(args.output)
    if not args.fetch_only:
        print(build_map(args.output, preview=args.preview).resolve())


if __name__ == "__main__":
    main()
