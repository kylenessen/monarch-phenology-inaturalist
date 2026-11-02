"""Reproducible antecedent temperature and satellite AET pilot."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import random
from threading import Lock
import time

import httpx
from pyproj import Transformer
from shapely.geometry import Point, box, shape
from shapely.ops import transform, unary_union

from .benchmark_jev import write_json
from .phenology_map import normalize_observation

DAYMET = "https://daymet.ornl.gov/single-pixel/api/data"
MODIS = "https://modis.ornl.gov/rst/api/v1/MOD16A2GF/subset"
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
REGIONS = ["California coast", "Eastern North America", "Other western North America"]


class Regions:
    def __init__(self, output: Path):
        folder = output / "geography"
        folder.mkdir(parents=True, exist_ok=True)
        data = {}
        for name in ("ne_10m_admin_1_states_provinces", "ne_10m_coastline"):
            path = folder / f"{name}.geojson"
            if not path.exists():
                response = httpx.get(f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/{name}.geojson", timeout=120)
                response.raise_for_status()
                path.write_bytes(response.content)
            data[name] = json.loads(path.read_text())
        ca = next(f for f in data["ne_10m_admin_1_states_provinces"]["features"] if f["properties"].get("name") == "California" and f["properties"].get("iso_a2") == "US")
        self.california = shape(ca["geometry"])
        extent = box(-126, 31, -115, 43)
        coast = unary_union([shape(f["geometry"]).intersection(extent) for f in data["ne_10m_coastline"]["features"] if shape(f["geometry"]).intersects(extent)])
        self.project = Transformer.from_crs("EPSG:4326", "EPSG:3310", always_xy=True).transform
        self.coast = transform(self.project, coast)

    def classify(self, lat: float, lon: float) -> str:
        if lon >= -100:
            return REGIONS[1]
        point = Point(lon, lat)
        if self.california.covers(point) and transform(self.project, point).distance(self.coast) <= 50_000:
            return REGIONS[0]
        return REGIONS[2]


def allocate_sample(groups: dict, size: int, minimum: int = 8) -> dict:
    quotas = {key: min(minimum, len(rows)) for key, rows in groups.items()}
    if sum(quotas.values()) > size:
        raise ValueError("Sample size is too small to cover every stratum")
    size = min(size, sum(map(len, groups.values())))
    while sum(quotas.values()) < size:
        remaining = size - sum(quotas.values())
        capacities = {key: len(groups[key]) - quotas[key] for key in groups if quotas[key] < len(groups[key])}
        total = sum(capacities.values())
        shares = {key: remaining * capacity / total for key, capacity in capacities.items()}
        for key, share in shares.items():
            quotas[key] += min(capacities[key], math.floor(share))
        left = size - sum(quotas.values())
        for key in sorted(shares, key=lambda key: (-(shares[key] % 1), key))[:left]:
            quotas[key] += 1
    return quotas


def sample_observations(source: Path, output: Path, size: int, seed: int, all_observations: bool = False) -> dict:
    path = output / "manifest.json"
    source_meta = json.loads((source / "source.json").read_text())
    if not source_meta["complete"]:
        raise ValueError("The observation download must be complete")
    config = {"source": str(source.resolve()), "source_sha256": hashlib.sha256((source / "source.json").read_bytes()).hexdigest(), "size": size, "seed": seed, "all": all_observations, "years": [2001, 2025], "max_accuracy_m": 1000, "version": 1}
    if path.exists():
        manifest = json.loads(path.read_text())
        if manifest["config"] != config:
            raise ValueError("Sampling settings changed. Use a new output directory.")
        return manifest
    geography = Regions(output)
    groups = defaultdict(list)
    excluded = Counter()
    seen = set()
    for page in sorted((source / "pages").glob("*.json")):
        for raw in json.loads(page.read_text())["results"]:
            row, reason = normalize_observation(raw, date.fromisoformat(source_meta["params"]["d2"]))
            if row is None:
                excluded[reason] += 1
                continue
            if row["id"] in seen:
                raise ValueError("Duplicate source observation")
            seen.add(row["id"])
            if not 2001 <= row["year"] <= 2025:
                excluded["outside_common_complete_years"] += 1
                continue
            if row["accuracy"] is None or row["accuracy"] > 1000:
                excluded["accuracy_unknown_or_over_1km"] += 1
                continue
            row["region"] = geography.classify(row["lat"], row["lon"])
            row["season"] = SEASONS[date.fromisoformat(row["date"]).month % 12 // 3]
            key = "|".join((row["region"], row["season"], row["stage"]))
            groups[key].append(row)
    quotas = {k: len(v) for k, v in groups.items()} if all_observations else allocate_sample(groups, size)
    samples = []
    strata = []
    for key in sorted(groups):
        population = sorted(groups[key], key=lambda row: row["id"])
        chosen = random.Random(f"{seed}-{key}").sample(population, quotas[key])
        strata.append({"stratum": key, "population": len(population), "sample": quotas[key]})
        for row in chosen:
            samples.append({**row, "stratum": key, "sampling_weight": len(population) / quotas[key]})
    random.Random(seed).shuffle(samples)
    manifest = {"config": config, "created_at": datetime.now(timezone.utc).isoformat(), "eligible_population": sum(map(len, groups.values())), "exclusions": dict(excluded), "strata": strata, "samples": samples}
    write_json(path, manifest)
    return manifest


def preceding_days(observed: date, days: int = 14) -> list[date]:
    return [observed - timedelta(days=d) for d in range(days, 0, -1)]


def completed_composites(observed: date, count: int = 2) -> list[tuple[date, date]]:
    periods = []
    for year in (observed.year - 1, observed.year):
        start = date(year, 1, 1)
        while start.year == year:
            end = min(start + timedelta(days=8), date(year + 1, 1, 1))
            if end <= observed:
                periods.append((start, end))
            start = end
    return periods[-count:]


def parse_daymet(text: str, observed: date) -> dict:
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if line.startswith("year,yday,")), None)
    if header is None:
        raise ValueError("Daymet returned no daily-data header")
    values = {}
    for row in csv.DictReader(io.StringIO("\n".join(lines[header:]))):
        day = date(int(row["year"]), 1, 1) + timedelta(days=int(row["yday"]) - 1)
        low, high = float(row["tmin (deg c)"]), float(row["tmax (deg c)"])
        if math.isfinite(low) and math.isfinite(high) and -100 < low <= high < 70:
            values[day] = (low, high)
    needed = preceding_days(observed)
    daily = [{"date": d.isoformat(), "tmin_c": values[d][0], "tmax_c": values[d][1]} for d in needed if d in values]
    result = {"temperature_days": len(daily), "temperature_start": needed[0].isoformat(), "temperature_end": needed[-1].isoformat(), "daily": daily}
    if len(daily) == 14:
        result.update(temperature_status="ok", tmin_14d_c=min(r["tmin_c"] for r in daily), tmax_14d_c=max(r["tmax_c"] for r in daily), freezing_days=sum(r["tmin_c"] <= 0 for r in daily), hot_days=sum(r["tmax_c"] >= (100 - 32) / 1.8 for r in daily))
    else:
        result["temperature_status"] = "incomplete_14_day_window"
    return result


def parse_modis(payload: dict, observed: date) -> dict:
    if payload.get("nrows") != 1 or payload.get("ncols") != 1:
        raise ValueError("Expected the single MODIS pixel containing the observation")
    lookup = {(row["calendar_date"], row["band"]): row for row in payload.get("subset", [])}
    periods = completed_composites(observed)
    composites = []
    for start, end in periods:
        et = lookup.get((start.isoformat(), "ET_500m"))
        qc = lookup.get((start.isoformat(), "ET_QC_500m"))
        value = et["data"][0] if et and et.get("data") else None
        flag = qc["data"][0] if qc and qc.get("data") else None
        reason = "ok"
        if value is None or flag is None:
            reason = "missing_composite"
        elif not 0 <= value <= 32700:
            reason = "fill_or_negative_et"
        elif flag == 255 or flag & 1 or (flag >> 5) > 1:
            reason = "quality_rejected"
        composites.append({"start": start.isoformat(), "end": (end - timedelta(days=1)).isoformat(), "days": (end - start).days, "raw_et": value, "qc": flag, "status": reason, "et_mm": value * 0.1 if reason == "ok" else None, "tile": et.get("tile") if et else None})
    result = {"aet_composites": composites, "aet_status": "ok" if all(c["status"] == "ok" for c in composites) else "missing_or_quality_rejected", "aet_start": periods[0][0].isoformat(), "aet_end": (periods[-1][1] - timedelta(days=1)).isoformat(), "aet_window_days": sum(c["days"] for c in composites), "aet_lag_days": (observed - periods[-1][1]).days, "modis_cellsize_m": payload.get("cellsize"), "modis_xllcorner": payload.get("xllcorner"), "modis_yllcorner": payload.get("yllcorner")}
    if result["aet_status"] == "ok":
        result["aet_mm_day"] = sum(c["et_mm"] for c in composites) / result["aet_window_days"]
    return result


class Fetcher:
    def __init__(self, output: Path):
        self.folder = output / "cache"
        self.folder.mkdir(exist_ok=True)
        self.locks = {name: Lock() for name in ("daymet", "modis")}
        self.last = dict.fromkeys(self.locks, 0.0)
        self.client = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "monarch-phenology/0.1.0 (research pilot)", "Accept": "application/json,text/csv"})

    def get(self, service: str, url: str, params: dict) -> str:
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        path = self.folder / f"{service}-{key}.txt"
        if path.exists():
            return path.read_text()
        for attempt in range(5):
            with self.locks[service]:
                time.sleep(max(0, 0.6 - (time.monotonic() - self.last[service])))
                self.last[service] = time.monotonic()
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                body = response.text
                # Do not cache HTML login/error pages as scientific data.
                if service == "daymet" and "year,yday," not in body:
                    raise ValueError("Daymet returned no data")
                if service == "modis" and "subset" not in response.json():
                    raise ValueError("MODIS returned no subset")
                temp = path.with_suffix(f".{time.time_ns()}.tmp")
                temp.write_text(body)
                temp.replace(path)
                return body
            except (httpx.HTTPError, ValueError):
                if attempt == 4:
                    raise
                time.sleep(min(30, 2 ** (attempt + 1)))
        raise RuntimeError("Unreachable")


def enrich(row: dict, fetcher: Fetcher) -> dict:
    result = {**row}
    observed = date.fromisoformat(row["date"])
    days = preceding_days(observed)
    try:
        response = fetcher.get("daymet", DAYMET, {"lat": row["lat"], "lon": row["lon"], "vars": "tmin,tmax", "start": days[0].isoformat(), "end": days[-1].isoformat()})
        result.update(parse_daymet(response, observed))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        result.update(temperature_status="request_error", temperature_error=str(exc)[:400])
    periods = completed_composites(observed)
    try:
        response = fetcher.get("modis", MODIS, {"latitude": row["lat"], "longitude": row["lon"], "startDate": periods[0][0].strftime("A%Y%j"), "endDate": periods[-1][0].strftime("A%Y%j"), "kmAboveBelow": 0, "kmLeftRight": 0})
        result.update(parse_modis(json.loads(response), observed))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        result.update(aet_status="request_error", aet_error=str(exc)[:400])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("runs/phenology-map"))
    parser.add_argument("--output", type=Path, default=Path("runs/weather-pilot"))
    parser.add_argument("--sample-size", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--all", action="store_true", help="Enrich every eligible observation instead of sampling.")
    parser.add_argument("--limit", type=int, help="Process only this many pending observations for a smoke test.")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = sample_observations(args.source, args.output, args.sample_size, args.seed, args.all)
    directory = args.output / "observations"
    directory.mkdir(exist_ok=True)
    pending = [r for r in manifest["samples"] if not (directory / f"{r['id']}.json").exists()]
    if args.limit is not None:
        pending = pending[:args.limit]
    print(f"Sampled {len(manifest['samples'])} of {manifest['eligible_population']:,} eligible observations. Processing {len(pending)} pending records.", flush=True)
    fetcher = Fetcher(args.output)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(enrich, row, fetcher): row for row in pending}
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            write_json(directory / f"{result['id']}.json", result)
            if index % 20 == 0 or index == len(pending):
                print(f"Completed {index}/{len(pending)}", flush=True)
    fetcher.client.close()
    results = [json.loads((directory / f"{r['id']}.json").read_text()) for r in manifest["samples"] if (directory / f"{r['id']}.json").exists()]
    print(json.dumps({"completed": len(results), "temperature": dict(Counter(r["temperature_status"] for r in results)), "aet": dict(Counter(r["aet_status"] for r in results))}, indent=2), flush=True)


if __name__ == "__main__":
    main()
