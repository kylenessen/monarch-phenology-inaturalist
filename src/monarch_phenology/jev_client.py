"""Image-only Jev requests. No observation metadata enters the model payload."""

from __future__ import annotations

import io
import json
import math
import time
import uuid
from typing import Any

import httpx
from PIL import Image, ImageOps

STAGES = {"egg": 7, "larva": 6, "pupa": 4, "adult": 2}
DESCRIPTIONS = {
    "egg": "A monarch egg, small and pale with a ridged shell.",
    "larva": "A monarch caterpillar, including small early instars and large striped larvae.",
    "pupa": "A monarch pupa or chrysalis, including green and dark pre-emergence chrysalises.",
    "adult": "An adult monarch butterfly with developed wings, including newly emerged adults.",
    "unknown": "No identifiable monarch life stage, an empty shell, or multiple different stages with no single main subject.",
}
QUESTIONS = {
    "life_stage": {
        "type": "choice",
        "instructions": (
            "Which life stage is the main monarch butterfly (Danaus plexippus) subject "
            "in `photo`? Use only visible evidence. Select unknown when it cannot be determined."
        ),
        "criteria": DESCRIPTIONS,
    },
    **{
        f"is_{stage}": {
            "type": "noul",
            "instructions": f"Does `photo` visibly contain a monarch in the {stage} life stage?",
            "criteria": {"true": description, "false": "That monarch life stage is not visible."},
        }
        for stage, description in DESCRIPTIONS.items() if stage in STAGES
    },
}


def request_with_retry(client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Bounded retries for transient failures. Authentication errors fail immediately."""
    for attempt in range(5):
        try:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (408, 429, 500, 502, 503, 504) or attempt == 4:
                raise
            try:
                delay = float(exc.response.headers.get("Retry-After", 2 ** attempt))
            except ValueError:
                delay = 2 ** attempt
        except httpx.TransportError:
            if attempt == 4:
                raise
            delay = 2 ** attempt
        time.sleep(max(0, delay))
    raise AssertionError("unreachable")


def prepare_image(data: bytes) -> bytes:
    """Rotate, strip metadata, shrink and pad to Jev's 280..1568 pixel limits."""
    with Image.open(io.BytesIO(data)) as original:
        img = ImageOps.exif_transpose(original).convert("RGB")
        img.thumbnail((1568, 1568))
        canvas = Image.new("RGB", (max(280, img.width), max(280, img.height)), "white")
        canvas.paste(img, ((canvas.width - img.width) // 2, (canvas.height - img.height) // 2))
        output = io.BytesIO()
        canvas.save(output, "JPEG", quality=90)
        return output.getvalue()


def make_request(model: str) -> dict[str, Any]:
    reference = str(uuid.uuid4())
    return {
        "model": model,
        "state": {"photo": reference},
        "assets": {reference: {"type": "image", "part": "photo"}},
        "questions": QUESTIONS,
    }


def probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid probability")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Probability outside 0..1")
    return float(value)


def parse_response(raw: dict[str, Any]) -> dict[str, Any]:
    choice = raw["answers"]["life_stage"]
    if choice["type"] != "choice" or choice["choice"] not in DESCRIPTIONS:
        raise ValueError("Invalid life stage answer")
    probabilities = {key: probability(value) for key, value in choice["probabilities"].items()}
    if set(probabilities) != set(DESCRIPTIONS) or not math.isclose(sum(probabilities.values()), 1, abs_tol=0.01):
        raise ValueError("Invalid choice distribution")
    binary = {}
    for stage in STAGES:
        answer = raw["answers"][f"is_{stage}"]
        if answer["type"] != "noul":
            raise ValueError("Invalid independent stage answer")
        binary[stage] = probability(answer["noul"])
    return {
        "prediction": choice["choice"],
        "confidence": probability(choice["confidence"]),
        "probabilities": probabilities,
        "stage_probabilities": binary,
        "resolved_model": raw["model"],
        "usage": raw.get("usage", {}),
    }


def classify_image(client: httpx.Client, image: bytes, model: str) -> dict[str, Any]:
    response = request_with_retry(
        client, "POST", "https://api.typesafe.ai/v1/systemone",
        files=[
            ("request", (None, json.dumps(make_request(model)), "application/json")),
            ("photo", ("photo.jpg", image, "image/jpeg")),
        ],
    )
    raw = response.json()
    return {**parse_response(raw), "raw_response": raw}
