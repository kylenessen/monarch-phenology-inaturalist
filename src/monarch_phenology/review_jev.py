"""Build a local HTML reviewer for a completed Jev benchmark."""

import argparse
import csv
import json
from pathlib import Path


def build_review(run_dir: Path) -> Path:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    results = json.loads((run_dir / "results.json").read_text())
    samples = {str(s["photo_id"]): s for s in manifest["samples"]}
    with (run_dir / "review.csv").open(newline="") as handle:
        flagged = list(csv.DictReader(handle))
    items = []
    for row in flagged:
        sample = samples[row["photo_id"]]
        result = results["results"].get(row["photo_id"], {})
        image = Path(sample["image_path"])
        if image.is_absolute() or ".." in image.parts:
            raise ValueError("Review images must be inside the run directory")
        if not (run_dir / image).is_file():
            raise ValueError(f"Missing cached image {image}")
        items.append({
            **{k: sample.get(k) for k in (
                "photo_id", "observation_id", "expected_stage", "observed_on",
                "image_path", "license_code", "attribution",
            )},
            "prediction": result.get("prediction", "unavailable"),
            "confidence": result.get("confidence"),
            "stage_probabilities": result.get("stage_probabilities", {}),
            "reasons": row["review_reasons"].split(", "),
        })
    items.sort(key=lambda item: ("choice_disagrees" not in item["reasons"], item["expected_stage"], item["photo_id"]))
    data = {"fingerprint": results["fingerprint"], "model": results["model"], "items": items}
    # Escape HTML delimiters so embedded source text cannot terminate the data script.
    encoded = json.dumps(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("templates").joinpath("jev_review.html").read_text()
    output = run_dir / "review.html"
    output.write_text(template.replace("__REVIEW_DATA__", encoded))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("runs/jev-pilot"))
    args = parser.parse_args()
    print(build_review(args.run_dir).resolve())


if __name__ == "__main__":
    main()
