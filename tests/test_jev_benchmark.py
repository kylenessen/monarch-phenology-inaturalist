import io
import json
import csv
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from monarch_phenology.benchmark_jev import annotation_stage, evaluate, run_benchmark, save_reports
from monarch_phenology.jev_client import (
    DESCRIPTIONS, STAGES, classify_image, parse_response, prepare_image, request_with_retry,
)


def response_for(stage):
    return {
        "model": "jev-1.14.0",
        "answers": {
            "life_stage": {"type": "choice", "choice": stage, "confidence": 1.0,
                           "probabilities": {s: float(s == stage) for s in DESCRIPTIONS}},
            **{f"is_{s}": {"type": "noul", "noul": float(s == stage)} for s in STAGES},
        },
        "usage": {"input_tokens": 100},
    }


def test_disputed_and_conflicting_annotations_are_excluded():
    egg = {"controlled_attribute_id": 1, "controlled_value_id": 7, "votes": []}
    assert annotation_stage({"annotations": [egg]}) == "egg"
    assert annotation_stage({"annotations": [egg, {**egg, "controlled_value_id": 2}]}) is None
    assert annotation_stage({"annotations": [{**egg, "votes": [{"vote_flag": False}]}]}) is None
    assert annotation_stage({"annotations": [{**egg, "vote_score": -1}]}) is None
    assert annotation_stage({"annotations": []}) is None


@pytest.mark.parametrize("size", [(60, 40), (3000, 100), (2000, 4000), (800, 600)])
def test_images_fit_api_limits_without_cropping(size):
    original = io.BytesIO()
    Image.new("RGB", size, "green").save(original, "PNG")
    prepared = prepare_image(original.getvalue())
    with Image.open(io.BytesIO(prepared)) as image:
        assert image.format == "JPEG"
        assert all(280 <= value <= 1568 for value in image.size)
        assert not image.getexif()
        assert image.getpixel((image.width // 2, image.height // 2))[1] > 100


def test_live_request_shape_has_image_only_and_all_independent_questions():
    def handle(request):
        body = request.read()
        assert request.headers["TypeSafe-Danger-Zone-Images"] == "true"
        assert b'filename="photo.jpg"' in body
        assert b"expected_stage" not in body
        assert b"observation_id" not in body
        assert b'"state": {"photo":' in body
        assert all(f'"is_{s}"'.encode() in body for s in STAGES)
        return httpx.Response(200, json=response_for("egg"))
    with httpx.Client(transport=httpx.MockTransport(handle), headers={"TypeSafe-Danger-Zone-Images": "true"}) as client:
        assert classify_image(client, b"test image", "jev-1.14.0")["prediction"] == "egg"


def test_malformed_probabilities_are_rejected():
    raw = response_for("egg")
    raw["answers"]["is_egg"]["noul"] = float("nan")
    with pytest.raises(ValueError):
        parse_response(raw)
    raw = response_for("egg")
    del raw["answers"]["life_stage"]["probabilities"]["unknown"]
    with pytest.raises(ValueError):
        parse_response(raw)


def test_metrics_count_unknown_as_error_and_report_api_failures():
    samples = [{"photo_id": i, "expected_stage": s} for i, s in enumerate(["egg", "egg", "larva", "adult", "pupa"])]
    results = {str(i): {"status": "ok", **parse_response(response_for(s))} for i, s in enumerate(["egg", "unknown", "egg"])}
    results["3"] = {"status": "error"}
    metrics = evaluate(samples, results, 0.5)
    assert metrics["scored"] == 3
    assert metrics["failed"] == 1
    assert metrics["pending"] == 1
    assert metrics["accuracy"] == pytest.approx(1 / 3)
    assert metrics["per_stage"]["egg"]["precision"] == 0.5
    assert metrics["per_stage"]["egg"]["recall"] == 0.5
    assert metrics["per_stage"]["egg"]["independent"]["fp"] == 1
    assert metrics["per_stage"]["adult"]["recall"] is None
    assert metrics["balanced_accuracy"] is None


def test_retry_transient_but_not_auth_errors(monkeypatch):
    monkeypatch.setattr("monarch_phenology.jev_client.time.sleep", lambda _: None)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(429 if len(calls) == 1 else 200)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert request_with_retry(client, "GET", "https://example.test").status_code == 200
    assert len(calls) == 2
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            request_with_retry(client, "GET", "https://example.test")


def test_resume_skips_success_and_refuses_changed_model(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    (tmp_path / "photo.jpg").write_bytes(b"fixture")
    sample = {"photo_id": 1, "sha256": "fixture", "expected_stage": "egg", "image_path": "photo.jpg"}
    manifest = {"samples": [sample]}
    args = SimpleNamespace(output=tmp_path, model="jev-1.14.0", seed=42, max_items=0, threshold=0.5)
    calls = []
    def classify(*args):
        calls.append(args)
        return parse_response(response_for("egg"))
    monkeypatch.setattr("monarch_phenology.benchmark_jev.classify_image", classify)
    assert run_benchmark(args, manifest)["accuracy"] == 1
    assert run_benchmark(args, manifest)["accuracy"] == 1
    assert len(calls) == 1
    args.model = "other"
    with pytest.raises(ValueError, match="changed"):
        run_benchmark(args, manifest)


def test_review_includes_independent_disagreement_even_when_choice_is_correct(tmp_path):
    result = {"status": "ok", **parse_response(response_for("egg"))}
    result["stage_probabilities"]["adult"] = 0.8
    save_reports(tmp_path, {"samples": [{"photo_id": 1, "expected_stage": "egg"}]}, {"1": result}, 0.5)
    with (tmp_path / "review.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["review_reasons"] == "independent_questions_disagree"
