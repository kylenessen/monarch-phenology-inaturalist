from datetime import date
import json

import httpx
import pytest

from monarch_phenology import phenology_map as pm


def observation(**changes):
    return {
        "id": 1, "observed_on": "2025-03-05", "location": "38.5,-121.5",
        "positional_accuracy": 20, "geoprivacy": None, "obscured": False,
        "quality_grade": "research",
        "annotations": [{"controlled_attribute_id": 1, "controlled_value_id": 6}],
        **changes,
    }


def test_location_order_and_week_alignment():
    row, reason = pm.normalize_observation(observation(), date(2026, 11, 2))
    assert reason is None
    assert (row["lat"], row["lon"]) == (38.5, -121.5)
    assert row["week"] == 9
    assert pm.seasonal_week(date(2024, 3, 5)) == pm.seasonal_week(date(2025, 3, 5))
    assert pm.seasonal_week(date(2024, 2, 29)) == 8
    assert pm.seasonal_week(date(2025, 12, 31)) == 52
    assert pm.seasonal_week(date(2025, 1, 1)) == 0


@pytest.mark.parametrize("changes,reason", [
    ({"obscured": True}, "obscured_or_private"),
    ({"geoprivacy": "private"}, "obscured_or_private"),
    ({"observed_on": None}, "missing_or_invalid_date"),
    ({"observed_on": "2027-01-01"}, "future_date"),
    ({"location": "nan,-120"}, "missing_or_invalid_location"),
    ({"location": "100,-120"}, "missing_or_invalid_location"),
    ({"location": None}, "missing_or_invalid_location"),
    ({"annotations": [{"controlled_attribute_id": 1, "controlled_value_id": 7}]}, "conflicting_or_disputed_stage"),
    ({"annotations": [{"controlled_attribute_id": 1, "controlled_value_id": 6}, {"controlled_attribute_id": 1, "controlled_value_id": 4}]}, "conflicting_or_disputed_stage"),
    ({"annotations": [{"controlled_attribute_id": 1, "controlled_value_id": 6, "votes": [{"vote_flag": False}]}]}, "conflicting_or_disputed_stage"),
])
def test_exclusion_rules(changes, reason):
    assert pm.normalize_observation(observation(**changes), date(2026, 11, 2)) == (None, reason)


def test_unknown_and_coarse_accuracy_remain_available_for_ui_filters():
    for value in (None, 5000):
        row, reason = pm.normalize_observation(observation(positional_accuracy=value), date(2026, 11, 2))
        assert reason is None
        assert row["accuracy"] == value


def mock_api(monkeypatch, rows):
    calls = []

    def handle(request):
        params = request.url.params
        calls.append(dict(params))
        eligible = sorted([row for row in rows if int(params.get("id_above", -1)) < row["id"] < int(params.get("id_below", 2_000_000_000))], key=lambda row: row["id"], reverse=True)
        return httpx.Response(200, json={"total_results": len(eligible), "results": eligible[:int(params["per_page"])]})

    original_client = httpx.Client
    monkeypatch.setattr(pm.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(pm.time, "sleep", lambda seconds: None)
    return calls


def test_partition_boundaries_have_no_gaps_or_duplicates(tmp_path, monkeypatch):
    ids = [1, 99_999_999, 100_000_000, 100_000_001, 200_000_000, 300_000_000, 390_000_000]
    calls = mock_api(monkeypatch, [observation(id=i) for i in ids])
    manifest = pm.fetch_observations(tmp_path)
    downloaded = [row["id"] for path in (tmp_path / "pages").glob("*.json") for row in json.loads(path.read_text())["results"]]
    assert sorted(downloaded) == ids
    assert manifest["complete"] and manifest["downloaded"] == len(ids)
    assert manifest["maximum_id"] == max(ids)
    calls_before = len(calls)
    assert pm.fetch_observations(tmp_path) == manifest
    assert len(calls) == calls_before


def test_resume_reconciles_page_written_before_manifest(tmp_path, monkeypatch):
    mock_api(monkeypatch, [observation(id=1), observation(id=10)])
    (tmp_path / "pages").mkdir()
    pm.write_json(tmp_path / "pages/segment-0-00000.json", {"results": [observation(id=10)]})
    pm.write_json(tmp_path / "source.json", {
        "complete": False, "params": {"per_page": 200}, "downloaded": 0, "pages": 0,
        "segments": [{"lower": 0, "upper": 100, "complete": False}],
    })
    manifest = pm.fetch_observations(tmp_path)
    assert manifest["downloaded"] == 2
    ids = [r["id"] for p in (tmp_path / "pages").glob("*.json") for r in json.loads(p.read_text())["results"]]
    assert sorted(ids) == [1, 10]


def test_incomplete_download_is_not_presented_as_finished(tmp_path):
    pm.write_json(tmp_path / "source.json", {"complete": False})
    with pytest.raises(ValueError, match="incomplete"):
        pm.build_map(tmp_path)


def test_build_counts_unique_observations_and_preserves_coordinates(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "assets").mkdir()
    for name in pm.ASSETS:
        (tmp_path / "assets" / name).write_text("cached test asset")
    pm.write_json(tmp_path / "source.json", {
        "complete": True, "downloaded": 3, "params": {"d2": "2026-11-02"},
        "started_at": "2026-11-02", "completed_at": "2026-11-02", "place": "North America", "place_id": 97394,
    })
    rows = [observation(id=1), observation(id=2, obscured=True), observation(id=3, annotations=[{"controlled_attribute_id": 1, "controlled_value_id": 4}])]
    pm.write_json(tmp_path / "pages/segment-0-00000.json", {"results": rows})
    html = pm.build_map(tmp_path).read_text()
    payload = json.loads(html.split('<script id="map-data" type="application/json">')[1].split('</script>')[0])
    assert payload["stats"]["mapped"] == 2
    assert payload["stats"]["larvae"] == payload["stats"]["pupae"] == 1
    assert payload["stats"]["excluded"] == {"obscured_or_private": 1}
    assert payload["observations"][0][4:6] == [38.5, -121.5]
    assert [r["level"] for r in payload["resolutions"]] == list(range(16))
    assert payload["preview"] is False

    pm.write_json(tmp_path / "pages/segment-0-00001.json", {"results": [rows[0]]})
    with pytest.raises(ValueError, match="Duplicate observation"):
        pm.build_map(tmp_path)
