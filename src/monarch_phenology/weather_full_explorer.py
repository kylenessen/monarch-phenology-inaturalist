"""Publish the completed seven-day archive in the existing local weather lab."""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import gzip
import json
from pathlib import Path
import shutil
import sqlite3

from .daymet_archive import VARIABLES
from .weather_explorer import METRICS, habitat_group
from .weather_pilot import Regions, SEASONS
from .weather_report import COLORS


def compressed_json(path, value):
    temporary=path.with_suffix('.tmp')
    with gzip.open(temporary,'wt',encoding='utf-8') as handle:
        json.dump(value,handle,separators=(',',':'),allow_nan=False)
    temporary.replace(path)


def build(source: Path, output: Path) -> Path:
    output.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(f'{(source/"observations.sqlite").resolve().as_uri()}?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    db.execute('BEGIN')
    try:
        pending=db.execute("SELECT count(*) FROM requests WHERE status IN ('pending','running')").fetchone()[0]
        if pending:
            raise ValueError(f'The full run still has {pending} pending or running lookups')
        exported=db.execute("SELECT value FROM metadata WHERE key='exported_at'").fetchone()
        latest=db.execute('SELECT max(retrieved_at) FROM requests').fetchone()[0]
        if not exported or (latest and exported[0]<latest):
            raise ValueError('Wait for the final CSV exports before publishing the full lab')
        geography=Regions(output)
        rows=[]
        sql='''SELECT o.*, COALESCE(wr.status,o.weather_eligibility) AS weather_status,
            COALESCE(lr.status,o.landcover_eligibility) AS landcover_status,
            l.year AS landcover_year,l.code AS landcover_code,l.label AS landcover_label,w.metrics
            FROM observations o LEFT JOIN requests wr ON wr.key=o.weather_key
            LEFT JOIN requests lr ON lr.key=o.landcover_key
            LEFT JOIN landcover_results l ON l.key=o.landcover_key
            LEFT JOIN weather_summaries w ON w.key=o.weather_key ORDER BY o.id'''
        for record in db.execute(sql):
            original=json.loads(record['payload'])
            observed=date.fromisoformat(record['observed_on'])
            row={'id':record['id'],'date':record['observed_on'],'year':observed.year,
                 'stage':record['stage'],'lat':record['latitude'],'lon':record['longitude'],
                 'latitude':record['latitude'],'accuracy':record['accuracy_m'],
                 'region':geography.classify(record['latitude'],record['longitude']),
                 'month':observed.month,'doy':observed.replace(year=2000).timetuple().tm_yday,
                 'season':SEASONS[observed.month%12//3],'sampling_weight':1,
                 'daymet_status':record['weather_status'],'landcover_status':record['landcover_status'],
                 'landcover_year':record['landcover_year'],'landcover_code':record['landcover_code'],
                 'landcover_label':record['landcover_label'] or 'Unavailable',
                 'human_alive_status':original.get('human_alive_status','unannotated'),
                 'temperature_audit_flag':'not_checked',
                 'windows':{'7':json.loads(record['metrics'])} if record['metrics'] else {}}
            row['habitat_group']=habitat_group(row)
            rows.append(row)
        summary={'dataset':'full','sample_size':len(rows),'eligible_population':len(rows),
                 'built_at':datetime.now(timezone.utc).isoformat(),'pending':0,
                 'unknown_accuracy':sum(r['accuracy'] is None for r in rows),
                 'weather':dict(Counter(r['daymet_status'] for r in rows)),
                 'landcover':dict(Counter(r['landcover_status'] for r in rows)),
                 'habitat_groups':dict(Counter(r['habitat_group'] for r in rows))}
        # Keep daily series out of the initial page payload. Fetch one small shard on inspection.
        buckets=[defaultdict(list) for _ in range(128)]
        daily_sql='''SELECT o.id,d.date,d.tmin,d.tmax,d.prcp,d.vp,d.srad,d.swe,d.dayl
            FROM observations o JOIN weather_summaries w ON w.key=o.weather_key
            JOIN weather_daily d ON d.point_key=o.point_key
            AND d.date>=date(o.observed_on,'-7 days') AND d.date<o.observed_on
            ORDER BY o.id,d.date'''
        for r in db.execute(daily_sql):
            buckets[r['id']%128][str(r['id'])].append(list(r)[1:])
    finally:
        db.close()
    folder=output/'full-daily'
    folder.mkdir(exist_ok=True)
    for number,bucket in enumerate(buckets):
        compressed_json(folder/f'{number}.json.gz',bucket)
    compressed_json(output/'full-observations.json.gz',rows)
    (output/'full-summary.json').write_text(json.dumps(summary,indent=2))
    for filename in ('observations.csv.gz','weather-daily.csv.gz'):
        shutil.copyfile(source/filename,output/('full-'+filename))
    payload={'rows_url':'full-observations.json.gz','daily_url':'full-daily/',
             'daily_fields':['date',*VARIABLES],'summary':summary,'colors':COLORS,
             'metrics':[{'key':k,'label':label,'unit':unit,'definition':definition} for k,label,unit,definition in METRICS]}
    target=output/'index.html'
    pilot=output/'pilot-weather-lab.html'
    if target.exists() and not pilot.exists():
        shutil.copyfile(target,pilot)
    template=Path(__file__).with_name('templates')/'weather_explorer.html'
    encoded=json.dumps(payload,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    temporary=output/'index.tmp'
    html=template.read_text().replace('__EXPLORER_DATA__',encoded)
    html=html.replace('600 observations · seven daily weather variables · annual land cover',
                      f'{len(rows):,} observations · seven-day weather · annual land cover')
    temporary.write_text(html)
    temporary.replace(target)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('runs/weather-full-7d'))
    parser.add_argument('--output',type=Path,default=Path('runs/weather-pilot'))
    args=parser.parse_args()
    print(build(args.source,args.output))


if __name__=='__main__':
    main()
