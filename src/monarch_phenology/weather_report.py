"""Build auditable figures and an interactive report for the weather pilot."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

import httpx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from .benchmark_jev import write_json
from .weather_pilot import REGIONS

COLORS = dict(zip(REGIONS, ["#c56c2e", "#315f76", "#6b8451"]))
FIELDS = ["tmin_14d_c", "tmax_14d_c", "aet_mm_day"]


def weighted_quantile(values: list, weights: list, quantiles: list) -> list:
    order = np.argsort(values)
    v, w = np.array(values)[order], np.array(weights)[order]
    cumulative = np.cumsum(w) / sum(w)
    return [float(v[min(np.searchsorted(cumulative, q), len(v) - 1)]) for q in quantiles]


def weighted_correlation(rows: list[dict], x: str, y: str) -> float | None:
    valid = [r for r in rows if x in r and y in r]
    if len(valid) < 3:
        return None
    a, b, w = [np.array([r[k] for r in valid], dtype=float) for k in (x, y, "sampling_weight")]
    a, b = a - np.average(a, weights=w), b - np.average(b, weights=w)
    denominator = np.sqrt(np.sum(w * a * a) * np.sum(w * b * b))
    return float(np.sum(w * a * b) / denominator) if denominator else None


def summarize(rows: list[dict]) -> dict:
    result = {"n": len(rows), "temperature_status": dict(Counter(r["temperature_status"] for r in rows)), "aet_status": dict(Counter(r["aet_status"] for r in rows))}
    for field in FIELDS:
        valid = [r for r in rows if field in r]
        if not valid:
            result[field] = {"n": 0}
            continue
        values, weights = [r[field] for r in valid], [r["sampling_weight"] for r in valid]
        result[field] = {"n": len(valid), "min": min(values), "max": max(values), "weighted_p05_p50_p95": weighted_quantile(values, weights, [0.05, 0.5, 0.95])}
    temp = [r for r in rows if "tmin_14d_c" in r]
    if temp:
        for label, predicate in (("at_or_below_freezing", lambda r: r["tmin_14d_c"] <= 0), ("at_or_above_100f", lambda r: r["tmax_14d_c"] >= (100 - 32) / 1.8)):
            result[label] = {"n": sum(predicate(r) for r in temp), "denominator": len(temp), "weighted_percent": 100 * sum(r["sampling_weight"] for r in temp if predicate(r)) / sum(r["sampling_weight"] for r in temp)}
    result["weighted_correlations"] = {f"{x}__{y}": weighted_correlation(rows, x, y) for x, y in ((FIELDS[0], FIELDS[1]), (FIELDS[0], FIELDS[2]), (FIELDS[1], FIELDS[2]))}
    result["urban_masked_aet"] = sum(any(c.get("raw_et") == 32762 for c in r.get("aet_composites", [])) for r in rows)
    return result


def figures(rows: list[dict], output: Path, complete: bool) -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.labelcolor": "#344539", "text.color": "#344539", "axes.edgecolor": "#c5cbbf", "xtick.color": "#5b665c", "ytick.color": "#5b665c", "figure.facecolor": "#fffdf7", "axes.facecolor": "#fffdf7"})
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.6))
    titles = ["Coldest daily minimum in prior 14 days", "Hottest daily maximum in prior 14 days", "Prior satellite actual evapotranspiration"]
    labels = ["Temperature (°F)", "Temperature (°F)", "Mean AET (mm/day)"]
    convert = lambda r, field: r[field] * 1.8 + 32 if field != "aet_mm_day" else r[field]
    for i, field in enumerate(FIELDS):
        ax = axes[0, i]
        all_values = [convert(r, field) for r in rows if field in r]
        width = 0.5 if field == "aet_mm_day" else 5
        low = min(all_values, default=0)
        high = max(all_values, default=1)
        if i == 0:
            low, high = min(low, 32), max(high, 32)
        if i == 1:
            low, high = min(low, 100), max(high, 100)
        bins = np.arange(np.floor(low / width) * width, np.ceil(high / width) * width + width * 1.01, width)
        for region in REGIONS:
            subset = [r for r in rows if r["region"] == region and field in r]
            if subset:
                weights = np.array([r["sampling_weight"] for r in subset])
                ax.hist([convert(r, field) for r in subset], bins=bins, weights=100 * weights / weights.sum(), histtype="step", linewidth=2, color=COLORS[region], label=f"{region} (n={len(subset)})")
        if i < 2:
            threshold = 32 if i == 0 else 100
            ax.axvline(threshold, color="#8b4c43", linestyle="--", linewidth=1)
            ax.text(threshold, 0.97, f" {threshold}°F", transform=ax.get_xaxis_transform(), va="top", fontsize=8)
        ax.set(title=titles[i] + f"\nn = {len(all_values)} valid observations", xlabel=labels[i], ylabel="Weighted share within region (%)")
        ax.grid(axis="y", alpha=0.15)
    pairs = [(FIELDS[0], FIELDS[1]), (FIELDS[0], FIELDS[2]), (FIELDS[1], FIELDS[2])]
    for i, (x, y) in enumerate(pairs):
        ax = axes[1, i]
        for region in REGIONS:
            subset = [r for r in rows if r["region"] == region and x in r and y in r]
            ax.scatter([convert(r, x) for r in subset], [convert(r, y) for r in subset], color=COLORS[region], s=17, alpha=0.55, edgecolors="none")
        ax.set(xlabel="Prior 14-day minimum (°F)" if x == FIELDS[0] else "Prior 14-day maximum (°F)", ylabel="Prior 14-day maximum (°F)" if y == FIELDS[1] else "Prior satellite AET (mm/day)")
        ax.grid(alpha=0.15)
    fig.suptitle("Conditions before monarch larva and pupa observations" + ("" if complete else " · PARTIAL PREVIEW"), fontsize=18, x=0.055, ha="left", y=0.98)
    fig.text(0.055, 0.935, f"{len(rows)} stratified observations · 2001–2025 · Daymet 1 km · MODIS MOD16A2GF 500 m", fontsize=10, color="#647066")
    fig.legend([Line2D([], [], color=COLORS[r], linewidth=2) for r in REGIONS], REGIONS, loc="upper center", bbox_to_anchor=(0.5, 0.916), ncol=3, frameon=False, fontsize=9)
    fig.text(0.055, 0.035, "Temperature uses days D−14 through D−1. AET averages the last two completed composites, usually 16 days ending 1–8 days before D.\nHistogram weights correct the sample design, not observer effort or missing AET. Scatter points are individual sampled observations. Presence-only distributions do not identify breeding limits.", fontsize=8, color="#647066")
    fig.subplots_adjust(top=0.81, bottom=0.13, left=0.055, right=0.98, hspace=0.36, wspace=0.3)
    fig.savefig(output / "weather-distributions.png", dpi=180)
    fig.savefig(output / "weather-distributions.pdf")
    plt.close(fig)


def build_report(output: Path, preview: bool = False) -> Path:
    manifest = json.loads((output / "manifest.json").read_text())
    paths = [output / "observations" / f"{r['id']}.json" for r in manifest["samples"]]
    rows = [json.loads(p.read_text()) for p in paths if p.exists()]
    for row in rows:
        row["urban_masked_aet"] = any(c.get("raw_et") == 32762 for c in row.get("aet_composites", []))
    complete = len(rows) == len(paths)
    if not complete and not preview:
        raise ValueError("Weather enrichment is incomplete. Use --preview to mark a partial report.")
    summaries = {"all": summarize(rows), **{region: summarize([r for r in rows if r["region"] == region]) for region in REGIONS}}
    summary = {"complete": complete, "sample_size": len(manifest["samples"]), "completed": len(rows), "eligible_population": manifest["eligible_population"], "groups": summaries}
    write_json(output / "summary.json", summary)
    fields = ["id", "date", "stage", "region", "season", "lat", "lon", "accuracy", "sampling_weight", "temperature_status", "temperature_start", "temperature_end", "temperature_days", *FIELDS[:2], "freezing_days", "hot_days", "aet_status", "aet_start", "aet_end", "aet_window_days", "aet_lag_days", FIELDS[2], "urban_masked_aet"]
    with (output / "observations.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    figures(rows, output, complete)
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    for name, url in {"plotly.min.js": "https://cdn.plot.ly/plotly-4.1.1.min.js", "plotly.LICENSE": "https://raw.githubusercontent.com/plotly/plotly.js/v4.1.1/LICENSE"}.items():
        path = assets / name
        if not path.exists():
            response = httpx.get(url, timeout=90, follow_redirects=True)
            response.raise_for_status()
            path.write_bytes(response.content)
    payload = {"rows": [{k: r.get(k) for k in fields} for r in rows], "summary": summary, "strata": manifest["strata"], "regions": REGIONS, "colors": COLORS}
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("templates").joinpath("weather_report.html").read_text()
    target = output / "index.html"
    target.write_text(template.replace("__WEATHER_DATA__", encoded))
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/weather-pilot"))
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    print(build_report(args.output, args.preview).resolve())


if __name__ == "__main__":
    main()
