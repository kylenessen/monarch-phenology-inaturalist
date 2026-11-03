from datetime import date, timedelta
import gzip
import json

import pytest

from monarch_phenology.daymet_archive import VARIABLES
from monarch_phenology.weather_full import connect, decode_result, export, plan, save_result
from monarch_phenology.weather_full_explorer import build


def test_full_lab_keeps_unavailable_records_and_exact_daily_windows(tmp_path, monkeypatch):
    source=tmp_path/'atlas'
    (source/'pages').mkdir(parents=True)
    (source/'source.json').write_text(json.dumps({'complete':True,'params':{'d2':'2026-11-02'}}))
    rows=[{'id':i,'date':day,'year':int(day[:4]),'lat':38.,'lon':-120.,'accuracy':accuracy,'stage':'larva'}
          for i,day,accuracy in [(1,'2025-06-08',None),(2,'2025-06-09',10),(3,'2026-06-08',None),(4,'2025-06-10',10)]]
    (source/'pages'/'1.json').write_text(json.dumps({'results':rows}))
    monkeypatch.setattr('monarch_phenology.weather_full.normalize_observation',lambda r,c:(r,None))
    monkeypatch.setattr('monarch_phenology.weather_full.available_land_years',lambda o,p:[2025])
    class Geography:
        def __init__(self,output):pass
        def classify(self,lat,lon):return 'California coast'
    monkeypatch.setattr('monarch_phenology.weather_full_explorer.Regions',Geography)
    run=tmp_path/'run'
    out=tmp_path/'lab'
    out.mkdir()
    (out/'index.html').write_text('original pilot')
    db=connect(run)
    try:
        plan(db,source,run,tmp_path/'pilot')
        with pytest.raises(ValueError,match='pending or running'):
            build(run,out)
        for job in db.execute('SELECT * FROM requests').fetchall():
            params=json.loads(job['params'])
            if job['service']=='daymet' and params['end']=='2025-06-09':
                save_result(db,job,{'status':'request_error','body':'Unavailable','response_code':500})
                continue
            if job['service']=='daymet':
                # Include a day outside either window. It must not leak into the inspector.
                body='year,yday,'+','.join(VARIABLES.values())+'\n'
                body+='\n'.join(f'2025,{date(2025,6,1).timetuple().tm_yday+i},5,25,1,1000,200,0,43200' for i in range(10))
            else:
                body=json.dumps({'features':[{'properties':{'PALETTE_INDEX':21}}]})
            save_result(db,job,{**decode_result(job['service'],params,body),'body':body,'response_code':200})
        with pytest.raises(ValueError,match='final CSV exports'):
            build(run,out)
        export(db,run)
    finally:db.close()
    assert build(run,out).exists()
    assert (out/'pilot-weather-lab.html').read_text()=='original pilot'
    with gzip.open(out/'full-observations.json.gz','rt') as f:
        result=json.load(f)
    assert len(result)==4
    assert result[0]['accuracy'] is None
    assert result[0]['habitat_group']=='Developed'
    assert result[0]['windows']['7']['tmin_highest']==5
    assert result[2]['habitat_group']=='Unavailable'
    assert result[2]['daymet_status']=='outside_available_years'
    assert result[2]['windows']=={}
    assert result[3]['daymet_status']=='request_error'
    assert result[3]['windows']=={}
    import csv
    with gzip.open(out/'full-observations.csv.gz','rt') as f:
        exported=list(csv.DictReader(f))
    assert exported[0]['tmin_highest_7d']=='5.0'
    assert exported[3]['tmin_highest_7d']==''
    assert all(r['sampling_weight']==1 and '14' not in r['windows'] and 'daily' not in r for r in result)
    for original in result[:2]:
        with gzip.open(out/'full-daily'/f"{original['id']%128}.json.gz",'rt') as f:
            daily=json.load(f)[str(original['id'])]
        expected=[(date.fromisoformat(original['date'])-timedelta(days=n)).isoformat() for n in range(7,0,-1)]
        assert [r[0] for r in daily]==expected
        assert all(r[1:]==[5,25,1,1000,200,0,43200] for r in daily)
    summary=json.loads((out/'full-summary.json').read_text())
    assert summary['unknown_accuracy']==2
    assert summary['weather']=={'ok':2,'outside_available_years':1,'request_error':1}
    # Rebuilding must preserve the pilot, not replace it with the full lab.
    build(run,out)
    assert (out/'pilot-weather-lab.html').read_text()=='original pilot'
