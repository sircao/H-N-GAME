import unreal

TARGET_MAP_NAME = "EVSmallCity"
GRASS_MATERIAL_CANDIDATES = [
    "/Game/StarterContent/Materials/M_Ground_Grass.M_Ground_Grass",
    "/Game/StarterContent/Materials/M_Ground_Grass",
]
GROUND_LABEL = "EV_GrassGround"


def _actor_class_name(actor):
    return actor.get_class().get_name().lower()


def _actor_label(actor):
    return actor.get_actor_label().lower()


def is_streetmap_actor(actor):
    class_name = _actor_class_name(actor)
    label = _actor_label(actor)

    if "streetmap" in class_name or "streetmap" in label or "osm" in label:
        return True

    for comp in actor.get_components_by_class(unreal.ActorComponent):
        comp_class_name = comp.get_class().get_name().lower()
        if "streetmap" in comp_class_name or "osm" in comp_class_name:
            return True

    return False


def is_world_infra_actor(actor):
    class_name = _actor_class_name(actor)

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
    ]
    return any(k in class_name for k in keep_keywords)


def should_remove_actor(actor):
    label = _actor_label(actor)
    class_name = _actor_class_name(actor)

    if label == GROUND_LABEL.lower():
        return True

    if is_streetmap_actor(actor):
        return False

    if is_world_infra_actor(actor):
        return False

    remove_label_keywords = ["ev_", "smallcity", "building", "road", "checkpoint", "barrier", "gantry"]
    if any(k in label for k in remove_label_keywords):
        return True

    if "staticmeshactor" in class_name:
        return True

    return False


def clear_small_city_content():
    removed = 0
    failed = 0

    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if not should_remove_actor(actor):
            continue

        try:
            ok = unreal.EditorLevelLibrary.destroy_actor(actor)
            if ok:
                removed += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    return removed, failed


def get_streetmap_bounds():
    origins = []
    extents = []

    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if not is_streetmap_actor(actor):
            continue
        origin, extent = actor.get_actor_bounds(False)
        origins.append(origin)
        extents.append(extent)

    if not origins:
        return unreal.Vector(0.0, 0.0, 0.0), unreal.Vector(25000.0, 25000.0, 500.0), 0

    min_x = min(o.x - e.x for o, e in zip(origins, extents))
    max_x = max(o.x + e.x for o, e in zip(origins, extents))
    min_y = min(o.y - e.y for o, e in zip(origins, extents))
    max_y = max(o.y + e.y for o, e in zip(origins, extents))
    min_z = min(o.z - e.z for o, e in zip(origins, extents))

    center = unreal.Vector((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, min_z)
    half_extent = unreal.Vector((max_x - min_x) * 0.5, (max_y - min_y) * 0.5, 500.0)
    return center, half_extent, len(origins)


def load_grass_material():
    for path in GRASS_MATERIAL_CANDIDATES:
        mat = unreal.load_asset(path)
        if mat is not None:
            return mat, path
    return None, ""


def spawn_grass_ground(center, half_extent):
    cube = unreal.load_asset("/Engine/BasicShapes/Cube.Cube")
    if cube is None:
        raise RuntimeError("Engine cube mesh is unavailable")

    ground = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.StaticMeshActor,
        unreal.Vector(center.x, center.y, center.z - 35.0),
        unreal.Rotator(0.0, 0.0, 0.0),
    )
    ground.set_actor_label(GROUND_LABEL)
    ground.static_mesh_component.set_static_mesh(cube)

    padding = 8000.0
    scale_x = max((half_extent.x + padding) * 2.0 / 100.0, 200.0)
    scale_y = max((half_extent.y + padding) * 2.0 / 100.0, 200.0)
    ground.set_actor_scale3d(unreal.Vector(scale_x, scale_y, 0.5))

    mat, mat_path = load_grass_material()
    if mat is not None:
        ground.static_mesh_component.set_material(0, mat)
        unreal.log("Use grass material: %s" % mat_path)
    else:
        unreal.log_warning("No grass material found in StarterContent; keep default material")

    return ground


def apply_clean_grass_city():
    world = unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        raise RuntimeError("No editor world is open")

    if world.get_name() != TARGET_MAP_NAME:
        raise RuntimeError(
            "Open %s before running this script; current map: %s"
            % (TARGET_MAP_NAME, world.get_name())
        )

    removed, failed = clear_small_city_content()
    center, half_extent, streetmap_count = get_streetmap_bounds()
    spawn_grass_ground(center, half_extent)

    if not unreal.EditorLoadingAndSavingUtils.save_current_level():
        raise RuntimeError("Unable to save EVSmallCity map")

    unreal.log(
        "EVSmallCity cleaned: keep StreetMap=%d, removed=%d, remove_failed=%d, grass_added=1"
        % (streetmap_count, removed, failed)
    )


apply_clean_grass_city()