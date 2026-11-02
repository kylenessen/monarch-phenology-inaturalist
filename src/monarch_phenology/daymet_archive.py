"""Plan and resume an all-variable Daymet archive without AET requests."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import date, timedelta
import hashlib
import io
import json
import math
from pathlib import Path

import httpx

from .benchmark_jev import write_json
from .phenology_map import normalize_observation
from .weather_pilot import DAYMET, Fetcher

VARIABLES = {
    "tmin": "tmin (deg c)", "tmax": "tmax (deg c)",
    "prcp": "prcp (mm/day)", "vp": "vp (Pa)",
    "srad": "srad (W/m^2)", "swe": "swe (kg/m^2)", "dayl": "dayl (s)",
}


def needed_years(observed: date, lookback: int) -> list[int]:
    return list(range((observed - timedelta(days=lookback)).year, observed.year + 1))


def parse_daily(body: str) -> dict:
    lines = body.splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("year,yday,"))
    reader = csv.DictReader(io.StringIO("\n".join(lines[header:])))
    if not set(VARIABLES.values()).issubset(reader.fieldnames or []):
        raise ValueError("Response does not contain all seven Daymet variables")
    daily = []
    seen = set()
    for row in reader:
        year, yday = int(row["year"]), int(row["yday"])
        if not 1 <= yday <= 365:
            raise ValueError("Unexpected Daymet day of year")
        day = (date(year, 1, 1) + timedelta(days=yday - 1)).isoformat()
        if day in seen:
            raise ValueError("Duplicate daily record")
        seen.add(day)
        values = {key: float(row[column]) for key, column in VARIABLES.items()}
        daily.append({"date": day, **{key: value if math.isfinite(value) and value != -9999 else None for key, value in values.items()}})
    return {"metadata": lines[:header], "columns_with_units": VARIABLES, "daily": daily}


def make_plan(source: Path, output: Path, last_year: int = 2025, lookback: int = 60, strict_accuracy: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    source_bytes = (source / "source.json").read_bytes()
    meta = json.loads(source_bytes)
    if not meta["complete"]:
        raise ValueError("Observation source must be complete")
    if last_year < 1980 or lookback < 1:
        raise ValueError("Invalid year or lookback")
    config = {"source": str(source.resolve()), "source_sha256": hashlib.sha256(source_bytes).hexdigest(), "first_year": 1980, "last_year": last_year, "lookback_days": lookback, "strict_accuracy": strict_accuracy, "variables": list(VARIABLES), "version": 1}
    path = output / "plan.json"
    if path.exists():
        plan = json.loads(path.read_text())
        if plan["config"] != config:
            raise ValueError("Settings changed. Use a new output directory.")
        return plan
    points, observations, excluded = {}, [], Counter()
    seen = set()
    for page in sorted((source / "pages").glob("*.json")):
        for raw in json.loads(page.read_text())["results"]:
            row, reason = normalize_observation(raw, date.fromisoformat(meta["params"]["d2"]))
            if row is None:
                excluded[reason] += 1
                continue
            if row["id"] in seen:
                raise ValueError("Duplicate source observation")
            seen.add(row["id"])
            observed = date.fromisoformat(row["date"])
            if observed.year > last_year or (observed - timedelta(days=lookback)).year < 1980:
                excluded["outside_available_years_or_lookback"] += 1
                continue
            if row["accuracy"] is not None and row["accuracy"] > 1000:
                excluded["accuracy_over_1km"] += 1
                continue
            if strict_accuracy and row["accuracy"] is None:
                excluded["accuracy_unknown"] += 1
                continue
            # Exact coordinates only. No rounding or approximate grid snapping.
            key = hashlib.sha256(json.dumps([row["lat"], row["lon"]]).encode()).hexdigest()[:24]
            point = points.setdefault(key, {"key": key, "lat": row["lat"], "lon": row["lon"], "years": set(), "observation_count": 0})
            point["years"].update(needed_years(observed, lookback))
            point["observation_count"] += 1
            observations.append({**row, "point_key": key})
    for point in points.values():
        point["years"] = sorted(point["years"])
    plan = {"config": config, "summary": {"observations": len(observations), "planned_requests": len(points), "point_years": sum(len(p["years"]) for p in points.values()), "unknown_accuracy_included": sum(r["accuracy"] is None for r in observations), "exclusions": dict(excluded)}, "points": sorted(points.values(), key=lambda p: p["key"]), "observations": observations}
    write_json(path, plan)
    return plan


def fetch_point(point: dict, output: Path, fetcher: Fetcher) -> dict:
    (output / "points").mkdir(parents=True, exist_ok=True)
    params = {"lat": point["lat"], "lon": point["lon"], "vars": ",".join(VARIABLES), "years": ",".join(map(str, point["years"]))}
    result = {**point, "request": {"url": DAYMET, "params": params}}
    try:
        body = fetcher.get("daymet", DAYMET, params)
        result.update(parse_daily(body))
        expected = {date(year, 1, 1) + timedelta(days=i) for year in point["years"] for i in range(365)}
        actual = {date.fromisoformat(row["date"]) for row in result["daily"]}
        if actual != expected:
            raise ValueError("Daymet did not return exactly the requested full years")
        result["status"] = "ok"
    except (httpx.HTTPError, ValueError, KeyError, StopIteration) as exc:
        result.update(status="request_error", error=str(exc)[:400])
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 400 and "Tile was not found" in exc.response.text:
            result.update(status="outside_daymet_coverage", error="No Daymet tile contains this coordinate")
    write_json(output / "points" / f"{point['key']}.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("runs/phenology-map"))
    parser.add_argument("--output", type=Path, default=Path("runs/daymet-full"))
    parser.add_argument("--last-year", type=int, default=2025)
    parser.add_argument("--lookback-days", type=int, default=60)
    parser.add_argument("--strict-accuracy", action="store_true")
    parser.add_argument("--fetch", action="store_true", help="Fetch planned requests. Otherwise only create the offline plan.")
    parser.add_argument("--limit", type=int, help="Maximum pending point requests in this invocation")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retry-errors", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or (args.limit is not None and args.limit < 1):
        parser.error("Workers and limit must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    plan = make_plan(args.source, args.output, args.last_year, args.lookback_days, args.strict_accuracy)
    print(json.dumps(plan["summary"], indent=2), flush=True)
    if not args.fetch:
        return
    pending = []
    for point in plan["points"]:
        path = args.output / "points" / f"{point['key']}.json"
        if not path.exists() or (args.retry_errors and json.loads(path.read_text())["status"] == "request_error"):
            pending.append(point)
    fetcher = Fetcher(args.output)
    counts = Counter()
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(fetch_point, p, args.output, fetcher) for p in pending[:args.limit]]
            for i, future in enumerate(as_completed(futures), 1):
                counts[future.result()["status"]] += 1
                if i % 100 == 0:
                    print(f"Completed {i}/{len(futures)} {dict(counts)}", flush=True)
    finally:
        fetcher.client.close()
    print(json.dumps({"completed_this_invocation": dict(counts)}, indent=2))


if __name__ == "__main__":
    main()
