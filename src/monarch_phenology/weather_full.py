"""Resumable seven-day point enrichment of the complete annotated atlas."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import csv
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import fcntl
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Lock
import time
import xml.etree.ElementTree as ET

import httpx
from pyproj import Transformer

from .benchmark_jev import write_json
from .daymet_archive import VARIABLES, parse_daily
from .landcover_pilot import SERVICE, LAYER, CLASSES, category
from .phenology_map import normalize_observation
from .weather_audit import life_status
from .weather_expand import summarize_window
from .weather_explorer import habitat_group, METRICS
from .weather_pilot import DAYMET


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def key_for(service, params):
    return hashlib.sha256(encoded([service, params]).encode()).hexdigest()


def point_key(lat, lon):
    return hashlib.sha256(encoded([lat, lon]).encode()).hexdigest()[:24]


def weather_params(row):
    day = date.fromisoformat(row['date'])
    return {'lat': row['lat'], 'lon': row['lon'], 'vars': ','.join(VARIABLES), 'start': (day-timedelta(days=7)).isoformat(), 'end': (day-timedelta(days=1)).isoformat()}


def cover_params(row, project):
    x, y = project.transform(row['lon'], row['lat'])
    return {'service':'WMS','version':'1.1.1','request':'GetFeatureInfo','layers':LAYER,'query_layers':LAYER,'styles':'','srs':'EPSG:5070','bbox':f'{x-45},{y-45},{x+45},{y+45}','width':3,'height':3,'x':1,'y':1,'format':'image/png','info_format':'application/json','time':row['date'][:4]+'-01-01','feature_count':1}


def connect(output):
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(output/'observations.sqlite')
    db.row_factory = sqlite3.Row
    db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(
            key TEXT PRIMARY KEY, service TEXT NOT NULL, params TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            retrieved_at TEXT, response_code INTEGER, response_gzip BLOB, error TEXT, provenance TEXT);
        CREATE INDEX IF NOT EXISTS request_status ON requests(service,status);
        CREATE TABLE IF NOT EXISTS observations(
            id INTEGER PRIMARY KEY, observed_on TEXT NOT NULL, stage TEXT NOT NULL,
            latitude REAL NOT NULL, longitude REAL NOT NULL, accuracy_m REAL,
            point_key TEXT NOT NULL, weather_key TEXT REFERENCES requests(key),
            landcover_key TEXT REFERENCES requests(key), weather_eligibility TEXT,
            landcover_eligibility TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS excluded_observations(id INTEGER PRIMARY KEY, reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS weather_daily(
            point_key TEXT NOT NULL, date TEXT NOT NULL, tmin REAL, tmax REAL, prcp REAL,
            vp REAL, srad REAL, swe REAL, dayl REAL, source_key TEXT REFERENCES requests(key),
            PRIMARY KEY(point_key,date)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS weather_summaries(key TEXT PRIMARY KEY REFERENCES requests(key), metrics TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS landcover_results(key TEXT PRIMARY KEY REFERENCES requests(key), year INTEGER, code INTEGER, label TEXT, habitat_group TEXT);
    ''')
    metrics=', '.join(f"json_extract(w.metrics,'$.{m[0]}') AS {m[0]}_7d" for m in METRICS[:20])
    db.execute('CREATE VIEW IF NOT EXISTS enriched_observations AS SELECT o.id, o.observed_on, o.stage, o.latitude, o.longitude, o.accuracy_m, o.point_key, '
               "json_extract(o.payload,'$.human_alive_status') AS human_alive_status, "
               'COALESCE(wr.status,o.weather_eligibility) AS weather_status, COALESCE(lr.status,o.landcover_eligibility) AS landcover_status, '
               'l.year AS landcover_year,l.code AS landcover_code,l.label AS landcover_label,l.habitat_group, '+metrics+
               ' FROM observations o LEFT JOIN requests wr ON wr.key=o.weather_key LEFT JOIN requests lr ON lr.key=o.landcover_key '
               'LEFT JOIN weather_summaries w ON w.key=o.weather_key LEFT JOIN landcover_results l ON l.key=o.landcover_key')
    db.commit()
    return db


def available_land_years(output, pilot):
    path=output/'landcover-capabilities.xml'
    if not path.exists():
        cached=pilot/'landcover'/'capabilities.xml'
        if cached.exists():
            path.write_bytes(cached.read_bytes())
        else:
            r=httpx.get(SERVICE,params={'service':'WMS','request':'GetCapabilities'},timeout=90)
            r.raise_for_status();path.write_text(r.text)
    root=ET.fromstring(path.read_text())
    dimension=next(e for e in root.iter() if e.tag.endswith('Dimension') and e.attrib.get('name')=='time')
    return sorted(int(s[:4]) for s in dimension.text.split(','))


def plan(db, source, output, pilot, last_year=2025):
    source_bytes=(source/'source.json').read_bytes()
    meta=json.loads(source_bytes)
    if not meta['complete']:
        raise ValueError('Source atlas must be complete')
    config={'version':1,'source':str(source.resolve()),'source_sha256':hashlib.sha256(source_bytes).hexdigest(),'window_days':7,'daymet_last_year':last_year,'maximum_accuracy_m':1000,'include_unknown_accuracy':True,'variables':list(VARIABLES),'landcover_years':available_land_years(output,pilot),'daymet_url':DAYMET,'landcover_url':SERVICE}
    old=db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
    if old:
        if json.loads(old[0])!=config:
            raise ValueError('Run configuration changed. Use a new output directory.')
        return config
    project=Transformer.from_crs(4326,5070,always_xy=True)
    cutoff=date.fromisoformat(meta['params']['d2'])
    with db:
        for page in sorted((source/'pages').glob('*.json')):
            for raw in json.loads(page.read_text())['results']:
                row, reason=normalize_observation(raw,cutoff)
                if row and row['accuracy'] is not None and row['accuracy']>1000:
                    reason='accuracy_over_1km';row=None
                if not row:
                    db.execute('INSERT INTO excluded_observations VALUES(?,?)',(raw['id'],reason))
                    continue
                row['human_alive_status']=life_status(raw)
                p=weather_params(row)
                weather_key=None;cover_key=None
                weather_eligibility='outside_available_years'
                land_eligibility='year_unavailable'
                if p['start']>='1980-01-01' and p['end']<=f'{last_year}-12-31':
                    weather_key=key_for('daymet',p);weather_eligibility='eligible'
                    db.execute('INSERT OR IGNORE INTO requests(key,service,params) VALUES(?,?,?)',(weather_key,'daymet',encoded(p)))
                if row['year'] in config['landcover_years']:
                    p=cover_params(row,project);cover_key=key_for('landcover',p);land_eligibility='eligible'
                    db.execute('INSERT OR IGNORE INTO requests(key,service,params) VALUES(?,?,?)',(cover_key,'landcover',encoded(p)))
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(row['id'],row['date'],row['stage'],row['lat'],row['lon'],row['accuracy'],point_key(row['lat'],row['lon']),weather_key,cover_key,weather_eligibility,land_eligibility,encoded(row)))
        db.execute('INSERT INTO metadata VALUES(?,?)',('config',encoded(config)))
        db.execute('INSERT INTO metadata VALUES(?,?)',('created_at',now()))
        db.execute('INSERT INTO metadata VALUES(?,?)',('units',encoded({'tmin':'deg C','tmax':'deg C','prcp':'mm/day','vp':'Pa','srad':'W/m2 daylight average','swe':'kg/m2','dayl':'s/day'})))
    write_json(output/'manifest.json',config)
    return config


def decode_result(service, params, body):
    if service=='daymet':
        parsed=parse_daily(body)
        daily=[d for d in parsed['daily'] if params['start']<=d['date']<=params['end']]
        metrics=summarize_window(daily,date.fromisoformat(params['end'])+timedelta(days=1),7)
        return {'status':'ok' if metrics['complete_variables']==7 and 'tmin_median' in metrics else 'incomplete_window','daily':daily,'metrics':metrics}
    code=category(json.loads(body))
    status='ok' if code is not None else 'outside_coverage_or_nodata'
    return {'status':status,'code':code,'label':CLASSES.get(code,'Unavailable'),'habitat':habitat_group({'landcover_status':status,'landcover_code':code})}


def save_result(db, job, result):
    params=json.loads(job['params'])
    with db:
        db.execute('UPDATE requests SET status=?,attempts=attempts+?,retrieved_at=?,response_code=?,response_gzip=?,error=?,provenance=? WHERE key=?',
                   (result['status'],result.get('attempts',0),now(),result.get('response_code'),gzip.compress(result['body'].encode()) if result.get('body') is not None else None,result.get('error'),result.get('provenance','network'),job['key']))
        if job['service']=='daymet' and 'daily' in result:
            pk=point_key(params['lat'],params['lon'])
            for d in result['daily']:
                db.execute('INSERT OR IGNORE INTO weather_daily VALUES(?,?,?,?,?,?,?,?,?,?)',(pk,d['date'],*[d.get(k) for k in VARIABLES],job['key']))
            db.execute('INSERT OR REPLACE INTO weather_summaries VALUES(?,?)',(job['key'],encoded(result['metrics'])))
        elif job['service']=='landcover' and 'code' in result:
            db.execute('INSERT OR REPLACE INTO landcover_results VALUES(?,?,?,?,?)',(job['key'],int(params['time'][:4]),result['code'],result['label'],result['habitat']))


def seed_pilot(db,pilot):
    if db.execute("SELECT 1 FROM metadata WHERE key='pilot_seeded'").fetchone():
        return
    seeded=Counter()
    for observation in db.execute('SELECT id,weather_key,landcover_key FROM observations').fetchall():
        for service, folder, column in [('daymet','expanded','weather_key'),('landcover','landcover','landcover_key')]:
            path=pilot/folder/f"{observation['id']}.json"
            if not observation[column] or not path.exists():
                continue
            job=db.execute('SELECT * FROM requests WHERE key=?',(observation[column],)).fetchone()
            if job['status']!='pending':
                continue
            old=json.loads(path.read_text())
            if service=='daymet' and old.get('daily'):
                old_params=old['daymet_request']
                digest=hashlib.sha256(json.dumps([DAYMET,old_params],sort_keys=True).encode()).hexdigest()
                raw=pilot/'cache'/f'daymet-{digest}.txt'
            elif service=='landcover' and old.get('landcover_status') in ('ok','outside_coverage_or_nodata'):
                old_params=old['landcover_request']
                if old_params!=json.loads(job['params']):
                    continue
                digest=hashlib.sha256(json.dumps(old_params,sort_keys=True).encode()).hexdigest()
                raw=pilot/'landcover'/'cache'/f'{digest}.json'
            else:
                continue
            if raw.exists():
                body=raw.read_text()
                result=decode_result(service,json.loads(job['params']),body)
                result.update(body=body,response_code=200,provenance=encoded({'kind':'pilot_cache','path':str(raw.resolve()),'original_params':old_params}))
                save_result(db,job,result);seeded[service]+=1
    with db:
        db.execute('INSERT INTO metadata VALUES(?,?)',('pilot_seeded',encoded(dict(seeded))))
    print('Reused pilot requests',dict(seeded),flush=True)


class Transport:
    def __init__(self, interval=1.0):
        self.interval=interval
        self.locks={s:Lock() for s in ('daymet','landcover')}
        self.next={s:0.0 for s in self.locks}
        self.effective={s:interval for s in self.locks}
        self.codes={s:Counter() for s in self.locks}
        self.successes={s:0 for s in self.locks}
        self.failures={s:0 for s in self.locks}
        self.client=httpx.Client(timeout=90,follow_redirects=True,headers={'User-Agent':'monarch-phenology/0.1 (cached research point extraction)'})

    def wait_turn(self, service):
        while True:
            with self.locks[service]:
                delay=self.next[service]-time.monotonic()
                if delay<=0:
                    self.next[service]=time.monotonic()+self.effective[service]
                    return
            # Release the lock while sleeping so responses can extend a shared cooldown.
            time.sleep(min(delay,1.0))

    def record_response(self, service, code, retry_after=None):
        delay=0
        if code in (429,503):
            try:delay=float(retry_after or '30')
            except ValueError:
                try:delay=(parsedate_to_datetime(retry_after)-datetime.now(timezone.utc)).total_seconds()
                except (TypeError,ValueError):delay=30
        with self.locks[service]:
            self.codes[service][str(code)]+=1
            self.failures[service]=self.failures[service]+1 if code>=500 else 0
            if code in (429,503) or self.failures[service]>=3:
                self.effective[service]=min(10,max(self.interval,self.effective[service]*2))
                self.next[service]=max(self.next[service],time.monotonic()+max(5,delay))
                self.successes[service]=0
                self.failures[service]=0
            elif code==200:
                self.successes[service]+=1
                if self.successes[service]>=100:
                    self.effective[service]=max(self.interval,self.effective[service]*0.9)
                    self.successes[service]=0

    def snapshot(self):
        result={}
        for service in self.locks:
            with self.locks[service]:
                result[service]={'target_interval_seconds':self.interval,'effective_interval_seconds':self.effective[service],'http_responses':dict(self.codes[service]),'cooldown_seconds':max(0,self.next[service]-time.monotonic())}
        return result

    def restore_backoff(self, checkpoint):
        """A restart must not bypass a provider's outstanding cooldown."""
        updated=checkpoint.get('updated_at')
        if not updated:
            return
        age=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(updated)).total_seconds())
        for service,previous in checkpoint.get('transport',{}).items():
            if service not in self.locks:
                continue
            old_target=previous.get('target_interval_seconds',self.interval)
            old_effective=previous.get('effective_interval_seconds',old_target)
            # Preserve adaptive slowdowns, but do not carry over an old, slower target.
            if old_effective>old_target:
                self.effective[service]=max(self.interval,old_effective)
                remaining=max(0,previous.get('cooldown_seconds',0)-age)
                self.next[service]=time.monotonic()+remaining

    def fetch(self, job):
        service=job['service'];params=json.loads(job['params']);body=None;code=None
        for attempt in range(4):
            self.wait_turn(service)
            try:
                r=self.client.get(DAYMET if service=='daymet' else SERVICE,params=params)
                body=r.text;code=r.status_code
                self.record_response(service,code,r.headers.get('Retry-After'))
                if service=='daymet' and code==400 and 'Tile was not found' in body:
                    return {'status':'outside_daymet_coverage','body':body,'response_code':code,'attempts':attempt+1}
                r.raise_for_status()
                result=decode_result(service,params,body)
                return {**result,'body':body,'response_code':code,'attempts':attempt+1}
            except (httpx.HTTPError,ValueError,KeyError,StopIteration) as exc:
                if (isinstance(exc,httpx.HTTPStatusError) and 400<=code<500 and code!=429) or attempt==3:
                    return {'status':'request_error','error':str(exc)[:1500],'body':body[:16000] if body else None,'response_code':code,'attempts':attempt+1}
                time.sleep(2**(attempt+1))


def status(db,output,state,transport=None,started=None,completed=None):
    jobs={}
    for row in db.execute('SELECT service,status,count(*) AS n FROM requests GROUP BY service,status'):
        jobs.setdefault(row['service'],{})[row['status']]=row['n']
    obs={}
    for service,column,elig in [('daymet','weather_key','weather_eligibility'),('landcover','landcover_key','landcover_eligibility')]:
        obs[service]={r[0]:r[1] for r in db.execute(f'SELECT COALESCE(r.status,o.{elig}),count(*) FROM observations o LEFT JOIN requests r ON r.key=o.{column} GROUP BY 1')}
    result={'updated_at':now(),'state':state,'observations':db.execute('SELECT count(*) FROM observations').fetchone()[0],'unknown_accuracy':db.execute('SELECT count(*) FROM observations WHERE accuracy_m IS NULL').fetchone()[0],'excluded':dict(db.execute('SELECT reason,count(*) FROM excluded_observations GROUP BY reason')),'jobs':jobs,'observation_coverage':obs,'daily_rows':db.execute('SELECT count(*) FROM weather_daily').fetchone()[0],'disk_bytes':sum(p.stat().st_size for p in output.glob('observations.sqlite*'))}
    result['habitat_counts']=dict(db.execute('SELECT l.habitat_group,count(*) FROM observations o JOIN landcover_results l ON l.key=o.landcover_key GROUP BY l.habitat_group'))
    exported=db.execute("SELECT value FROM metadata WHERE key='exported_at'").fetchone()
    result['csv_snapshot_at']=exported[0] if exported else None
    if transport:
        elapsed=max(0.001,time.monotonic()-started)
        result['transport']=transport.snapshot()
        result['run_performance']={'elapsed_seconds':elapsed,'completed_jobs':dict(completed),'jobs_per_second':{s:completed[s]/elapsed for s in ('daymet','landcover')}}
    write_json(output/'status.json',result)
    return result


def export(db,output):
    for name,sql in [('observations.csv','SELECT * FROM enriched_observations'),('weather-daily.csv','SELECT * FROM weather_daily')]:
        path=output/(name+'.gz')
        temp=path.with_suffix('.tmp')
        cursor=db.execute(sql)
        with gzip.open(temp,'wt',newline='') as handle:
            writer=csv.writer(handle);writer.writerow([c[0] for c in cursor.description]);writer.writerows(cursor)
        temp.replace(path)
    with db:
        db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('exported_at',now()))


def run(db,output,workers,interval,limit=None):
    with db:
        db.execute("UPDATE requests SET status='pending' WHERE status='running'")
    transport=Transport(interval)
    checkpoint=output/'status.json'
    if checkpoint.exists():
        transport.restore_backoff(json.loads(checkpoint.read_text()))
    started=time.monotonic()
    completed_by_service=Counter()
    with db:
        db.execute('INSERT INTO metadata VALUES(?,?)',('runtime:'+now(),encoded({'workers_per_provider':workers,'target_interval_seconds':interval,'pipeline_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})))
    queues={s:iter(db.execute("SELECT * FROM requests WHERE status='pending' AND service=? ORDER BY key",(s,)).fetchall()) for s in ('daymet','landcover')}
    # Separate pools prevent a slow provider from occupying every worker.
    pools={s:ThreadPoolExecutor(max_workers=workers) for s in queues}
    active={};submitted=0;completed=0;last_status=time.monotonic()
    status(db,output,'running',transport,started,completed_by_service)
    def submit(service):
        nonlocal submitted
        if limit is not None and submitted>=limit:return
        job=next(queues[service],None)
        if job is None:return
        db.execute("UPDATE requests SET status='running' WHERE key=?",(job['key'],));db.commit()
        active[pools[service].submit(transport.fetch,dict(job))]=job;submitted+=1
    try:
        for _ in range(workers):
            for service in pools:submit(service)
        while active:
            finished,_=wait(active,timeout=20,return_when=FIRST_COMPLETED)
            for future in finished:
                job=active.pop(future);save_result(db,job,future.result());completed+=1;completed_by_service[job['service']]+=1;submit(job['service'])
            if time.monotonic()-last_status>25 or not active:
                info=status(db,output,'running',transport,started,completed_by_service);print(encoded({'completed_this_process':completed,**info}),flush=True);last_status=time.monotonic()
    finally:
        for pool in pools.values():pool.shutdown(wait=True)
        transport.client.close()
    pending=db.execute("SELECT count(*) FROM requests WHERE status IN ('pending','running')").fetchone()[0]
    errors=db.execute("SELECT count(*) FROM requests WHERE status='request_error'").fetchone()[0]
    export(db,output)
    state='partial' if pending else 'finished_with_errors' if errors else 'complete'
    info=status(db,output,state,transport,started,completed_by_service)
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    print(encoded(info),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=Path('runs/phenology-map'))
    p.add_argument('--pilot',type=Path,default=Path('runs/weather-pilot'))
    p.add_argument('--output',type=Path,default=Path('runs/weather-full-7d'))
    p.add_argument('--plan-only',action='store_true')
    p.add_argument('--export-only',action='store_true')
    p.add_argument('--retry-errors',action='store_true')
    p.add_argument('--limit',type=int)
    p.add_argument('--workers',type=int,default=4,help='Concurrent workers per provider')
    p.add_argument('--interval',type=float,default=1.0,help='Minimum seconds between requests per provider')
    args=p.parse_args()
    if args.workers<1 or args.interval<0.125 or (args.limit is not None and args.limit<1):p.error('Invalid worker count, pacing or limit')
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'run.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('A downloader already holds this run directory')
        db=connect(args.output)
        try:
            plan(db,args.source,args.output,args.pilot)
            (args.output/'index.html').write_text(Path(__file__).with_name('templates').joinpath('weather_full_status.html').read_text())
            with db:
                db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)',('products',encoded({'daymet':'Daymet V4 R1, daily, 1 km','landcover':'USGS Annual NLCD Collection 1.2, annual, 30 m, contiguous U.S.','window':'D-7 through D-1','daily_units':'See metadata.units','summary_temperature_units':'degrees Celsius','landcover_groups':'Developed 21-24. Agriculture 81-82. Other recognized classes natural cover. NoData unavailable.'})))
                db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)',('pipeline_sha256',hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
            seed_pilot(db,args.pilot)
            if args.export_only:export(db,args.output);return
            if args.retry_errors:
                with db:db.execute("UPDATE requests SET status='pending' WHERE status='request_error'")
            if args.plan_only:print(encoded(status(db,args.output,'planned')),flush=True);return
            run(db,args.output,args.workers,args.interval,args.limit)
        except BaseException:
            status(db,args.output,'interrupted')
            raise
        finally:db.close()


if __name__=='__main__':
    main()
