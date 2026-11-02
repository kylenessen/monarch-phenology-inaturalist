"""Attach life-status annotations and independently cross-check extreme weather."""

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import time

import httpx

from .benchmark_jev import write_json
from .weather_pilot import preceding_days


def life_status(observation: dict) -> str:
    annotations = [a for a in observation.get("annotations", []) if a["controlled_attribute_id"] == 17]
    if any((a.get("vote_score") or 0) < 0 or any(v.get("vote_flag") is False for v in a.get("votes", [])) for a in annotations):
        return "disputed"
    values = {a["controlled_value_id"] for a in annotations}
    return {frozenset({18}): "alive", frozenset({19}): "dead", frozenset({20}): "undetermined"}.get(frozenset(values), "unannotated" if not values else "disputed")


def audit(output: Path) -> dict:
    manifest = json.loads((output / "manifest.json").read_text())
    ids = {r["id"] for r in manifest["samples"]}
    annotations = {}
    for path in Path(manifest["config"]["source"]).joinpath("pages").glob("*.json"):
        for row in json.loads(path.read_text())["results"]:
            if row["id"] in ids:
                annotations[row["id"]] = life_status(row)
    directory = output / "audit"
    directory.mkdir(exist_ok=True)
    records = {}
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for sample in manifest["samples"]:
            path = output / "observations" / f"{sample['id']}.json"
            if not path.exists():
                continue
            row = json.loads(path.read_text())
            item = {"human_alive_status": annotations.get(row["id"], "unannotated"), "temperature_audit_flag": "not_checked"}
            records[str(row["id"])] = item
            if row.get("temperature_status") != "ok":
                continue
            extreme = row["tmin_14d_c"] <= 0 or row["tmax_14d_c"] >= (100 - 32) / 1.8 or max(d["tmax_c"] - d["tmin_c"] for d in row["daily"]) >= 40
            if not extreme:
                continue
            days = preceding_days(date.fromisoformat(row["date"]))
            params = {"latitude": row["lat"], "longitude": row["lon"], "start_date": days[0].isoformat(), "end_date": days[-1].isoformat(), "daily": "temperature_2m_min,temperature_2m_max", "models": "era5_land", "timezone": "auto"}
            cached = directory / f"era5-{row['id']}.json"
            try:
                if cached.exists():
                    payload = json.loads(cached.read_text())
                else:
                    response = client.get("https://archive-api.open-meteo.com/v1/archive", params=params)
                    response.raise_for_status()
                    payload = response.json()
                    write_json(cached, payload)
                    time.sleep(0.65)
                daily = payload["daily"]
                if daily["time"] != [d.isoformat() for d in days] or any(v is None for key in ("temperature_2m_min", "temperature_2m_max") for v in daily[key]):
                    raise ValueError("Incomplete ERA5-Land window")
                low, high = min(daily["temperature_2m_min"]), max(daily["temperature_2m_max"])
                delta = max(abs(low - row["tmin_14d_c"]), abs(high - row["tmax_14d_c"]))
                item.update(temperature_audit_flag="large_disagreement" if delta >= 10 else "checked", era5_tmin_14d_c=low, era5_tmax_14d_c=high, temperature_audit_max_difference_c=delta)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                item.update(temperature_audit_flag="unavailable", temperature_audit_error=str(exc)[:300])
    result = {"source": "ERA5-Land through Open-Meteo, approximately 9 km, local-day aggregates", "selection": "Daymet minimum <= 0 C, maximum >= 37.7778 C, or a daily temperature range >= 40 C", "flag_threshold_c": 10, "records": records}
    write_json(output / "audit.json", result)
    print(json.dumps({"life_status": dict(Counter(r["human_alive_status"] for r in records.values())), "temperature_audit": dict(Counter(r["temperature_audit_flag"] for r in records.values()))}, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/weather-pilot"))
    audit(parser.parse_args().output)


if __name__ == "__main__":
    main()
