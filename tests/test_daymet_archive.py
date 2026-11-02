from datetime import date
import json

import pytest

from monarch_phenology.daymet_archive import VARIABLES, fetch_point, make_plan, needed_years, parse_daily


def test_lookback_crosses_year_and_retains_observation_year():
    assert needed_years(date(2025, 1, 15), 60) == [2024, 2025]
    assert needed_years(date(2025, 7, 15), 60) == [2025]


def test_all_variables_units_metadata_and_missing_values():
    body = "Elevation: 5 meters\nyear,yday," + ",".join(VARIABLES.values()) + "\n2024,365,5,20,0,1000,300,-9999,40000"
    result = parse_daily(body)
    assert result["metadata"] == ["Elevation: 5 meters"]
    assert result["daily"][0] == {"date": "2024-12-30", "tmin": 5, "tmax": 20, "prcp": 0, "vp": 1000, "srad": 300, "swe": None, "dayl": 40000}
    with pytest.raises(ValueError, match="seven"):
        parse_daily("year,yday,tmin (deg c)\n2025,1,10")
    with pytest.raises(ValueError, match="Duplicate"):
        parse_daily(body + "\n2024,365,5,20,0,1000,300,0,40000")


def test_plan_deduplicates_exact_coordinates_and_reports_exclusions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / "pages").mkdir(parents=True)
    (source / "source.json").write_text(json.dumps({"complete": True, "params": {"d2": "2026-11-02"}}))
    rows = [
        {"id": 1, "date": "2025-01-15", "lat": 38.5, "lon": -121.5, "accuracy": 10},
        {"id": 2, "date": "2023-07-15", "lat": 38.5, "lon": -121.5, "accuracy": None},
        {"id": 3, "date": "2025-07-15", "lat": 38.500001, "lon": -121.5, "accuracy": 10},
        {"id": 4, "date": "2026-07-15", "lat": 38.5, "lon": -121.5, "accuracy": 10},
        {"id": 5, "date": "2025-07-15", "lat": 38.5, "lon": -121.5, "accuracy": 1500},
    ]
    (source / "pages" / "1.json").write_text(json.dumps({"results": rows}))
    monkeypatch.setattr("monarch_phenology.daymet_archive.normalize_observation", lambda row, cutoff: (row, None))
    output = tmp_path / "output"
    plan = make_plan(source, output)
    assert plan["summary"]["observations"] == 3
    assert plan["summary"]["planned_requests"] == 2
    assert plan["summary"]["unknown_accuracy_included"] == 1
    assert plan["summary"]["exclusions"] == {"outside_available_years_or_lookback": 1, "accuracy_over_1km": 1}
    assert next(p for p in plan["points"] if p["lat"] == 38.5)["years"] == [2023, 2024, 2025]
    assert make_plan(source, output) == plan
    with pytest.raises(ValueError, match="Settings changed"):
        make_plan(source, output, strict_accuracy=True)
    strict = make_plan(source, tmp_path / "strict", strict_accuracy=True)
    assert strict["summary"]["observations"] == 2


def test_fetch_saves_all_variables_in_one_request_and_detects_missing_year(tmp_path):
    class FakeFetcher:
        calls = []

        def get(self, service, url, params):
            self.calls.append((service, params))
            return "year,yday," + ",".join(VARIABLES.values()) + "\n" + "\n".join(f"2025,{i},5,20,0,1000,300,0,40000" for i in range(1, 366))

    fetcher = FakeFetcher()
    point = {"key": "test", "lat": 38.5, "lon": -121.5, "years": [2025]}
    result = fetch_point(point, tmp_path, fetcher)
    assert result["status"] == "ok"
    assert len(fetcher.calls) == 1
    assert fetcher.calls[0][0] == "daymet"
    assert set(fetcher.calls[0][1]["vars"].split(",")) == set(VARIABLES)
    assert json.loads((tmp_path / "points" / "test.json").read_text()) == result
    missing = fetch_point({**point, "years": [2024, 2025]}, tmp_path, fetcher)
    assert missing["status"] == "request_error"
