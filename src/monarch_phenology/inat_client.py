from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # iNat uses ISO 8601 with timezone, e.g. "2025-12-16T14:13:00-08:00"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class InatObservation:
    raw: dict[str, Any]

    @property
    def observation_id(self) -> int:
        return int(self.raw["id"])

    @property
    def inat_url(self) -> str:
        return f"https://www.inaturalist.org/observations/{self.observation_id}"

    @property
    def updated_at(self) -> datetime | None:
        return _parse_dt(self.raw.get("updated_at"))


class InatClient:
    def __init__(self, *, sleep_seconds: float = 0.5, timeout_seconds: float = 30.0):
        self._sleep_seconds = sleep_seconds
        self._client = httpx.Client(
            base_url="https://api.inaturalist.org/v1",
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": "monarch-phenology/0.1.0"},
        )

    def close(self) -> None:
        self._client.close()

    def list_observations(
        self,
        *,
        taxon_id: int,
        place_id: int,
        quality_grade: str,
        per_page: int,
        page: int,
        updated_since: str | None,
        order_by: str = "updated_at",
        order: str = "asc",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "taxon_id": taxon_id,
            "place_id": place_id,
            "quality_grade": quality_grade,
            "per_page": per_page,
            "page": page,
            "order_by": order_by,
            "order": order,
        }
        if updated_since:
            params["updated_since"] = updated_since

        resp = self._client.get("/observations", params=params)
        resp.raise_for_status()
        data = resp.json()
        time.sleep(self._sleep_seconds)
        return data


def best_photo_urls(photo: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    square = photo.get("url")
    original = photo.get("original_url")
    large = None

    if isinstance(square, str) and "square." in square:
        large = square.replace("/square.", "/large.")

    # Sometimes original is not provided; try the open-data pattern.
    if original is None and isinstance(square, str) and "/photos/" in square:
        # Common pattern: .../photos/<id>/square.jpg -> .../photos/<id>/original.jpeg
        original_guess = square.replace("/square.jpg", "/original.jpeg")
        if original_guess != square:
            original = original_guess

    return square, large, original

