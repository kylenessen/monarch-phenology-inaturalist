from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


logger = logging.getLogger(__name__)


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
    def __init__(
        self,
        *,
        sleep_seconds: float = 0.5,
        timeout_seconds: float = 30.0,
        max_retries: int = 5,
        retry_backoff_seconds: float = 2.0,
    ):
        self._sleep_seconds = sleep_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
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

        attempt = 0
        while True:
            try:
                resp = self._client.get("/observations", params=params)
                resp.raise_for_status()
                data = resp.json()
                time.sleep(self._sleep_seconds)
                return data
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                retry_after = e.response.headers.get("Retry-After")
                attempt += 1
                if attempt > self._max_retries:
                    raise

                if status == 429:
                    sleep_for = float(retry_after) if retry_after and retry_after.isdigit() else self._retry_backoff_seconds * attempt
                    logger.warning("iNat rate limited (429); sleeping %.1fs", sleep_for)
                    time.sleep(sleep_for)
                    continue
                if 500 <= status < 600:
                    sleep_for = self._retry_backoff_seconds * attempt
                    logger.warning("iNat server error %s; sleeping %.1fs", status, sleep_for)
                    time.sleep(sleep_for)
                    continue
                raise
            except (httpx.TimeoutException, httpx.RequestError):
                attempt += 1
                if attempt > self._max_retries:
                    raise
                sleep_for = self._retry_backoff_seconds * attempt
                logger.warning("iNat request error; sleeping %.1fs", sleep_for)
                time.sleep(sleep_for)


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
