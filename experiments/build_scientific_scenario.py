"""Build a complete, finite simulation task contract from actual map actors.

New assumptions are recorded as protocol inputs. No trajectory is treated as an
independent observation of the model that generated it.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
RATES={'Sedan':.135,'SUV':.17,'Hatch':.12,'MiniBus':.26}


def read_vector(text):
    values=re.findall(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?',text)
    if len(values)!=3:raise ValueError('Expected 3D source vector')
    return [float(x) for x in values]


def waypoint_polyline(points,approach,middle,exit_path,p0,p2,station0,station1):
    """Visit exact OD waypoints at the route section boundaries, including loops."""
    o,d=middle[0],middle[-1]
    return ([station0]+[points[n].tolist() for n in approach]
            +[p0,points[o].tolist()]+[points[n].tolist() for n in middle[1:]]
            +[p2,points[d].tolist()]+[points[n].tolist() for n in exit_path[1:]]+[station1])


def build(out):
    scene_path=out/'scene.json';protocol_path=ROOT/'experiments/scientific_protocol.json'
    scene=json.loads(scene_path.read_text());protocol=json.loads(protocol_path.read_text())
    params_path=ROOT/'unreal-map-master/Config/EVOptimizationParams.json'
    params=json.loads(params_path.read_text());keys=sorted(scene['road_nodes'])
    points=np.array([scene['road_nodes'][k] for k in keys]);index={k:i for i,k in enumerate(keys)}
    tree=cKDTree(points[:,:2]);start=[];end=[];dist=[];times=[]
    for a,b,width in scene['road_edges']:
        i,j=index[a],index[b];length=float(np.linalg.norm(points[i,:2]-points[j,:2]))/100000
        speed=protocol['road_speed_kmh']*min(1.5,max(.5,width/6))
        start.append(i);end.append(j);dist.append(length);times.append(length/speed)
    # Source adjacency is unique, but record exact topology size and component coverage.
    dist=np.array(dist);times=np.array(times)
    matrices=[coo_matrix((times+w*dist,(start,end)),shape=(len(keys),len(keys))).tocsr() for w in [0,.02,.05,.2,100]]
    _,components=connected_components(matrices[0],directed=False)
    stations={}
    for s in scene['stations']:
        snap=int(tree.query(np.array(s['position'][:2]))[1])
        stations[s['station_id']]=dict(position=s['position'],node=snap,
            connectors=int(params['default_station_capacity']),
            power_kw=float(params['default_station_capacity']*params['default_charging_power_kw']),
            connector_power_kw=float(params['default_charging_power_kw']))
    adjacency={(i,j):(d,t) for i,j,d,t in zip(start,end,dist,times)}
    cache={}
    def path(a,b,mode=0):
        cache_key=(a,mode)
        if cache_key not in cache:
            cache[cache_key]=dijkstra(matrices[mode],directed=True,indices=a,return_predecessors=True)
        distances,previous=cache[cache_key]
        if not np.isfinite(distances[b]):raise ValueError(f'Unreachable source endpoints {a}->{b}')
        sequence=[b]
        while sequence[-1]!=a:
            p=int(previous[sequence[-1]])
            if p<0:raise ValueError('Invalid predecessor chain')
            sequence.append(p)
        return list(reversed(sequence))
    component_trees={}
    def station_for(node):
        component=int(components[node])
        if component not in component_trees:
            members=np.flatnonzero(components==component)
            component_trees[component]=(members,cKDTree(points[members,:2]))
        members,local_tree=component_trees[component]
        s=min(stations,key=lambda s:np.linalg.norm(points[node,:2]-np.array(stations[s]['position'][:2])))
        # A declared local driveway joins the physical cabinet to the nearest
        # point of this source-road component. It is included in route geometry,
        # distance, time and energy, and is not inferred as a legal road.
        snap=int(members[int(local_tree.query(stations[s]['position'][:2])[1])])
        return s,snap
    vehicles=[];diagnostics=[]
    for vi,actor in enumerate(scene['vehicles']):
        tags=actor['tags'];vid=actor['vehicle_id']
        p0=read_vector(tags['P0']);p2=read_vector(tags['P2'])
        o=int(tree.query(p0[:2])[1]);d=int(tree.query(p2[:2])[1])
        if components[o]!=components[d]:raise ValueError(f'Original OD disconnected for {vid}')
        (s0,a),(s1,b)=station_for(o),station_for(d)
        rate=RATES[tags['TYPE']]
        routes=[];seen=set()
        for mode in range(5):
            approach=path(a,o);middle=path(o,d,mode);exit_path=path(d,b)
            seq=approach+middle[1:]+exit_path[1:]
            key=tuple(seq)
            if key in seen:continue
            seen.add(key)
            road_distance=sum(adjacency[i,j][0] for i,j in zip(seq,seq[1:]))
            road_time=sum(adjacency[i,j][1] for i,j in zip(seq,seq[1:]))
            # The physical cabinet-to-road access and exact OD snap connectors are
            # explicit off-road access segments, not cost-free teleports.
            access=(math.dist(stations[s0]['position'],points[a])+math.dist(stations[s1]['position'],points[b])+
                    2*math.dist(p0,points[o])+2*math.dist(p2,points[d]))/100000
            # Insert the required waypoints at section boundaries. Searching for
            # the first matching road node is incorrect when an approach or exit
            # happens to revisit the destination before the required origin.
            coords=waypoint_polyline(points,approach,middle,exit_path,p0,p2,stations[s0]['position'],stations[s1]['position'])
            length=road_distance+access
            routes.append(dict(route_id=f'{vid}:R{len(routes)}',time_h=road_time+access/protocol['station_access_speed_kmh'],
                               distance_km=length,energy_kwh=length*rate,path_points=coords,
                               road_distance_km=road_distance,access_distance_km=access))
        routes.sort(key=lambda r:(r['time_h'],r['energy_kwh']))
        depart=float(tags['DEPART']);span=max(float(tags['ARRIVE'])-depart,.01)
        effective=max(depart,params['morning_departure_floor_hour'])
        turnaround=min(params['max_turnaround_hours'],max(params['min_turnaround_hours'],span*params['turnaround_ratio']))
        cycle=max(span+turnaround,.05)
        count=int(math.floor((23-effective+turnaround)/cycle))
        count=min(max(count,params['min_daily_trip_legs']),params['max_daily_trip_legs'])
        # Unlike the legacy controller, never execute undeclared extra trips.
        count=min(count,max(0,int(math.floor((23-effective-span)/cycle))+1))
        if count<1:raise ValueError(f'No complete source-day task for {vid}')
        trips=[];windows=[];previous=0.;parking=s0
        for leg in range(count):
            departure=effective+leg*cycle;deadline=departure+span
            windows.append(dict(start=previous,end=departure,station_id=parking))
            leg_routes=[]
            for ri,r in enumerate(routes):
                rr=dict(r);rr['route_id']=f'{vid}:{leg}:R{ri}'
                if leg%2:rr['path_points']=list(reversed(r['path_points']))
                leg_routes.append(rr)
            trips.append(dict(leg=leg,task_id=f'{vid}:{leg}',departure=departure,deadline=deadline,
                              origin_station=s0 if leg%2==0 else s1,destination_station=s1 if leg%2==0 else s0,routes=leg_routes))
            previous=deadline;parking=s1 if leg%2==0 else s0
        windows.append(dict(start=previous,end=24.,station_id=parking))
        battery=float(tags['CAPK']);initial=battery*float(tags['SOC0'])/100
        vehicles.append(dict(vehicle_id=vid,vehicle_type=tags['TYPE'],battery_kwh=battery,initial_kwh=initial,
                             terminal_kwh=initial,reserve_kwh=battery*protocol['minimum_soc_pct']/100,
                             efficiency=protocol['charging_efficiency'],power_kw=float(params['default_charging_power_kw']),
                             trips=trips,windows=windows,initial_position=stations[s0]['position']))
        diagnostics.append(dict(vehicle_id=vid,trips=count,candidates=len(routes),
                                origin_snap_m=math.dist(p0,points[o])/100,destination_snap_m=math.dist(p2,points[d])/100,
                                shortest_time_h=routes[0]['time_h'],source_reserved_span_h=span,
                                all_deadline_feasible=all(r['time_h']<=span+1e-6 for r in routes)))
        if vi%100==0:print(f'Canonical vehicle {vi+1}/{len(scene["vehicles"])}',flush=True)
    dt=protocol['slot_hours'];wholesale=[.35 if h*dt<7 or h*dt>=22 else 1.1 if 17<=h*dt<22 else .65 for h in range(round(24/dt))]
    spec=dict(schema=2,dt=dt,vehicles=vehicles,stations=stations,retail=[p+.25 for p in wholesale],wholesale=wholesale,
              beta=protocol['time_value_cny_per_hour'],gamma=protocol['carbon_factor_kg_per_kwh'],tau=protocol['carbon_price_cny_per_tonne'],
              protocol=protocol,provenance={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [scene_path,protocol_path,params_path,Path(__file__)]},
              topology=dict(nodes=len(keys),directed_edges=len(start),source='full scene-generator road topology',coverage='all exported road edges; no trajectory pruning'),
              assumptions=['Finite source-tag schedule with explicit terminal energy and reserve added by the protocol.',
                           'Cars park at actual nearest component-accessible cabinets; access driving is included; initial placement at those cabinets is part of the revised simulation contract.',
                           'Parking windows reserve source deadline spans, so early arrival does not create extra unmodeled charging access.',
                           'Road speeds, efficiency, tariffs, reserve and terminal requirements are declared simulation inputs, not empirical calibration.',
                           'Physical cabinet driveways join the vehicle road component at its nearest point; straight-line driveway geometry is a declared simulation abstraction, not verified road access.',
                           'Road directions follow the original generator bidirectional convention, not a claim about legal real-world road directions.'])
    (out/'canonical_scenario.json').write_text(json.dumps(spec,indent=2,allow_nan=False)+'\n')
    (out/'topology_and_tasks.json').write_text(json.dumps(dict(vehicles=len(vehicles),trips=sum(len(v['trips']) for v in vehicles),stations=len(stations),**spec['topology'],diagnostics=diagnostics),indent=2)+'\n')
    return spec


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=ROOT/'experiments/scientific')
    args=p.parse_args();s=build(args.output_dir);print('Canonical scenario:',len(s['vehicles']),'vehicles',sum(len(v['trips']) for v in s['vehicles']),'trips')
