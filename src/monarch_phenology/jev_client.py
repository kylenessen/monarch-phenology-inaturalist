"""Image-only Jev requests. No observation metadata enters the model payload."""

from __future__ import annotations

import io
import copy
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

EXTRA_LABELS = {
    "empty_chrysalis": {
        "true": "A visibly empty monarch chrysalis casing is present, typically a thin translucent or papery shell with an emergence opening and no developing butterfly inside. An emerged adult beside its empty casing can also qualify.",
        "false": "No visibly empty monarch chrysalis casing. An intact green chrysalis, a dark chrysalis containing a pre-emergence butterfly, a dead pupa still occupying its casing, or caterpillar shed skin alone is not an empty chrysalis. Do not assume a casing is empty from color alone.",
    },
    "no_obvious_monarch": {
        "true": "No monarch egg, caterpillar, occupied chrysalis, adult, empty chrysalis, or recognizable dead body parts can be visually located in the supplied photo. A milkweed plant or suitable habitat alone is not evidence. A target too small or blurred to identify counts as no obvious monarch.",
        "false": "At least one monarch organism, recognizable empty monarch chrysalis or monarch remains is visibly identifiable in this photo.",
    },
    "dead_remnants": {
        "true": "Recognizable monarch remains are visible, such as detached wings, a crushed or decomposing body, or a clearly dead whole monarch at any stage.",
        "false": "No recognizable dead monarch remains are visible. A motionless resting butterfly, dark pre-emergence chrysalis, empty chrysalis after successful emergence, shed skin, or worn wings on an otherwise intact butterfly alone does not establish death.",
    },
    "clustering": {
        "true": "Three or more adult monarchs are visibly gathered close together in a resting or roosting aggregation, including dense overlapping butterflies on branches or trunks.",
        "false": "No clear adult monarch resting aggregation is visible. A lone butterfly, a mating pair, scattered butterflies, or several adults independently visiting flowers is not clustering.",
    },
    "nectaring": {
        "true": "At least one adult monarch is visibly feeding at a flower, with a proboscis extended into floral structures or a clearly visible feeding posture with its head at the flower center.",
        "false": "No visible adult monarch feeding at a flower. Merely being near flowers, flying, or resting on a leaf or flower without visible feeding evidence is insufficient.",
    },
}
EVIDENCE_OPTIONS = {
    "monarch_visible": "At least one identifiable whole monarch egg, larva, pupa, or adult is visible and is not clearly dead. Resting individuals count. If live or indeterminate organisms and dead remains coexist, choose this option.",
    "dead_remnants_only": "The only identifiable monarch evidence is clearly dead bodies or recognizable body parts. Do not infer death just from an empty emerged chrysalis or shed skin.",
    "empty_chrysalis_only": "Only identifiable empty monarch chrysalis casings are visible. No occupied pupa, adult, larva, egg or clearly dead body is visible. An empty emerged casing is evidence of emergence rather than mortality.",
    "no_obvious_monarch": "No identifiable monarch organism, empty monarch chrysalis or dead remains can be located in the supplied photo, including habitat-only views or a target too small or blurry to identify.",
    "uncertain": "Possible monarch evidence is visible but its identity or evidence category cannot be resolved. This includes a case whose occupancy cannot be determined, or shed skin without an identifiable organism.",
}
LARVAL_OPTIONS = {
    "small_early": "A visibly small, slender monarch caterpillar consistent with early larval development. Use credible relative scale from nearby plant structures and visible developmental features together. This is a coarse early/small category, not an exact instar assignment.",
    "large_late": "A visibly large, robust monarch caterpillar consistent with late larval development, including an identifiable large hanging pre-pupation caterpillar. Use credible relative scale and visible developmental features together, not image pixel size. This is a coarse late/large category, not an exact instar assignment.",
    "intermediate_or_uncertain": "A monarch larva is visible but appears intermediate, scale or developmental cues are insufficient, the image is too poor to distinguish early from late development, or several larvae of different development are present without a clear main larva. Magnification or apparent pixel size alone is insufficient.",
    "not_applicable": "No identifiable monarch larva is visible in the photo. Eggs, occupied or empty chrysalises, adults and unidentifiable fragments do not have a larval development label.",
}
QUESTIONS_V2 = copy.deepcopy(QUESTIONS)
QUESTIONS_V2["life_stage"]["instructions"] = (
    "Which life stage is the main visibly identifiable monarch butterfly (Danaus plexippus) "
    "subject in `photo`? Use only visible image evidence. Do not infer an egg or caterpillar "
    "from milkweed or habitat alone. A clustering or nectaring butterfly is still adult. "
    "A clearly identifiable dead individual can retain its anatomical life stage, with death "
    "recorded separately. Choose unknown when the organism is not visible or identifiable, "
    "only an empty case is visible, or multiple life stages have no single main subject."
)
QUESTIONS_V2["evidence"] = {
    "type": "choice", "instructions": "What monarch evidence is visibly identifiable in `photo`?", "criteria": EVIDENCE_OPTIONS,
}
QUESTIONS_V2["larval_development"] = {
    "type": "choice",
    "instructions": "What coarse developmental group best describes the main visibly identifiable monarch caterpillar in `photo`? Use visible developmental features and reliable relative scale. Do not infer an exact instar, and do not use how much of the image the caterpillar occupies as evidence of actual size.",
    "criteria": LARVAL_OPTIONS,
}
for _label, _criteria in EXTRA_LABELS.items():
    QUESTIONS_V2[_label] = {
        "type": "noul",
        "instructions": f"Does the supplied photo meet the true definition for {_label.replace('_', ' ')}? Evaluate visible pixels only. Do not assume that a monarch is present just because this question mentions monarchs.",
        "criteria": _criteria,
    }


def get_questions(prompt_version: str = "v1") -> dict[str, Any]:
    if prompt_version not in {"v1", "v2"}:
        raise ValueError("Unknown prompt version")
    return QUESTIONS if prompt_version == "v1" else QUESTIONS_V2


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


def make_request(model: str, prompt_version: str = "v1") -> dict[str, Any]:
    reference = str(uuid.uuid4())
    return {
        "model": model,
        "state": {"photo": reference},
        "assets": {reference: {"type": "image", "part": "photo"}},
        "questions": get_questions(prompt_version),
    }


def probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid probability")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Probability outside 0..1")
    return float(value)


def parse_response(raw: dict[str, Any], prompt_version: str = "v1") -> dict[str, Any]:
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
    parsed = {
        "prediction": choice["choice"],
        "confidence": probability(choice["confidence"]),
        "probabilities": probabilities,
        "stage_probabilities": binary,
        "resolved_model": raw["model"],
        "usage": raw.get("usage", {}),
    }
    if prompt_version == "v2":
        evidence = raw["answers"]["evidence"]
        distribution = {k: probability(v) for k, v in evidence["probabilities"].items()}
        if evidence["type"] != "choice" or evidence["choice"] not in EVIDENCE_OPTIONS:
            raise ValueError("Invalid evidence answer")
        if set(distribution) != set(EVIDENCE_OPTIONS) or not math.isclose(sum(distribution.values()), 1, abs_tol=0.01):
            raise ValueError("Invalid evidence distribution")
        extras = {}
        for label in EXTRA_LABELS:
            answer = raw["answers"][label]
            if answer["type"] != "noul":
                raise ValueError("Invalid extra label answer")
            extras[label] = probability(answer["noul"])
        parsed.update(evidence=evidence["choice"], evidence_confidence=probability(evidence["confidence"]),
                      evidence_probabilities=distribution, extra_probabilities=extras)
        larval = raw["answers"]["larval_development"]
        distribution = {k: probability(v) for k, v in larval["probabilities"].items()}
        if larval["type"] != "choice" or larval["choice"] not in LARVAL_OPTIONS:
            raise ValueError("Invalid larval development answer")
        if set(distribution) != set(LARVAL_OPTIONS) or not math.isclose(sum(distribution.values()), 1, abs_tol=0.01):
            raise ValueError("Invalid larval development distribution")
        parsed.update(larval_development=larval["choice"], larval_development_confidence=probability(larval["confidence"]),
                      larval_development_probabilities=distribution)
    return parsed


def classify_image(client: httpx.Client, image: bytes, model: str, prompt_version: str = "v1") -> dict[str, Any]:
    response = request_with_retry(
        client, "POST", "https://api.typesafe.ai/v1/systemone",
        files=[
            ("request", (None, json.dumps(make_request(model, prompt_version)), "application/json")),
            ("photo", ("photo.jpg", image, "image/jpeg")),
        ],
    )
    raw = response.json()
    return {**parse_response(raw, prompt_version), "raw_response": raw}
