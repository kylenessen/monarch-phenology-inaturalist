"""Build a local HTML reviewer for a completed Jev benchmark."""

import argparse
import base64
import csv
import json
from pathlib import Path


def build_review(run_dir: Path, all_photos: bool = False, embed_images: bool = True) -> Path:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    results = json.loads((run_dir / "results.json").read_text())
    samples = {str(s["photo_id"]): s for s in manifest["samples"]}
    with (run_dir / ("predictions.csv" if all_photos else "review.csv")).open(newline="") as handle:
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
            **({"image_src": "data:image/jpeg;base64," + base64.b64encode((run_dir / image).read_bytes()).decode("ascii")} if embed_images else {}),
            "confidence": result.get("confidence"),
            "stage_probabilities": result.get("stage_probabilities", {}),
            "extra_probabilities": result.get("extra_probabilities", {}),
            "evidence": result.get("evidence"),
            "larval_development": result.get("larval_development"),
            "larval_development_confidence": result.get("larval_development_confidence"),
            "phenology_stage": result.get("phenology_stage"),
            "reasons": [reason for reason in row["review_reasons"].split(", ") if reason],
        })
    items.sort(key=lambda item: ("choice_disagrees" not in item["reasons"], item["expected_stage"], item["photo_id"]))
    data = {"fingerprint": results["fingerprint"], "model": results["model"], "prompt_version": results.get("prompt_version", "v1"), "all_photos": all_photos, "items": items}
    # Escape HTML delimiters so embedded source text cannot terminate the data script.
    encoded = json.dumps(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("templates").joinpath("jev_review.html").read_text()
    output = run_dir / "review.html"
    output.write_text(template.replace("__REVIEW_DATA__", encoded))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("runs/jev-pilot"))
    parser.add_argument("--all-photos", action="store_true", help="Include every sampled photo for auditing negatives as well as flagged predictions.")
    parser.add_argument("--linked-images", action="store_true", help="Use cached images beside the HTML for a lighter page served over localhost.")
    args = parser.parse_args()
    print(build_review(args.run_dir, args.all_photos, not args.linked_images).resolve())


if __name__ == "__main__":
    main()
