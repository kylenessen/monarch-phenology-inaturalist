"""Sample year-matched USGS Annual NLCD categories at pilot coordinates."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
import time
import xml.etree.ElementTree as ET

import httpx
from pyproj import Transformer

from .benchmark_jev import write_json

SERVICE = 'https://dmsdata.cr.usgs.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data/wms'
LAYER = 'Land-Cover-Native_conus_year_data'
CLASSES = {11:'Open water',12:'Perennial ice/snow',21:'Developed, open space',22:'Developed, low intensity',23:'Developed, medium intensity',24:'Developed, high intensity',31:'Barren land',41:'Deciduous forest',42:'Evergreen forest',43:'Mixed forest',52:'Shrub/scrub',71:'Grassland/herbaceous',81:'Pasture/hay',82:'Cultivated crops',90:'Woody wetlands',95:'Emergent herbaceous wetlands'}


def category(payload: dict) -> int | None:
    features = payload.get('features')
    if not isinstance(features, list):
        raise ValueError('USGS did not return a feature collection')
    if not features:
        return None
    props = features[0]['properties']
    if 'PALETTE_INDEX' not in props:
        raise ValueError('USGS response does not contain the native category')
    value = props['PALETTE_INDEX']
    if value is None or value in (0,250,255):
        return None
    if value not in CLASSES:
        raise ValueError(f'Unknown NLCD class {value}')
    return int(value)


class Landcover:
    def __init__(self, output: Path):
        self.folder=output/'landcover'
        self.folder.mkdir(exist_ok=True)
        self.cache=self.folder/'cache'
        self.cache.mkdir(exist_ok=True)
        self.client=httpx.Client(timeout=90,follow_redirects=True,headers={'User-Agent':'monarch-phenology research pilot'})
        self.lock=Lock()
        self.next_request=0
        self.project=Transformer.from_crs(4326,5070,always_xy=True)
        path=self.folder/'capabilities.xml'
        if not path.exists():
            r=self.client.get(SERVICE,params={'service':'WMS','request':'GetCapabilities'})
            r.raise_for_status()
            path.write_text(r.text)
        root=ET.fromstring(path.read_text())
        dim=next(e for e in root.iter() if e.tag.endswith('Dimension') and e.attrib.get('name')=='time')
        self.years={int(s[:4]) for s in dim.text.split(',')}

    def fetch(self, row: dict) -> dict:
        year=int(row['date'][:4])
        result={'id':row['id'],'landcover_year':year,'landcover_resolution_m':30,'landcover_source':SERVICE,'landcover_product':'USGS Annual NLCD Collection 1.2','landcover_retrieved_at':datetime.now(timezone.utc).isoformat()}
        if year not in self.years:
            return {**result,'landcover_status':'year_unavailable'}
        x,y=self.project.transform(row['lon'],row['lat'])
        params={'service':'WMS','version':'1.1.1','request':'GetFeatureInfo','layers':LAYER,'query_layers':LAYER,'styles':'','srs':'EPSG:5070','bbox':f'{x-45},{y-45},{x+45},{y+45}','width':3,'height':3,'x':1,'y':1,'format':'image/png','info_format':'application/json','time':f'{year}-01-01','feature_count':1}
        result['landcover_request']=params
        key=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()
        path=self.cache/f'{key}.json'
        try:
            if path.exists():
                payload=json.loads(path.read_text())
            else:
                for attempt in range(4):
                    with self.lock:
                        time.sleep(max(0,self.next_request-time.monotonic()))
                        self.next_request=time.monotonic()+0.65
                    try:
                        response=self.client.get(SERVICE,params=params)
                        if response.status_code==429:
                            try: delay=max(5,float(response.headers.get('Retry-After','30')))
                            except ValueError: delay=30
                            with self.lock:
                                self.next_request=max(self.next_request,time.monotonic()+delay)
                        response.raise_for_status()
                        payload=response.json()
                        category(payload)  # Validate before caching, including explicit NoData.
                        write_json(path,payload)
                        break
                    except (httpx.HTTPError,ValueError):
                        if attempt==3: raise
                        time.sleep(2**(attempt+1))
            value=category(payload)
            result.update(landcover_code=value,landcover_label=CLASSES.get(value,'Unavailable'),landcover_status='ok' if value is not None else 'outside_coverage_or_nodata')
        except (httpx.HTTPError,ValueError,KeyError) as exc:
            result.update(landcover_status='request_error',landcover_error=str(exc)[:400])
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('runs/weather-pilot'))
    parser.add_argument('--limit',type=int)
    parser.add_argument('--retry-errors',action='store_true')
    args=parser.parse_args()
    worker=Landcover(args.output)
    manifest=json.loads((args.output/'manifest.json').read_text())
    pending=[]
    for row in manifest['samples']:
        path=worker.folder/f"{row['id']}.json"
        if not path.exists() or (args.retry_errors and json.loads(path.read_text())['landcover_status']=='request_error'):
            pending.append(row)
    counts=Counter()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(worker.fetch,row) for row in pending[:args.limit]]
            for i,f in enumerate(as_completed(futures),1):
                result=f.result()
                write_json(worker.folder/f"{result['id']}.json",result)
                counts[result['landcover_status']]+=1
                if i%25==0: print(f'{i}/{len(futures)} {dict(counts)}',flush=True)
    finally:
        worker.client.close()
    print(dict(counts),flush=True)


if __name__=='__main__':
    main()
