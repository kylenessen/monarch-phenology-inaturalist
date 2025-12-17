from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str
    timeout_seconds: float = 60.0


class OpenRouterClient:
    def __init__(self, cfg: OpenRouterConfig):
        self._cfg = cfg
        self._client = httpx.Client(
            base_url="https://openrouter.ai/api/v1",
            timeout=httpx.Timeout(cfg.timeout_seconds),
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def classify_image(
        self,
        *,
        image_url: str,
        observer_notes: str,
        prompt: str,
    ) -> dict[str, Any]:
        payload = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Observer notes:\n{observer_notes}"},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }
        resp = self._client.post("/chat/completions", content=json.dumps(payload))
        resp.raise_for_status()
        return resp.json()

