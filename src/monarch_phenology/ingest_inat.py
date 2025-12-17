from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .db import dumps_json, ensure_schema, get_state, set_state
from .inat_client import InatClient, InatObservation, best_photo_urls


STATE_KEY_LAST_UPDATED_SINCE = "inat.last_updated_since"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_observation_fields(obs: dict[str, Any]) -> dict[str, Any]:
    user = obs.get("user") or {}
    taxon = obs.get("taxon") or {}

    time_observed_at = obs.get("time_observed_at")
    observed_at = _parse_iso(time_observed_at) if isinstance(time_observed_at, str) else None

    created_at = _parse_iso(obs.get("created_at")) if isinstance(obs.get("created_at"), str) else None
    updated_at = _parse_iso(obs.get("updated_at")) if isinstance(obs.get("updated_at"), str) else None

    lat = lon = None
    location = obs.get("location")
    if isinstance(location, str) and "," in location:
        try:
            lat_s, lon_s = location.split(",", 1)
            lat = float(lat_s)
            lon = float(lon_s)
        except ValueError:
            pass

    return {
        "observation_id": int(obs["id"]),
        "inat_url": f"https://www.inaturalist.org/observations/{int(obs['id'])}",
        "taxon_id": taxon.get("id"),
        "taxon_name": taxon.get("name"),
        "taxon_preferred_common_name": taxon.get("preferred_common_name"),
        "quality_grade": obs.get("quality_grade"),
        "captive": obs.get("captive"),
        "license_code": obs.get("license_code"),
        "observed_at": observed_at,
        "observed_on": obs.get("observed_on"),
        "created_at": created_at,
        "updated_at": updated_at,
        "latitude": lat,
        "longitude": lon,
        "positional_accuracy": obs.get("positional_accuracy"),
        "place_guess": obs.get("place_guess"),
        "user_id": user.get("id"),
        "user_login": user.get("login"),
        "description": obs.get("description"),
        "raw": dumps_json(obs),
    }


def _extract_photo_fields(observation_id: int, photo: dict[str, Any], position: int) -> dict[str, Any]:
    square, large, original = best_photo_urls(photo)
    return {
        "photo_id": int(photo["id"]),
        "observation_id": observation_id,
        "position": position,
        "url_square": square,
        "url_large": large,
        "url_original": original,
        "license_code": photo.get("license_code"),
        "attribution": photo.get("attribution"),
        "raw": dumps_json(photo),
    }


def ingest_inat(
    *,
    conn,
    taxon_id: int,
    place_id: int,
    quality_grade: str,
    per_page: int,
    backfill_days: int,
    overlap_hours: int,
    sleep_seconds: float,
    max_pages_per_run: int,
    max_retries: int,
    retry_backoff_seconds: float,
) -> dict[str, int]:
    ensure_schema(conn)

    last_updated_since = get_state(conn, STATE_KEY_LAST_UPDATED_SINCE)
    last_dt = _parse_iso(last_updated_since)
    if last_dt is None:
        last_dt = datetime.now(tz=timezone.utc) - timedelta(days=backfill_days)

    updated_since = _iso(last_dt - timedelta(hours=overlap_hours))

    client = InatClient(
        sleep_seconds=sleep_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    try:
        page = 1
        max_updated_at: datetime | None = None
        obs_count = 0
        photo_count = 0

        while True:
            if max_pages_per_run and page > max_pages_per_run:
                break

            data = client.list_observations(
                taxon_id=taxon_id,
                place_id=place_id,
                quality_grade=quality_grade,
                per_page=per_page,
                page=page,
                updated_since=updated_since,
                order_by="updated_at",
                order="asc",
            )
            results = data.get("results") or []
            if not results:
                break

            observations = [InatObservation(raw=o) for o in results]
            for o in observations:
                fields = _extract_observation_fields(o.raw)
                conn.execute(
                    """
                    INSERT INTO observations (
                      observation_id, inat_url, taxon_id, taxon_name, taxon_preferred_common_name,
                      quality_grade, captive, license_code,
                      observed_at, observed_on, created_at, updated_at,
                      latitude, longitude, positional_accuracy, place_guess,
                      user_id, user_login, description,
                      first_seen_at, last_seen_at,
                      raw
                    )
                    VALUES (
                      %(observation_id)s, %(inat_url)s, %(taxon_id)s, %(taxon_name)s, %(taxon_preferred_common_name)s,
                      %(quality_grade)s, %(captive)s, %(license_code)s,
                      %(observed_at)s, %(observed_on)s, %(created_at)s, %(updated_at)s,
                      %(latitude)s, %(longitude)s, %(positional_accuracy)s, %(place_guess)s,
                      %(user_id)s, %(user_login)s, %(description)s,
                      now(), now(),
                      %(raw)s::jsonb
                    )
                    ON CONFLICT (observation_id) DO UPDATE SET
                      inat_url = EXCLUDED.inat_url,
                      taxon_id = EXCLUDED.taxon_id,
                      taxon_name = EXCLUDED.taxon_name,
                      taxon_preferred_common_name = EXCLUDED.taxon_preferred_common_name,
                      quality_grade = EXCLUDED.quality_grade,
                      captive = EXCLUDED.captive,
                      license_code = EXCLUDED.license_code,
                      observed_at = EXCLUDED.observed_at,
                      observed_on = EXCLUDED.observed_on,
                      created_at = EXCLUDED.created_at,
                      updated_at = EXCLUDED.updated_at,
                      latitude = EXCLUDED.latitude,
                      longitude = EXCLUDED.longitude,
                      positional_accuracy = EXCLUDED.positional_accuracy,
                      place_guess = EXCLUDED.place_guess,
                      user_id = EXCLUDED.user_id,
                      user_login = EXCLUDED.user_login,
                      description = EXCLUDED.description,
                      last_seen_at = now(),
                      raw = EXCLUDED.raw
                    """,
                    fields,
                )
                obs_count += 1

                photos = o.raw.get("photos") or []
                for idx, photo in enumerate(photos):
                    pfields = _extract_photo_fields(o.observation_id, photo, idx)
                    conn.execute(
                        """
                        INSERT INTO photos (
                          photo_id, observation_id, position,
                          url_square, url_large, url_original,
                          license_code, attribution,
                          first_seen_at, last_seen_at,
                          raw
                        )
                        VALUES (
                          %(photo_id)s, %(observation_id)s, %(position)s,
                          %(url_square)s, %(url_large)s, %(url_original)s,
                          %(license_code)s, %(attribution)s,
                          now(), now(),
                          %(raw)s::jsonb
                        )
                        ON CONFLICT (photo_id) DO UPDATE SET
                          observation_id = EXCLUDED.observation_id,
                          position = EXCLUDED.position,
                          url_square = EXCLUDED.url_square,
                          url_large = EXCLUDED.url_large,
                          url_original = EXCLUDED.url_original,
                          license_code = EXCLUDED.license_code,
                          attribution = EXCLUDED.attribution,
                          last_seen_at = now(),
                          raw = EXCLUDED.raw
                        """,
                        pfields,
                    )
                    photo_count += 1

                if o.updated_at and (max_updated_at is None or o.updated_at > max_updated_at):
                    max_updated_at = o.updated_at

            conn.commit()
            page += 1

        if max_updated_at is not None:
            set_state(conn, STATE_KEY_LAST_UPDATED_SINCE, _iso(max_updated_at))

        return {"observations": obs_count, "photos": photo_count}
    finally:
        client.close()
