from datetime import date, timedelta

import pytest

from monarch_phenology.weather_pilot import allocate_sample, completed_composites, parse_daymet, parse_modis, preceding_days


def test_temperature_window_excludes_observation_day():
    observed = date(2025, 3, 1)
    days = preceding_days(observed)
    assert len(days) == 14
    assert days[0] == date(2025, 2, 15)
    assert days[-1] == date(2025, 2, 28)
    lines = ["metadata", "year,yday,tmax (deg c),tmin (deg c)"]
    for day in days:
        lines.append(f"{day.year},{day.timetuple().tm_yday},30,-1")
    lines.append("2025,60,60,-80")  # Must not influence antecedent extremes.
    result = parse_daymet("\n".join(lines), observed)
    assert result["temperature_status"] == "ok"
    assert result["tmin_14d_c"] == -1
    assert result["tmax_14d_c"] == 30
    assert result["freezing_days"] == 14


def test_daymet_missing_leap_year_december_31_is_not_silently_filled():
    observed = date(2025, 1, 7)
    lines = ["year,yday,tmax (deg c),tmin (deg c)"]
    for d in preceding_days(observed):
        if d == date(2024, 12, 31):
            continue
        lines.append(f"{d.year},{d.timetuple().tm_yday},20,5")
    result = parse_daymet("\n".join(lines), observed)
    assert result["temperature_days"] == 13
    assert result["temperature_status"] == "incomplete_14_day_window"
    assert "tmin_14d_c" not in result


@pytest.mark.parametrize("observed", [date(2025, 1, 1), date(2024, 1, 3), date(2025, 6, 18), date(2025, 6, 19)])
def test_aet_uses_only_completed_composites(observed):
    periods = completed_composites(observed)
    assert len(periods) == 2
    assert all(end <= observed for start, end in periods)
    assert periods[0][1] == periods[1][0]
    assert 0 <= (observed - periods[-1][1]).days <= 7
    assert all(5 <= (end - start).days <= 8 for start, end in periods)


def modis_payload(observed, raw=(80, 160), qc=(0, 32)):
    rows = []
    for (start, end), et, flag in zip(completed_composites(observed), raw, qc):
        rows.extend([
            {"calendar_date": start.isoformat(), "band": "ET_500m", "data": [et], "tile": "test"},
            {"calendar_date": start.isoformat(), "band": "ET_QC_500m", "data": [flag]},
        ])
    return {"nrows": 1, "ncols": 1, "subset": rows}


def test_aet_scale_and_duration_weighting():
    observed = date(2025, 6, 19)
    result = parse_modis(modis_payload(observed), observed)
    assert result["aet_status"] == "ok"
    assert result["aet_mm_day"] == pytest.approx((8 + 16) / 16)
    observed = date(2025, 1, 1)
    result = parse_modis(modis_payload(observed), observed)
    assert result["aet_window_days"] == 14  # 8 days plus the last 6 days of a leap year.
    assert result["aet_mm_day"] == pytest.approx(24 / 14)


@pytest.mark.parametrize("raw,qc", [((32762, 80), (0, 0)), ((80, 80), (0, 97)), ((-1, 80), (0, 0))])
def test_fill_and_bad_quality_are_missing_not_zero(raw, qc):
    observed = date(2025, 6, 19)
    result = parse_modis(modis_payload(observed, raw, qc), observed)
    assert result["aet_status"] == "missing_or_quality_rejected"
    assert "aet_mm_day" not in result


def test_sampling_weights_recover_the_eligible_population():
    groups = {"large": list(range(1000)), "small": list(range(20)), "tiny": list(range(3))}
    quotas = allocate_sample(groups, 100)
    assert sum(quotas.values()) == 100
    assert quotas["tiny"] == 3
    assert quotas["small"] >= 8
    assert sum(quotas[k] * len(v) / quotas[k] for k, v in groups.items()) == 1023


def test_report_weighted_statistics():
    from monarch_phenology.weather_report import weighted_correlation, weighted_quantile

    assert weighted_quantile([1, 2, 3], [1, 8, 1], [.05, .5, .95]) == [1, 2, 3]
    rows = [{"x": v, "y": 2 * v + 4, "sampling_weight": v + 1} for v in range(4)]
    assert weighted_correlation(rows, "x", "y") == pytest.approx(1)
    assert weighted_correlation(rows[:2], "x", "y") is None


def test_report_refuses_incomplete_enrichment(tmp_path):
    from monarch_phenology.benchmark_jev import write_json
    from monarch_phenology.weather_report import build_report

    write_json(tmp_path / "manifest.json", {"samples": [{"id": 1}]})
    with pytest.raises(ValueError, match="incomplete"):
        build_report(tmp_path)
