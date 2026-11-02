from datetime import date, timedelta
import gzip
import json

import pytest

from monarch_phenology.daymet_archive import VARIABLES
from monarch_phenology.weather_full import connect, decode_result, export, plan, save_result, weather_params


def test_exact_seven_days_and_missing_dates():
    params=weather_params({'date':'2025-01-07','lat':38,'lon':-120})
    assert params['start']=='2024-12-31'
    assert params['end']=='2025-01-06'
    body='year,yday,'+','.join(VARIABLES.values())+'\n'
    body+='\n'.join(f'2025,{i},5,25,1,1000,200,0,43200' for i in range(1,8))
    result=decode_result('daymet',params,body)
    assert len(result['daily'])==6  # January 7 is outside the window.
    assert result['status']=='incomplete_window'
    assert 'tmin_median' not in result['metrics']


def test_plan_preserves_unavailable_dates_reuses_jobs_and_exports(tmp_path,monkeypatch):
    source=tmp_path/'source';(source/'pages').mkdir(parents=True)
    (source/'source.json').write_text(json.dumps({'complete':True,'params':{'d2':'2026-11-02'}}))
    rows=[{'id':i,'date':d,'year':int(d[:4]),'lat':38.,'lon':-120.,'accuracy':a,'stage':'larva'} for i,d,a in [(1,'2025-06-08',10),(2,'2025-06-09',None),(3,'2025-06-08',10),(4,'2026-06-08',10),(5,'2025-06-08',1001)]]
    (source/'pages'/'1.json').write_text(json.dumps({'results':rows}))
    monkeypatch.setattr('monarch_phenology.weather_full.normalize_observation',lambda r,c:(r,None))
    monkeypatch.setattr('monarch_phenology.weather_full.available_land_years',lambda o,p:[2025])
    out=tmp_path/'output';db=connect(out)
    try:
        config=plan(db,source,out,tmp_path/'pilot')
        assert plan(db,source,out,tmp_path/'pilot')==config
        assert db.execute('SELECT count(*) FROM observations').fetchone()[0]==4
        assert db.execute('SELECT count(*) FROM requests').fetchone()[0]==3
        assert db.execute('SELECT reason FROM excluded_observations').fetchone()[0]=='accuracy_over_1km'
        unavailable=db.execute('SELECT * FROM enriched_observations WHERE id=4').fetchone()
        assert unavailable['weather_status']=='outside_available_years'
        assert unavailable['landcover_status']=='year_unavailable'
        for job in db.execute("SELECT * FROM requests WHERE service='daymet'").fetchall():
            params=json.loads(job['params'])
            start=date.fromisoformat(params['start'])
            body='year,yday,'+','.join(VARIABLES.values())+'\n'
            body+='\n'.join(f'2025,{(start+timedelta(days=i)).timetuple().tm_yday},5,25,1,1000,200,0,43200' for i in range(7))
            result=decode_result('daymet',params,body)
            save_result(db,job,{**result,'body':body,'attempts':1,'response_code':200})
            assert gzip.decompress(db.execute('SELECT response_gzip FROM requests WHERE key=?',(job['key'],)).fetchone()[0]).decode()==body
        assert db.execute('SELECT count(*) FROM weather_daily').fetchone()[0]==8
        assert db.execute('SELECT tmin_median_7d FROM enriched_observations WHERE id=1').fetchone()[0]==5
        job=db.execute("SELECT * FROM requests WHERE service='landcover'").fetchone()
        body=json.dumps({'features':[{'properties':{'PALETTE_INDEX':21}}]})
        save_result(db,job,{**decode_result('landcover',json.loads(job['params']),body),'body':body})
        assert db.execute('SELECT count(*) FROM enriched_observations WHERE habitat_group=?',('Developed',)).fetchone()[0]==3
        export(db,out)
        with gzip.open(out/'observations.csv.gz','rt') as handle:
            assert len(handle.readlines())==5
        with pytest.raises(ValueError,match='configuration changed'):
            plan(db,source,out,tmp_path/'pilot',last_year=2024)
    finally:db.close()
