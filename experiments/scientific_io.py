"""Shared file contract, with no solver-specific assumptions in Unreal."""
import csv
import gzip
import json
from pathlib import Path


def save_json_gz(path,data):
    with Path(path).open('wb') as raw:
        with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as f:
            f.write(json.dumps(data,separators=(',',':'),allow_nan=False).encode())


def load_json_gz(path):
    with gzip.open(path,'rt') as f:return json.load(f)


def export_event_csv(path,spec,events):
    vm={v['vehicle_id']:v for v in spec['vehicles']}
    names=['vehicle_id','task_id','event_type','start','end','deadline','energy_kwh','grid_kwh','path_points',
           'station_id','initial_kwh','battery_kwh','terminal_kwh','efficiency']
    with Path(path).open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,names);writer.writeheader()
        for e in sorted(events,key=lambda e:(e['vehicle_id'],e['start'])):
            v=vm[e['vehicle_id']]
            row={k:e[k] for k in names if k in e and k!='path_points'}
            row.update({k:v[k] for k in ['initial_kwh','battery_kwh','terminal_kwh','efficiency']})
            row['path_points']=';'.join(','.join(f'{x:.8f}' for x in point) for point in e['path_points'])
            writer.writerow(row)


def write_csv(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,keys);writer.writeheader();writer.writerows(rows)
