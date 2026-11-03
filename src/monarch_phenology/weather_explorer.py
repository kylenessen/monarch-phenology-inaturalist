"""Build the expanded weather and land-cover explorer from the fixed pilot."""

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil

import httpx

from .benchmark_jev import write_json
from .weather_report import COLORS
from .weather_expand import summarize_window
from .daymet_archive import VARIABLES


def habitat_group(row: dict) -> str:
    if row.get('landcover_status') != 'ok':
        return 'Unavailable'
    code=row.get('landcover_code')
    if code in (21,22,23,24):
        return 'Developed'
    if code in (81,82):
        return 'Agriculture'
    if code in (11,12,31,41,42,43,52,71,90,95):
        return 'Natural cover'
    return 'Unavailable'

# key, display label, unit, definition
METRICS = [
    ('tmin_median','Median daily minimum','temp','Median of daily minimum temperatures in the preceding window.'),
    ('tmax_median','Median daily maximum','temp','Median of daily maximum temperatures in the preceding window.'),
    ('tmin_extreme','Coldest daily minimum','temp','Lowest daily minimum in the preceding window.'),
    ('tmax_extreme','Hottest daily maximum','temp','Highest daily maximum in the preceding window.'),
    ('tmin_mean','Mean daily minimum','temp','Arithmetic mean of daily minimum temperatures.'),
    ('tmax_mean','Mean daily maximum','temp','Arithmetic mean of daily maximum temperatures.'),
    ('tmean','Mean temperature midpoint','temp','Mean of (daily minimum + daily maximum) / 2. Not an hourly mean.'),
    ('dtr_mean','Mean daily temperature range','delta','Mean of daily maximum minus daily minimum.'),
    ('freezing_days','Days reaching freezing','days','Number of daily minima at or below 0°C.'),
    ('hot_days','Days reaching 100°F','days','Number of daily maxima at or above 37.78°C.'),
    ('precip_total','Total precipitation','mm','Total precipitation, including snow as water equivalent.'),
    ('precip_median','Median daily precipitation','mm/day','Median daily precipitation. Often zero in dry windows.'),
    ('precip_max','Wettest day','mm/day','Maximum daily precipitation.'),
    ('wet_days','Wet days','days','Number of days with at least 1 mm precipitation.'),
    ('vapor_median','Median vapor pressure','kPa','Median actual vapor pressure. This is not relative humidity or vapor pressure deficit.'),
    ('solar_mean','Mean daily solar energy','MJ/m²/day','Mean of daily shortwave radiation × day length / 1,000,000.'),
    ('radiation_median','Median daylight radiation','W/m²','Median shortwave radiation averaged over each daylight period.'),
    ('snow_median','Median snow water equivalent','kg/m²','Median water stored in snowpack. Numerically equivalent to mm of water.'),
    ('snow_max','Maximum snow water equivalent','kg/m²','Maximum water stored in snowpack.'),
    ('daylength_median','Median day length','hours','Median daylight duration.'),
    ('tmin_highest','Hottest daily minimum','temp','Highest of the daily minimum temperatures in the preceding window. The warmest daily low, not a daily maximum.'),
    ('latitude','Latitude','°N','Observation latitude.'),
    ('doy','Seasonal day','day','Month and day aligned to leap year 2000, keeping seasons aligned across years.'),
    ('year','Observation year','year','Calendar year of observation.'),
]


def density_script():
    return Path(__file__).with_name('templates').joinpath('weather_density.js').read_text()


def build(output: Path, preview: bool = False) -> Path:
    manifest=json.loads((output/'manifest.json').read_text())
    audit=json.loads((output/'audit.json').read_text()) if (output/'audit.json').exists() else {'records':{}}
    rows=[]
    missing=[]
    for original in manifest['samples']:
        p=output/'expanded'/f"{original['id']}.json"
        lc=output/'landcover'/f"{original['id']}.json"
        if not p.exists() or not lc.exists():
            missing.append(original['id'])
        row=json.loads(p.read_text()) if p.exists() else {**original,'daily':[],'windows':{},'daymet_status':'pending'}
        # Preserve already retrieved temperatures when the expanded API request fails.
        previous=output/'observations'/f"{original['id']}.json"
        if row['daymet_status']=='request_error' and previous.exists():
            cached=json.loads(previous.read_text())
            if cached.get('temperature_status')=='ok':
                row['daily']=[{**dict.fromkeys(VARIABLES), 'date':d['date'],'tmin':d['tmin_c'],'tmax':d['tmax_c']} for d in cached['daily']]
                row['windows']={str(n):summarize_window(row['daily'],date.fromisoformat(row['date']),n) for n in (7,14)}
                row.update(daymet_status='temperature_only_cached',temperature_source='Original pilot cache. Expanded request failed.')
        row.update(json.loads(lc.read_text()) if lc.exists() else {'landcover_status':'pending'})
        for n in (7,14):
            metrics=summarize_window(row.get('daily',[]),date.fromisoformat(row['date']),n)
            if 'tmin_highest' in metrics:
                row.setdefault('windows',{}).setdefault(str(n),{})['tmin_highest']=metrics['tmin_highest']
        row.update(audit['records'].get(str(row['id']),{}))
        row.setdefault('landcover_label','Unavailable')
        row['habitat_group']=habitat_group(row)
        row.setdefault('human_alive_status','not_audited')
        row.setdefault('temperature_audit_flag','not_checked')
        observed=date.fromisoformat(row['date'])
        row.update(month=observed.month,latitude=row['lat'],doy=observed.replace(year=2000).timetuple().tm_yday)
        rows.append(row)
    if missing and not preview:
        raise ValueError(f'Expanded enrichment is incomplete for {len(missing)} observations')
    assets=output/'assets'
    assets.mkdir(exist_ok=True)
    for name,url in {'plotly.min.js':'https://cdn.plot.ly/plotly-4.1.1.min.js','plotly.LICENSE':'https://raw.githubusercontent.com/plotly/plotly.js/v4.1.1/LICENSE'}.items():
        if not (assets/name).exists():
            response=httpx.get(url,timeout=90,follow_redirects=True)
            response.raise_for_status()
            (assets/name).write_bytes(response.content)
    summary={'sample_size':len(rows),'eligible_population':manifest['eligible_population'],'built_at':datetime.now(timezone.utc).isoformat(),'pending':len(missing),'weather':dict(Counter(r['daymet_status'] for r in rows)),'landcover':dict(Counter(r['landcover_status'] for r in rows)),'landcover_classes':dict(Counter(r['landcover_label'] for r in rows))}
    summary['habitat_groups']=dict(Counter(r['habitat_group'] for r in rows))
    write_json(output/'expanded-summary.json',summary)
    flat=[]
    fields=['id','date','stage','region','season','lat','lon','accuracy','sampling_weight','daymet_status','temperature_source','landcover_status','landcover_year','landcover_code','landcover_label','landcover_resolution_m','landcover_product','landcover_source','human_alive_status','temperature_audit_flag','era5_tmin_14d_c','era5_tmax_14d_c']
    fields.append('habitat_group')
    for row in rows:
        record={k:row.get(k) for k in fields}
        for window in ('7','14'):
            for k in [m[0] for m in METRICS[:-3]]:
                record[f'{k}_{window}d']=row.get('windows',{}).get(window,{}).get(k)
        flat.append(record)
    with (output/'expanded-observations.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,list(flat[0]))
        writer.writeheader();writer.writerows(flat)
    with (output/'expanded-daily.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,['observation_id','date','tmin','tmax','prcp','vp','srad','swe','dayl'])
        writer.writeheader()
        for row in rows:
            writer.writerows({'observation_id':row['id'],**d} for d in row['daily'])
    payload={'rows':rows,'summary':summary,'metrics':[{'key':k,'label':label,'unit':unit,'definition':definition} for k,label,unit,definition in METRICS],'colors':COLORS}
    encoded=json.dumps(payload,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    target=output/'index.html'
    if target.exists() and not (output/'original-weather-report.html').exists():
        shutil.copyfile(target,output/'original-weather-report.html')
    template=Path(__file__).with_name('templates')/'weather_explorer.html'
    target.write_text(template.read_text().replace('__EXPLORER_DATA__',encoded).replace('__DENSITY_CODE__',density_script()))
    return target


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('runs/weather-pilot'))
    p.add_argument('--preview',action='store_true')
    args=p.parse_args()
    print(build(args.output,args.preview))


if __name__=='__main__':
    main()
