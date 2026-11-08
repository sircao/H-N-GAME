import math
import os
import random
import re
import xml.etree.ElementTree as ET

import unreal

TARGET_MAP_NAME = "EVSmallCity"
VEHICLE_COUNT = 800
SIM_START_HOUR = 6.0
SIM_END_HOUR = 23.0
DEFAULT_VIEW_HOUR = SIM_START_HOUR
SEED = 20260912
MAX_FNAME_TAG_LEN = 1000
MAX_ROUTE_POINTS_FOR_TAG = 26
MAX_PATH_TAG_VALUE_LEN = 320
MAX_PATH_TAG_CHUNKS = 8
MAX_TOTAL_SPAWN_ACTORS = 2200
MAX_BUILDING_SIGNS = 140
MAX_CHARGERS = 800                                                                                                                                                                                              
MAX_LAMP_PAIRS = 180
CIVILIAN_CAR_MESH = "/Game/ConceptCar/Car/SM_AutomotiveTP_Car.SM_AutomotiveTP_Car"

# Resolve map.osm from common locations.
OSM_PATH_CANDIDATES = [
    os.path.abspath(os.path.join(unreal.Paths.project_dir(), "..", "map.osm")),
    os.path.abspath(os.path.join(unreal.Paths.project_dir(), "map.osm")),
    "/media/cchio/new_disk/【2】IMSLAB/Game/map.osm",
]

ROAD_HIGHWAY_TYPES = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",                                                                                                                                                                                                                                                                 
    "residential",
    "living_street",
    "service",
    "unclassified",
    "cycleway",
    "road",
}

ROAD_DEFAULT_WIDTH_M = {
    "motorway": 9.0,
    "trunk": 8.0,
    "primary": 7.0,
    "secondary": 6.0,
    "tertiary": 5.5,
    "residential": 4.5,
    "living_street": 4.0,
    "service": 3.6,
    "unclassified": 4.0,
    "road": 4.0,
    "cycleway": 2.2,
}

LAMP_SPACING_M = 36.0
LAMP_POLE_HEIGHT_CM = 320.0
LAMP_OFFSET_MARGIN_M = 0.9

VEHICLE_TYPES = [
    {
        "name": "Sedan",
        "ratio": 0.45,
        "scale": unreal.Vector(0.82, 0.82, 0.82),
        "mesh_candidates": [CIVILIAN_CAR_MESH],
        "capacity_kwh": 65.0,
        "consumption_kwh_per_km": 0.135,
        "min_road_width_m": 2.0,
    },
    {
        "name": "SUV",
        "ratio": 0.30,
        "scale": unreal.Vector(0.92, 0.92, 1.02),
        "mesh_candidates": [CIVILIAN_CAR_MESH],
        "capacity_kwh": 82.0,
        "consumption_kwh_per_km": 0.17,
        "min_road_width_m": 2.2,
    },
    {
        "name": "Hatch",
        "ratio": 0.17,
        "scale": unreal.Vector(0.72, 0.78, 0.78),
        "mesh_candidates": [CIVILIAN_CAR_MESH],
        "capacity_kwh": 52.0,
        "consumption_kwh_per_km": 0.12,
        "min_road_width_m": 1.9,
    },
    {
        "name": "MiniBus",
        "ratio": 0.08,
        "scale": unreal.Vector(1.02, 0.94, 1.08),
        "mesh_candidates": [CIVILIAN_CAR_MESH],
        "capacity_kwh": 110.0,
        "consumption_kwh_per_km": 0.26,
        "min_road_width_m": 2.8,
    },
]


def load_first_asset(paths):
    for p in paths:
        asset = unreal.load_asset(p)
        if asset is not None:
            return asset
    return None


def weighted_choice(items, ratio_key="ratio"):
    roll = random.random()
    acc = 0.0
    for item in items:
        acc += item[ratio_key]
        if roll <= acc:
            return item
    return items[-1]


def actor_class_name(actor):
    return actor.get_class().get_name().lower()


def actor_label(actor):
    return actor.get_actor_label().lower()


def is_streetmap_actor(actor):
    cls = actor_class_name(actor)
    lbl = actor_label(actor)
    if "streetmap" in cls or "streetmap" in lbl or "osm" in lbl:
        return True
    for comp in actor.get_components_by_class(unreal.ActorComponent):
        comp_cls = comp.get_class().get_name().lower()
        if "streetmap" in comp_cls or "osm" in comp_cls:
            return True
    return False


def is_infra_actor(actor):
    cls = actor_class_name(actor)
    keep_keywords = [
        "light",
        "sky",
        "atmosphere",
        "fog",
        "cloud",
        "postprocess",
        "volumetric",
        "playerstart",
        "gamemode",
        "camera",
    ]
    return any(k in cls for k in keep_keywords)


def should_destroy_actor(actor):
    lbl = actor_label(actor)
    if (
        lbl.startswith("evsim_")
        or lbl.startswith("evsign_")
        or lbl.startswith("evcharger_")
        or lbl.startswith("evlamppole_")
        or lbl.startswith("evstreetlamp_")
    ):
        return True
    if lbl.startswith("evruntimehud"):
        return True
    if lbl.startswith("evtrafficruntimecontroller"):
        return True

    if is_streetmap_actor(actor) or is_infra_actor(actor):
        return False

    # Keep previously generated grass base if user wants global grass background.
    if lbl == "ev_grassground":
        return False

    return False


def clear_previous_sim_actors():
    removed = 0
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if should_destroy_actor(actor):
            if unreal.EditorLevelLibrary.destroy_actor(actor):
                removed += 1
    return removed


class OSMData(object):
    def __init__(self):
        self.nodes = {}  # node_id -> (lat, lon)
        self.road_ways = []  # [{node_ids, width_m, highway}]
        self.buildings = []  # [{name, node_ids, amenity, tags}]
        self.poi_chargers = []  # [node_id]


def parse_float_from_text(value):
    if value is None:
        return None
    txt = str(value)
    m = re.search(r"[-+]?\d*\.?\d+", txt)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def resolve_road_width_m(tags, highway):
    raw_w = tags.get("width")
    w = parse_float_from_text(raw_w)
    if w is not None and w > 0.5:
        return float(w)

    lanes = parse_float_from_text(tags.get("lanes"))
    if lanes is not None and lanes >= 1.0:
        return max(2.0, min(14.0, lanes * 3.1))

    return ROAD_DEFAULT_WIDTH_M.get(highway, 4.0)


def parse_osm(osm_path):
    data = OSMData()
    tree = ET.parse(osm_path)
    root = tree.getroot()

    for n in root.findall("node"):
        nid = n.attrib.get("id")
        lat = n.attrib.get("lat")
        lon = n.attrib.get("lon")
        if nid is None or lat is None or lon is None:
            continue
        data.nodes[nid] = (float(lat), float(lon))

        tags = {t.attrib.get("k"): t.attrib.get("v") for t in n.findall("tag")}
        if tags.get("amenity") == "charging_station":
            data.poi_chargers.append(nid)

    for w in root.findall("way"):
        node_ids = [nd.attrib.get("ref") for nd in w.findall("nd") if nd.attrib.get("ref")]
        if len(node_ids) < 2:
            continue

        tags = {t.attrib.get("k"): t.attrib.get("v") for t in w.findall("tag")}

        hw = tags.get("highway")
        if hw in ROAD_HIGHWAY_TYPES:
            data.road_ways.append(
                {
                    "node_ids": node_ids,
                    "width_m": resolve_road_width_m(tags, hw),
                    "highway": hw,
                }
            )

        if "building" in tags:
            data.buildings.append(
                {
                    "name": tags.get("name", ""),
                    "node_ids": node_ids,
                    "amenity": tags.get("amenity", ""),
                    "tags": tags,
                }
            )

        if tags.get("amenity") == "charging_station":
            if node_ids:
                data.poi_chargers.append(node_ids[0])

    return data


def project_latlon(lat, lon, lat0):
    r = 6378137.0
    x = math.radians(lon) * r * math.cos(math.radians(lat0))
    y = math.radians(lat) * r
    return x, y


def osm_to_projected(data):
    if not data.nodes:
        return {}, 0.0

    lat0 = sum(lat for lat, _ in data.nodes.values()) / float(len(data.nodes))
    projected = {}
    for nid, (lat, lon) in data.nodes.items():
        projected[nid] = project_latlon(lat, lon, lat0)
    return projected, lat0


def get_streetmap_world_bounds():
    origins = []
    extents = []
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if not is_streetmap_actor(actor):
            continue
        origin, extent = actor.get_actor_bounds(False)
        origins.append(origin)
        extents.append(extent)

    if not origins:
        return unreal.Vector(0.0, 0.0, 0.0), unreal.Vector(28000.0, 28000.0, 1000.0), 0

    min_x = min(o.x - e.x for o, e in zip(origins, extents))
    max_x = max(o.x + e.x for o, e in zip(origins, extents))
    min_y = min(o.y - e.y for o, e in zip(origins, extents))
    max_y = max(o.y + e.y for o, e in zip(origins, extents))
    min_z = min(o.z - e.z for o, e in zip(origins, extents))

    center = unreal.Vector((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, min_z)
    extent = unreal.Vector((max_x - min_x) * 0.5, (max_y - min_y) * 0.5, 1000.0)
    return center, extent, len(origins)


def build_world_mapper(projected_nodes, world_center, world_extent):
    xs = [p[0] for p in projected_nodes.values()]
    ys = [p[1] for p in projected_nodes.values()]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)

    usable_x = max(world_extent.x * 1.8, 1000.0)
    usable_y = max(world_extent.y * 1.8, 1000.0)

    def map_xy(x, y):
        nx = (x - min_x) / span_x
        ny = (y - min_y) / span_y
        wx = world_center.x - usable_x * 0.5 + nx * usable_x
        wy = world_center.y - usable_y * 0.5 + ny * usable_y
        return wx, wy

    return map_xy


def way_centroid_world(node_ids, projected_nodes, mapper):
    pts = [projected_nodes[nid] for nid in node_ids if nid in projected_nodes]
    if len(pts) < 3:
        return None
    cx = sum(p[0] for p in pts) / float(len(pts))
    cy = sum(p[1] for p in pts) / float(len(pts))
    wx, wy = mapper(cx, cy)
    return unreal.Vector(wx, wy, 0.0)


def sampled_road_points_world(data, projected_nodes, mapper, sample_step=4):
    out = []
    for way_info in data.road_ways:
        way = way_info["node_ids"]
        for idx, nid in enumerate(way):
            if idx % sample_step != 0:
                continue
            if nid not in projected_nodes:
                continue
            px, py = projected_nodes[nid]
            wx, wy = mapper(px, py)
            out.append(unreal.Vector(wx, wy, 5.0))
    return out


def build_road_graph_world(data, projected_nodes, mapper):
    node_world = {}
    adjacency = {}

    for way_info in data.road_ways:
        way = way_info["node_ids"]
        width_m = float(max(1.0, way_info.get("width_m", 4.0)))
        valid = [nid for nid in way if nid in projected_nodes]
        if len(valid) < 2:
            continue

        for nid in valid:
            if nid not in node_world:
                px, py = projected_nodes[nid]
                wx, wy = mapper(px, py)
                node_world[nid] = unreal.Vector(wx, wy, 42.0)
            adjacency.setdefault(nid, {})

        for i in range(1, len(valid)):
            a = valid[i - 1]
            b = valid[i]
            adjacency[a][b] = max(width_m, adjacency[a].get(b, 0.0))
            adjacency[b][a] = max(width_m, adjacency[b].get(a, 0.0))

    components = []
    visited = set()
    for nid in adjacency.keys():
        if nid in visited:
            continue
        stack = [nid]
        visited.add(nid)
        comp = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in adjacency.get(cur, {}).keys():
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append(nxt)
        if len(comp) >= 8:
            components.append(comp)

    return node_world, adjacency, components


def choose_component_weighted(components):
    total = float(sum(len(c) for c in components))
    if total <= 0.0:
        return None
    r = random.uniform(0.0, total)
    acc = 0.0
    for c in components:
        acc += len(c)
        if r <= acc:
            return c
    return components[-1]


def random_route_on_topology(node_world, adjacency, components, min_edge_width_m=2.0, min_steps=22, max_steps=110):
    if not components:
        return None

    for _ in range(40):
        comp = choose_component_weighted(components)
        if not comp:
            continue

        current = comp[random.randint(0, len(comp) - 1)]
        path = [current]
        prev = None
        steps = random.randint(min_steps, max_steps)

        for _step in range(steps):
            nbrs = [n for n, w in adjacency.get(current, {}).items() if w >= min_edge_width_m]
            if not nbrs:
                break

            candidates = [n for n in nbrs if n != prev]
            if not candidates:
                candidates = nbrs
            nxt = candidates[random.randint(0, len(candidates) - 1)]
            path.append(nxt)
            prev = current
            current = nxt

        if len(path) < 8:
            continue

        points = [node_world[nid] for nid in path if nid in node_world]
        if len(points) < 8:
            continue

        route = [points[0]]
        for idx in range(1, len(points) - 1):
            if idx % 2 == 0:
                route.append(points[idx])
        route.append(points[-1])

        if len(route) >= 4:
            return route

    return None


def building_polygons_world(data, projected_nodes, mapper):
    polygons = []
    for b in data.buildings:
        pts = []
        for nid in b["node_ids"]:
            if nid not in projected_nodes:
                continue
            px, py = projected_nodes[nid]
            wx, wy = mapper(px, py)
            pts.append((wx, wy))
        if len(pts) < 3:
            continue

        min_x = min(p[0] for p in pts)
        max_x = max(p[0] for p in pts)
        min_y = min(p[1] for p in pts)
        max_y = max(p[1] for p in pts)
        polygons.append({"pts": pts, "min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y})
    return polygons


def point_in_polygon_2d(x, y, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        intersect = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) + 1e-9) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside


def point_in_building(point, polygons):
    x = point.x
    y = point.y
    for poly in polygons:
        if x < poly["min_x"] or x > poly["max_x"] or y < poly["min_y"] or y > poly["max_y"]:
            continue
        if point_in_polygon_2d(x, y, poly["pts"]):
            return True
    return False


def route_is_building_safe(route, polygons):
    if not polygons:
        return True
    for idx, p in enumerate(route):
        if idx % 3 != 0 and idx != len(route) - 1:
            continue
        if point_in_building(p, polygons):
            return False
    return True


def spawn_street_lights(data, projected_nodes, mapper, building_polys, pole_mesh, world_z=6.0, max_pairs=MAX_LAMP_PAIRS):
    if pole_mesh is None:
        return 0

    lamp_index = 0
    spawned_actors = 0
    lamp_step_cm = max(800.0, LAMP_SPACING_M * 100.0)

    for way_info in data.road_ways:
        way = way_info["node_ids"]
        road_width_m = max(1.8, float(way_info.get("width_m", 4.0)))
        offset_cm = ((road_width_m * 100.0) * 0.5) + (LAMP_OFFSET_MARGIN_M * 100.0)

        way_pts = []
        for nid in way:
            if nid not in projected_nodes:
                continue
            px, py = projected_nodes[nid]
            wx, wy = mapper(px, py)
            way_pts.append(unreal.Vector(wx, wy, world_z))
        if len(way_pts) < 2:
            continue

        carry_cm = random.uniform(0.0, lamp_step_cm)
        for i in range(1, len(way_pts)):
            a = way_pts[i - 1]
            b = way_pts[i]
            dx = b.x - a.x
            dy = b.y - a.y
            seg_len = math.sqrt(dx * dx + dy * dy)
            if seg_len < 100.0:
                continue

            ux = dx / seg_len
            uy = dy / seg_len
            nx = -uy
            ny = ux

            d = carry_cm
            while d < seg_len:
                cx = a.x + ux * d
                cy = a.y + uy * d
                left = unreal.Vector(cx + nx * offset_cm, cy + ny * offset_cm, world_z)
                right = unreal.Vector(cx - nx * offset_cm, cy - ny * offset_cm, world_z)

                for side, pos in (("L", left), ("R", right)):
                    if point_in_building(pos, building_polys):
                        continue

                    pole = spawn_mesh_actor(
                        "EVLampPole_%05d_%s" % (lamp_index, side),
                        pole_mesh,
                        unreal.Vector(pos.x, pos.y, LAMP_POLE_HEIGHT_CM * 0.5),
                        unreal.Vector(0.07, 0.07, LAMP_POLE_HEIGHT_CM / 100.0),
                        random.uniform(0.0, 360.0),
                    )
                    pole.tags = ["LAMP_POLE"]
                    spawned_actors += 1

                    lamp = unreal.EditorLevelLibrary.spawn_actor_from_class(
                        unreal.PointLight,
                        unreal.Vector(pos.x, pos.y, LAMP_POLE_HEIGHT_CM + 60.0),
                        unreal.Rotator(0.0, 0.0, 0.0),
                    )
                    lamp.set_actor_label("EVStreetLamp_%05d_%s" % (lamp_index, side))
                    light_comp = lamp.point_light_component
                    light_comp.set_editor_property("intensity", 28000.0)
                    light_comp.set_editor_property("attenuation_radius", 3600.0)
                    light_comp.set_light_color(unreal.LinearColor(1.0, 0.93, 0.78, 1.0))
                    light_comp.set_visibility(False)
                    spawned_actors += 1

                lamp_index += 1
                if lamp_index >= max_pairs:
                    return spawned_actors
                d += lamp_step_cm

            carry_cm = d - seg_len

    return spawned_actors


def nearest_point(target, points):
    best = None
    best_d2 = None
    for p in points:
        dx = p.x - target.x
        dy = p.y - target.y
        d2 = dx * dx + dy * dy
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best = p
    return best


def spawn_text_label(label, text, location, scale=1.2):
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.TextRenderActor,
        location,
        unreal.Rotator(0.0, random.uniform(0.0, 360.0), 0.0),
    )
    actor.set_actor_label(label)

    text_comp = actor.get_editor_property("text_render")
    text_comp.set_editor_property("horizontal_alignment", unreal.HorizTextAligment.EHTA_CENTER)
    text_comp.set_editor_property("vertical_alignment", unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
    text_comp.set_world_size(80.0 * scale)
    text_comp.set_text(text)
    text_comp.set_text_render_color(unreal.Color(255, 245, 200, 255))
    return actor


def spawn_mesh_actor(label, mesh, location, scale, yaw):
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.StaticMeshActor,
        location,
        unreal.Rotator(0.0, yaw, 0.0),
    )
    actor.set_actor_label(label)
    actor.static_mesh_component.set_static_mesh(mesh)
    actor.set_actor_scale3d(scale)
    return actor


def spawn_charger_model(index, location, cube_mesh, cylinder_mesh, yaw):
    prefix = "EVCharger_%04d" % index
    parts = [
        spawn_mesh_actor(
            prefix + "_Base",
            cylinder_mesh,
            unreal.Vector(location.x, location.y, location.z + 8.0),
            unreal.Vector(0.58, 0.58, 0.16),
            yaw,
        ),
        spawn_mesh_actor(
            prefix + "_Cabinet",
            cube_mesh,
            unreal.Vector(location.x, location.y, location.z + 78.0),
            unreal.Vector(0.52, 0.36, 1.35),
            yaw,
        ),
        spawn_mesh_actor(
            prefix + "_Beacon",
            cylinder_mesh,
            unreal.Vector(location.x, location.y, location.z + 154.0),
            unreal.Vector(0.22, 0.22, 0.18),
            yaw,
        ),
    ]
    for part in parts:
        part.tags = ["EV_CHARGER", "CHARGER_ID:%04d" % index]
    return parts


def spawn_vehicle_actor(label, mesh_asset, location, scale, yaw):
    cls_name = mesh_asset.get_class().get_name().lower()
    if "skeletalmesh" in cls_name:
        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.SkeletalMeshActor,
            location,
            unreal.Rotator(0.0, yaw, 0.0),
        )
        actor.set_actor_label(label)
        actor.skeletal_mesh_component.set_skeletal_mesh(mesh_asset)
        actor.skeletal_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        actor.set_actor_scale3d(scale)
        return actor

    actor = spawn_mesh_actor(label, mesh_asset, location, scale, yaw)
    actor.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    return actor


def is_skeletal_mesh_asset(mesh_asset):
    if mesh_asset is None:
        return False
    cls_name = mesh_asset.get_class().get_name().lower()
    return "skeletalmesh" in cls_name


def find_osm_file():
    for p in OSM_PATH_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("Cannot find map.osm. Checked: %s" % OSM_PATH_CANDIDATES)


def compute_vehicle_progress(hour, depart_h, arrive_h):
    if hour <= depart_h:
        return 0.0
    if hour >= arrive_h:
        return 1.0
    return (hour - depart_h) / max(arrive_h - depart_h, 0.01)


def lerp(a, b, t):
    return a + (b - a) * t


def vec_to_tag(v):
    # Use 1 decimal place to reduce tag size pressure in UE FName-backed Actor.tags.
    return "%.1f,%.1f,%.1f" % (v.x, v.y, v.z)


def path_to_tag(path_points):
    return ";".join(vec_to_tag(p) for p in path_points)


def simplify_path_points(path_points, max_points=MAX_ROUTE_POINTS_FOR_TAG):
    if len(path_points) <= max_points:
        return list(path_points)

    simplified = []
    last_idx = len(path_points) - 1
    for i in range(max_points):
        idx = int(round((float(i) / float(max_points - 1)) * last_idx))
        simplified.append(path_points[idx])
    return simplified


def sanitize_tag_for_fname(tag, max_len=MAX_FNAME_TAG_LEN):
    if len(tag) <= max_len:
        return tag

    if ":" in tag:
        key, value = tag.split(":", 1)
        budget = max(0, max_len - len(key) - 1)
        return "%s:%s" % (key, value[:budget])

    return tag[:max_len]


def normalize_path_tags(tags, max_value_len=MAX_PATH_TAG_VALUE_LEN, max_chunks=MAX_PATH_TAG_CHUNKS):
    """Rewrite any PATH/PATHn tags into bounded PATHn chunks."""
    preserved = []
    path_values = []

    for t in tags:
        if t.startswith("PATH:"):
            path_values.append(t.split(":", 1)[1])
            continue
        if t.startswith("PATH") and ":" in t:
            key, value = t.split(":", 1)
            if key[4:].isdigit():
                path_values.append(value)
                continue
        preserved.append(t)

    if not path_values:
        return list(tags)

    merged = ";".join(v for v in path_values if v)
    if not merged:
        return preserved + ["PATH0:"]

    points = [p for p in merged.split(";") if p]
    chunks = []
    cur = ""
    for pt in points:
        candidate = pt if not cur else (cur + ";" + pt)
        if len(candidate) <= max_value_len:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
            if len(chunks) >= max_chunks:
                break
        cur = pt

    if len(chunks) < max_chunks and cur:
        chunks.append(cur)

    if not chunks:
        chunks = [""]

    rebuilt_path_tags = ["PATH%d:%s" % (idx, c) for idx, c in enumerate(chunks[:max_chunks])]
    return preserved + rebuilt_path_tags


def sanitize_tags_for_fname(tags, max_len=MAX_FNAME_TAG_LEN):
    normalized = normalize_path_tags(tags)
    return [sanitize_tag_for_fname(t, max_len=max_len) for t in normalized]


def path_to_chunked_tags(path_points, max_value_len=MAX_PATH_TAG_VALUE_LEN, max_chunks=MAX_PATH_TAG_CHUNKS):
    """Encode path into multiple PATHn tags to stay under UE FName max length."""
    points = [vec_to_tag(p) for p in simplify_path_points(path_points)]
    if not points:
        return ["PATH0:"]

    chunks = []
    cur = ""
    for pt in points:
        candidate = pt if not cur else (cur + ";" + pt)
        if len(candidate) <= max_value_len:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
            if len(chunks) >= max_chunks:
                break
        cur = pt

    if len(chunks) < max_chunks and cur:
        chunks.append(cur)

    if not chunks:
        chunks = [""]

    tags = ["PATH%d:%s" % (idx, c) for idx, c in enumerate(chunks[:max_chunks])]
    return sanitize_tags_for_fname(tags)


def path_length_cm(path_points):
    total = 0.0
    for i in range(1, len(path_points)):
        dx = path_points[i].x - path_points[i - 1].x
        dy = path_points[i].y - path_points[i - 1].y
        dz = path_points[i].z - path_points[i - 1].z
        total += math.sqrt(dx * dx + dy * dy + dz * dz)
    return total


def point_on_path(path_points, t):
    if not path_points:
        return unreal.Vector(0.0, 0.0, 42.0), unreal.Vector(1.0, 0.0, 0.0)
    if len(path_points) == 1:
        return path_points[0], unreal.Vector(1.0, 0.0, 0.0)

    length = path_length_cm(path_points)
    if length <= 0.01:
        return path_points[0], unreal.Vector(1.0, 0.0, 0.0)

    remain = max(0.0, min(1.0, t)) * length
    for i in range(1, len(path_points)):
        a = path_points[i - 1]
        b = path_points[i]
        seg = math.sqrt((b.x - a.x) ** 2 + (b.y - a.y) ** 2 + (b.z - a.z) ** 2)
        if seg <= 0.01:
            continue
        if remain <= seg:
            u = remain / seg
            p = unreal.Vector(lerp(a.x, b.x, u), lerp(a.y, b.y, u), lerp(a.z, b.z, u))
            d = unreal.Vector(b.x - a.x, b.y - a.y, 0.0)
            return p, d
        remain -= seg

    a = path_points[-2]
    b = path_points[-1]
    return path_points[-1], unreal.Vector(b.x - a.x, b.y - a.y, 0.0)


def route_point(start, mid, end, t):
    if t <= 0.5:
        u = t / 0.5
        return unreal.Vector(lerp(start.x, mid.x, u), lerp(start.y, mid.y, u), lerp(start.z, mid.z, u))
    u = (t - 0.5) / 0.5
    return unreal.Vector(lerp(mid.x, end.x, u), lerp(mid.y, end.y, u), lerp(mid.z, end.z, u))


def set_editor_property_fallback(actor, names, value):
    """Try multiple reflected property names to handle UE bool naming differences."""
    last_err = None
    for n in names:
        try:
            actor.set_editor_property(n, value)
            return n
        except Exception as e:
            last_err = e
    raise RuntimeError("Failed to set properties %s, last error: %s" % (names, last_err))


def clipped_name(raw_name, fallback, max_len=14):
    n = (raw_name or "").strip()
    if not n:
        n = fallback
    if len(n) <= max_len:
        return n
    return n[:max_len] + "..."


def design_ev_day_traffic(view_hour=DEFAULT_VIEW_HOUR, vehicle_count=VEHICLE_COUNT):
    random.seed(SEED)

    world = unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        raise RuntimeError("No editor world is open")
    if world.get_name() != TARGET_MAP_NAME:
        raise RuntimeError("Open %s before running script. Current map: %s" % (TARGET_MAP_NAME, world.get_name()))

    osm_path = find_osm_file()
    data = parse_osm(osm_path)
    if not data.nodes or not data.road_ways or not data.buildings:
        raise RuntimeError("OSM data incomplete: nodes=%d roads=%d buildings=%d" % (len(data.nodes), len(data.road_ways), len(data.buildings)))

    projected_nodes, _ = osm_to_projected(data)

    world_center, world_extent, streetmap_count = get_streetmap_world_bounds()
    mapper = build_world_mapper(projected_nodes, world_center, world_extent)
    building_polys = building_polygons_world(data, projected_nodes, mapper)
    road_nodes_world, road_adj, road_components = build_road_graph_world(data, projected_nodes, mapper)

    roads_world = sampled_road_points_world(data, projected_nodes, mapper, sample_step=5)
    if len(roads_world) < 200:
        raise RuntimeError("Too few sampled road points (%d)." % len(roads_world))
    if len(road_nodes_world) < 300 or not road_components:
        raise RuntimeError("Road topology incomplete: nodes=%d components=%d" % (len(road_nodes_world), len(road_components)))

    buildings_world = []
    for i, b in enumerate(data.buildings):
        c = way_centroid_world(b["node_ids"], projected_nodes, mapper)
        if c is None:
            continue
        bname = clipped_name(b.get("name", ""), "建筑_%03d" % i)
        buildings_world.append({"id": i, "name": bname, "loc": c})

    if len(buildings_world) < 50:
        raise RuntimeError("Too few projected buildings (%d)." % len(buildings_world))

    removed = clear_previous_sim_actors()

    cube = unreal.load_asset("/Engine/BasicShapes/Cube.Cube")
    cyl = unreal.load_asset("/Engine/BasicShapes/Cylinder.Cylinder")
    if cube is None or cyl is None:
        raise RuntimeError("Cannot load basic shape meshes")

    # Resolve one 3D model per vehicle type; fallback to cube if model missing.
    for v in VEHICLE_TYPES:
        mesh = load_first_asset(v.get("mesh_candidates", []))
        if mesh is None:
            mesh = cube
            unreal.log_warning("No 3D vehicle mesh found for %s, fallback cube" % v["name"])
        v["mesh"] = mesh

    # Building signs
    sign_count = min(len(buildings_world), MAX_BUILDING_SIGNS)
    sign_stride = max(1, len(buildings_world) // sign_count)
    signs = 0
    for idx in range(0, len(buildings_world), sign_stride):
        b = buildings_world[idx]
        sign_pos = unreal.Vector(b["loc"].x, b["loc"].y, 240.0)
        spawn_text_label("EVSign_%04d" % signs, b["name"], sign_pos, scale=1.0)
        signs += 1
        if signs >= sign_count:
            break

    # Chargers near building centroids
    charger_count = min(max(40, len(buildings_world) // 16), MAX_CHARGERS)
    chargers = []
    charger_actor_count = 0
    for cidx in range(charger_count):
        b = buildings_world[random.randint(0, len(buildings_world) - 1)]
        offset = unreal.Vector(random.uniform(-260.0, 260.0), random.uniform(-260.0, 260.0), 0.0)
        cpos = unreal.Vector(b["loc"].x + offset.x, b["loc"].y + offset.y, offset.z)
        charger_parts = spawn_charger_model(
            cidx,
            cpos,
            cube,
            cyl,
            random.uniform(0.0, 360.0),
        )
        chargers.append(charger_parts[1])
        charger_actor_count += len(charger_parts)
        spawn_text_label(
            "EVChargerSign_%04d" % cidx,
            "充电桩",
            unreal.Vector(cpos.x, cpos.y, 205.0),
            scale=0.65,
        )

    lamp_actors = spawn_street_lights(
        data,
        projected_nodes,
        mapper,
        building_polys,
        cyl,
        world_z=6.0,
        max_pairs=MAX_LAMP_PAIRS,
    )

    fixed_actor_cost = signs + charger_actor_count + len(chargers) + lamp_actors + 2
    per_vehicle_actor_cost = 1

    budgeted_vehicles = max(
        80,
        (MAX_TOTAL_SPAWN_ACTORS - fixed_actor_cost) // max(1, per_vehicle_actor_cost),
    )
    requested_vehicles = int(vehicle_count)
    vehicle_count = max(1, min(requested_vehicles, budgeted_vehicles))
    if vehicle_count < requested_vehicles:
        unreal.log_warning(
            "Vehicle count reduced for safety: requested=%d, budgeted=%d, actor_budget=%d"
            % (requested_vehicles, vehicle_count, MAX_TOTAL_SPAWN_ACTORS)
        )

    # Runtime HUD for aggregate metrics during Play.
    hud = spawn_text_label(
        "EVRuntimeHUD",
        "系统总电量: 0.00 kWh\n系统剩余电量: 0.00 kWh\n系统总耗电量: 0.00 kWh\n总时长: 420 s\n已经耗时: 0.0 s",
        unreal.Vector(world_center.x, world_center.y, world_center.z + 620.0),
        scale=1.5,
    )
    hud_text = hud.get_editor_property("text_render")
    hud_text.set_world_size(120.0)

    # Vehicles with topology routes, schedule, battery and labels.
    vehicles = 0
    max_attempts = max(vehicle_count * 7, 12000)
    vid = 0
    attempts = 0
    while vehicles < vehicle_count and attempts < max_attempts:
        attempts += 1
        vtype = weighted_choice(VEHICLE_TYPES)
        width_need = float(vtype.get("min_road_width_m", 2.0))
        route = random_route_on_topology(
            road_nodes_world,
            road_adj,
            road_components,
            min_edge_width_m=width_need,
        )
        if route is None and width_need > 2.0:
            route = random_route_on_topology(
                road_nodes_world,
                road_adj,
                road_components,
                min_edge_width_m=max(2.0, width_need - 0.4),
            )
        if route is None:
            continue
        if not route_is_building_safe(route, building_polys):
            continue

        # Morning/evening commute profile.
        if random.random() < 0.62:
            depart_h = max(SIM_START_HOUR, min(10.5, random.gauss(8.0, 1.0)))
        else:
            depart_h = max(11.0, min(19.0, random.gauss(17.6, 1.2)))
        travel_h = random.uniform(0.4, 2.2)
        arrive_h = min(SIM_END_HOUR, depart_h + travel_h)

        soc_start = random.uniform(55.0, 98.0)
        distance_km = max(path_length_cm(route) / 100000.0, 0.5)
        energy_used = distance_km * vtype["consumption_kwh_per_km"] * random.uniform(0.85, 1.2)
        soc_drop = energy_used / vtype["capacity_kwh"] * 100.0
        soc_arrive = max(8.0, soc_start - soc_drop)

        if soc_arrive < 28.0:
            soc_after_charge = min(95.0, soc_arrive + random.uniform(35.0, 70.0))
        else:
            soc_after_charge = soc_arrive

        p0 = route[0]
        p1 = route[len(route) // 2]
        p2 = route[-1]

        progress = compute_vehicle_progress(view_hour, depart_h, arrive_h)
        pos, direction = point_on_path(route, progress)

        yaw = math.degrees(math.atan2(direction.y, direction.x))
        mesh_for_spawn = vtype["mesh"]

        car = spawn_vehicle_actor(
            "EVSim_%04d_%s" % (vid, vtype["name"]),
            mesh_for_spawn,
            unreal.Vector(pos.x, pos.y, 42.0),
            vtype["scale"],
            yaw,
        )

        tags = [
            "TYPE:%s" % vtype["name"],
            "DEPART:%.3f" % depart_h,
            "ARRIVE:%.3f" % arrive_h,
            "SOC0:%.3f" % soc_start,
            "SOC1:%.3f" % soc_arrive,
            "SOC2:%.3f" % soc_after_charge,
            "CAPK:%.4f" % vtype["capacity_kwh"],
            "EUSE:%.5f" % energy_used,
            "P0:%s" % vec_to_tag(p0),
            "P1:%s" % vec_to_tag(p1),
            "P2:%s" % vec_to_tag(p2),
        ]
        tags.extend(path_to_chunked_tags(route))
        car.tags = sanitize_tags_for_fname(tags)

        vehicles += 1
        vid += 1

    if vehicles < vehicle_count:
        unreal.log_warning(
            "Spawned vehicles lower than requested after retries: requested=%d spawned=%d attempts=%d"
            % (vehicle_count, vehicles, attempts)
        )

    # Spawn runtime controller so vehicles animate during Play.
    ctrl_class = unreal.load_class(None, "/Script/UHMP.EVTrafficRuntimeController")
    if ctrl_class is not None:
        ctrl = unreal.EditorLevelLibrary.spawn_actor_from_class(
            ctrl_class,
            unreal.Vector(world_center.x, world_center.y, world_center.z + 120.0),
            unreal.Rotator(0.0, 0.0, 0.0),
        )
        ctrl.set_actor_label("EVTrafficRuntimeController")
        ctrl.set_editor_property("sim_start_hour", SIM_START_HOUR)
        ctrl.set_editor_property("sim_end_hour", SIM_END_HOUR)
        ctrl.set_editor_property("initial_hour", SIM_START_HOUR)
        ctrl.set_editor_property("sim_day_duration_seconds", 420.0)
        set_editor_property_fallback(ctrl, ["b_loop_simulation", "loop_simulation"], True)
        set_editor_property_fallback(ctrl, ["b_run_simulation", "run_simulation"], True)
    else:
        unreal.log_warning("Runtime controller class missing: compile UHMP C++ to enable Play-time movement")

    if not unreal.EditorLoadingAndSavingUtils.save_current_level():
        raise RuntimeError("Unable to save level after EV traffic generation")

    unreal.log(
        "EV day traffic done | map=%s | streetmap=%d | removed=%d | buildings=%d | signs=%d | chargers=%d | lamp_groups=%d | vehicles=%d | view_hour=%.2f"
        % (
            os.path.basename(osm_path),
            streetmap_count,
            removed,
            len(buildings_world),
            signs,
            len(chargers),
            lamp_actors,
            vehicles,
            view_hour,
        )
    )


# Main entry
# Change DEFAULT_VIEW_HOUR to visualize different moments from morning to evening.
design_ev_day_traffic(view_hour=DEFAULT_VIEW_HOUR, vehicle_count=VEHICLE_COUNT)


def refresh_by_hour(hour):
    """Convenience entry: call refresh_by_hour(6.0..20.0) in UE Python console."""
    hour = max(SIM_START_HOUR, min(SIM_END_HOUR, float(hour)))
    design_ev_day_traffic(view_hour=hour, vehicle_count=VEHICLE_COUNT)
