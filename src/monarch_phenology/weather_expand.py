"""Expand the fixed weather pilot with all Daymet variables. No AET calls."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
from pathlib import Path
from statistics import mean, median

import httpx

from .benchmark_jev import write_json
from .daymet_archive import VARIABLES, parse_daily
from .weather_pilot import DAYMET, Fetcher, preceding_days


def summarize_window(daily: list[dict], observed: date, days: int = 14) -> dict:
    needed = {d.isoformat() for d in preceding_days(observed, days)}
    rows = [r for r in daily if r['date'] in needed]
    result = {"days_found": len(rows), "days_required": days}
    valid = {}
    for key in VARIABLES:
        vals = [r[key] for r in rows if r.get(key) is not None and (-100 < r[key] < 70 if key in ('tmin', 'tmax') else r[key] >= 0)]
        if len(vals) == days:
            valid[key] = vals
    if 'tmin' in valid and 'tmax' in valid and all(r['tmin'] <= r['tmax'] for r in rows):
        low, high = valid['tmin'], valid['tmax']
        result.update(tmin_extreme=min(low), tmax_extreme=max(high), tmin_median=median(low), tmax_median=median(high), tmin_mean=mean(low), tmax_mean=mean(high), tmean=mean([(a+b)/2 for a,b in zip(low,high)]), dtr_mean=mean([b-a for a,b in zip(low,high)]), freezing_days=sum(v<=0 for v in low), hot_days=sum(v >= (100-32)/1.8 for v in high))
    for key, prefix in [('prcp','precip'),('vp','vapor'),('srad','radiation'),('swe','snow'),('dayl','daylength')]:
        if key not in valid:
            continue
        factor = 1/1000 if key == 'vp' else 1/3600 if key == 'dayl' else 1
        vals = [v * factor for v in valid[key]]
        result.update({prefix+'_median': median(vals), prefix+'_mean': mean(vals), prefix+'_max': max(vals)})
    if 'prcp' in valid:
        result.update(precip_total=sum(valid['prcp']), wet_days=sum(v >= 1 for v in valid['prcp']))
    if 'srad' in valid and 'dayl' in valid:
        result['solar_mean'] = mean([r['srad'] * r['dayl'] / 1e6 for r in rows])
    result['complete_variables'] = len(valid)
    return result


def expand_one(row: dict, fetcher: Fetcher) -> dict:
    observed = date.fromisoformat(row['date'])
    days = preceding_days(observed)
    params = {'lat':row['lat'], 'lon':row['lon'], 'vars':','.join(VARIABLES), 'start':days[0].isoformat(), 'end':days[-1].isoformat()}
    result = {**row, 'daymet_request': params}
    try:
        result.update(parse_daily(fetcher.get('daymet', DAYMET, params)))
        result['windows'] = {str(n): summarize_window(result['daily'], observed, n) for n in (7,14)}
        result['daymet_status'] = 'ok' if result['windows']['14']['complete_variables'] == 7 else 'incomplete_window'
    except (httpx.HTTPError, ValueError, KeyError, StopIteration) as exc:
        result.update(daymet_status='request_error', daymet_error=str(exc)[:400], daily=[], windows={})
        if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code == 400 and 'Tile was not found' in exc.response.text:
            result['daymet_status'] = 'outside_daymet_coverage'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('runs/weather-pilot'))
    parser.add_argument('--limit',type=int)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--retry-errors',action='store_true')
    args=parser.parse_args()
    folder=args.output/'expanded'
    folder.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((args.output/'manifest.json').read_text())
    pending=[]
    for row in manifest['samples']:
        p=folder/f"{row['id']}.json"
        if not p.exists() or (args.retry_errors and json.loads(p.read_text())['daymet_status']=='request_error'):
            pending.append(row)
    fetcher=Fetcher(args.output)
    counts=Counter()
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(expand_one,row,fetcher) for row in pending[:args.limit]]
            for i,future in enumerate(as_completed(futures),1):
                result=future.result()
                write_json(folder/f"{result['id']}.json", result)
                counts[result['daymet_status']]+=1
                if i%25==0:
                    print(f'{i}/{len(futures)} {dict(counts)}',flush=True)
    finally:
        fetcher.client.close()
    print(dict(counts),flush=True)


if __name__ == '__main__':
    main()
