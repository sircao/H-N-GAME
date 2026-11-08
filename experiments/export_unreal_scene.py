"""Run with UE4's PythonScript commandlet. Read-only export of EVSmallCity."""
import ast
import hashlib
import json
import os
import re
import unreal

root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project=os.path.join(root,'unreal-map-master')
output=os.path.join(root,'experiments','scientific','scene.json')
unreal.EditorLevelLibrary.load_level('/Game/Maps/EVSmallCity')
vehicles=[];stations=[]
for actor in unreal.EditorLevelLibrary.get_all_level_actors():
    label=actor.get_actor_label()
    pos=actor.get_actor_location()
    if label.startswith('EVSim_'):
        tags={}
        for raw in actor.tags:
            key,sep,value=str(raw).partition(':')
            if sep:tags[key]=value
        vehicles.append(dict(vehicle_id=label.split('_')[1],label=label,tags=tags,
                             position=[pos.x,pos.y,pos.z]))
    elif label.startswith('EVCharger_') and label.endswith('_Cabinet'):
        stations.append(dict(station_id=label,position=[pos.x,pos.y,pos.z]))
# Reuse the scene generator's actual OSM->world transform without executing its
# top-level call that regenerates/saves the scene.
source=os.path.join(project,'Content','Python','design_ev_day_traffic.py')
with open(source,encoding='utf-8') as f:code=f.read()
tree=ast.parse(code,filename=source)
tree.body=[node for node in tree.body if not (isinstance(node,ast.Expr)
           and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name)
           and node.value.func.id=='design_ev_day_traffic')]
scope={'__name__':'scene_export_helpers'}
exec(compile(tree,source,'exec'),scope)
osm=scope['find_osm_file']()
data=scope['parse_osm'](osm)
projected,lat0=scope['osm_to_projected'](data)
center,extent,count=scope['get_streetmap_world_bounds']()
mapper=scope['build_world_mapper'](projected,center,extent)
nodes,adj,components=scope['build_road_graph_world'](data,projected,mapper)
result=dict(schema=1,map='/Game/Maps/EVSmallCity',vehicles=sorted(vehicles,key=lambda v:v['vehicle_id']),
            stations=sorted(stations,key=lambda s:s['station_id']),
            road_nodes={str(k):[v.x,v.y,v.z] for k,v in nodes.items()},
            road_edges=[[str(a),str(b),width] for a,neighbors in adj.items() for b,width in neighbors.items()],
            coordinate_units='Unreal centimeters; source graph uses the map generator bidirectional-road convention',
            streetmap_actors=count,world_center=[center.x,center.y,center.z],world_extent=[extent.x,extent.y,extent.z],
            osm_path=osm,osm_sha256=hashlib.sha256(open(osm,'rb').read()).hexdigest(),
            generator_sha256=hashlib.sha256(code.encode()).hexdigest(),
            source_kind='stored simulated map actors/tags and full generator road topology; not observed city data')
if not vehicles or not stations or not nodes:raise RuntimeError('Incomplete scene export')
os.makedirs(os.path.dirname(output),exist_ok=True)
with open(output,'w',encoding='utf-8') as f:json.dump(result,f,indent=2)
unreal.log('SCIENTIFIC_SCENE_EXPORTED '+output+' vehicles='+str(len(vehicles))+' stations='+str(len(stations)))
