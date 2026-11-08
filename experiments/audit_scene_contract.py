"""Independent source-actor/geometry/finite-task audit for the revised contract."""
import hashlib
import json
import math
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def vector(text):return [float(x) for x in re.findall(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?',text)]


def audit():
    out=ROOT/'experiments/scientific';scene=json.loads((out/'scene.json').read_text());s=json.loads((out/'canonical_scenario.json').read_text())
    params=json.loads((ROOT/'unreal-map-master/Config/EVOptimizationParams.json').read_text())
    for name,expected in s['provenance'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:raise ValueError('Canonical source changed: '+name)
    actors={a['vehicle_id']:a for a in scene['vehicles']};facilities={a['station_id']:a for a in scene['stations']}
    if {v['vehicle_id'] for v in s['vehicles']}!=set(actors) or set(s['stations'])!=set(facilities):raise ValueError('Source vehicles/facilities removed or fabricated')
    trips=0;max_access=0.
    for v in s['vehicles']:
        tags=actors[v['vehicle_id']]['tags'];o,d=vector(tags['P0']),vector(tags['P2'])
        span=max(float(tags['ARRIVE'])-float(tags['DEPART']),.01)
        departure=max(float(tags['DEPART']),params['morning_departure_floor_hour'])
        turnaround=min(params['max_turnaround_hours'],max(params['min_turnaround_hours'],span*params['turnaround_ratio']))
        cycle=max(span+turnaround,.05)
        declared=min(max(int((23-departure+turnaround)//cycle),params['min_daily_trip_legs']),params['max_daily_trip_legs'])
        expected=min(declared,max(0,int(math.floor((23-departure-span)/cycle))+1))
        if len(v['trips'])!=expected:raise ValueError('Finite task count differs from source rule')
        if abs(v['initial_kwh']-float(tags['CAPK'])*float(tags['SOC0'])/100)>1e-9:raise ValueError('Source initial battery changed')
        for t in v['trips']:
            leg=t['leg'];wanted=[o,d] if leg%2==0 else [d,o]
            if abs(t['departure']-(departure+leg*cycle))>1e-9 or abs(t['deadline']-t['departure']-span)>1e-9:raise ValueError('Source task clock changed')
            for r in t['routes']:
                points=r['path_points']
                if math.dist(points[0],facilities[t['origin_station']]['position'])>1e-6 or math.dist(points[-1],facilities[t['destination_station']]['position'])>1e-6:raise ValueError('Virtual/incorrect station location')
                first=next((i for i,p in enumerate(points) if math.dist(p,wanted[0])<1e-6),None)
                second=next((i for i,p in enumerate(points) if i>=(first or 0) and math.dist(p,wanted[1])<1e-6),None)
                if first is None or second is None:raise ValueError('Required source OD waypoint skipped')
                max_access=max(max_access,r['access_distance_km']*1000)
            trips+=1
    result=dict(passed=True,source_vehicles=len(actors),actual_charger_cabinets=len(facilities),finite_trips=trips,
                road_nodes=len(scene['road_nodes']),directed_road_links=len(scene['road_edges']),
                maximum_combined_route_access_m=max_access,
                access_interpretation='Declared cabinet driveways and exact-OD snap connectors are accounted in route geometry; independent legal-road access is not claimed')
    (out/'scene_contract_audit.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':print(json.dumps(audit(),indent=2))
