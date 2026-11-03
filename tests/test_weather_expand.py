from datetime import date, timedelta

import pytest

from monarch_phenology.weather_expand import summarize_window
from monarch_phenology.landcover_pilot import category


def daily_rows():
    return [{'date':(date(2025,6,1)+timedelta(days=i)).isoformat(),'tmin':float(i),'tmax':float(i+20),'prcp':float(i%2)*2,'vp':1000.,'srad':200.,'swe':0.,'dayl':43200.} for i in range(14)]


def test_medians_extremes_and_units_exclude_observation_date():
    rows=daily_rows()
    rows.append({**rows[0],'date':'2025-06-15','tmin':-80,'tmax':60})
    metrics=summarize_window(rows,date(2025,6,15))
    assert metrics['tmin_median']==6.5
    assert metrics['tmax_median']==26.5
    assert metrics['tmin_extreme']==0
    assert metrics['tmin_highest']==13
    assert metrics['tmax_extreme']==33
    assert metrics['tmean']==16.5
    assert metrics['dtr_mean']==20
    assert metrics['precip_total']==14
    assert metrics['wet_days']==7
    assert metrics['vapor_median']==1
    assert metrics['daylength_median']==12
    assert metrics['solar_mean']==pytest.approx(8.64)
    assert metrics['freezing_days']==1


def test_short_window_and_variable_specific_missingness():
    rows=daily_rows()
    rows[0]['prcp']=None
    metrics=summarize_window(rows,date(2025,6,15))
    assert 'precip_total' not in metrics
    assert metrics['complete_variables']==6
    assert metrics['tmin_median']==6.5
    short=summarize_window(rows,date(2025,6,15),7)
    assert short['tmin_median']==10
    assert short['tmin_highest']==13
    assert short['complete_variables']==7
    missing=summarize_window(rows[1:],date(2025,6,15))
    assert missing['days_found']==13
    assert 'tmin_median' not in missing
    assert 'tmin_highest' not in missing


def test_nlcd_nodata_is_not_a_land_cover_class():
    def payload(value):
        return {'features':[{'properties':{'PALETTE_INDEX':value}}]}
    assert category(payload(21))==21
    assert category(payload(250)) is None
    assert category({'features':[]}) is None
    with pytest.raises(ValueError,match='Unknown'):
        category(payload(123))
    with pytest.raises(ValueError,match='native category'):
        category({'features':[{'properties':{'red':255}}]})


def test_explorer_preserves_cached_temperature_and_missing_landcover(tmp_path):
    import csv
    import json
    from monarch_phenology.benchmark_jev import write_json
    from monarch_phenology.weather_explorer import build

    for folder in ('expanded','landcover','observations','assets'):
        (tmp_path/folder).mkdir()
    for name in ('plotly.min.js','plotly.LICENSE'):
        (tmp_path/'assets'/name).write_text('fixture')
    row={'id':1,'date':'2025-06-15','year':2025,'region':'California coast','stage':'larva','lat':38.5,'lon':-121.5,'accuracy':10,'sampling_weight':2}
    write_json(tmp_path/'manifest.json',{'samples':[row],'eligible_population':2})
    write_json(tmp_path/'expanded'/'1.json',{**row,'daymet_status':'request_error','daily':[],'windows':{}})
    with pytest.raises(ValueError,match='incomplete'):
        build(tmp_path)
    write_json(tmp_path/'landcover'/'1.json',{'landcover_status':'outside_coverage_or_nodata','landcover_year':2025})
    write_json(tmp_path/'observations'/'1.json',{'temperature_status':'ok','daily':[{'date':r['date'],'tmin_c':r['tmin'],'tmax_c':r['tmax']} for r in daily_rows()]})
    assert build(tmp_path).exists()
    summary=json.loads((tmp_path/'expanded-summary.json').read_text())
    assert summary['weather']=={'temperature_only_cached':1}
    with (tmp_path/'expanded-observations.csv').open() as f:
        export=next(csv.DictReader(f))
    assert export['tmin_median_14d']=='6.5'
    assert export['precip_total_14d']==''
    assert export['landcover_label']=='Unavailable'
