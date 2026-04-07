import random
from typing import Any, Dict, List, Tuple

import pyproj
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union


_WGS84 = pyproj.CRS("EPSG:4326")


def _utm_crs(lon: float, lat: float) -> pyproj.CRS:
    zone = int((lon + 180) / 6) + 1
    hemi = "north" if lat >= 0 else "south"
    return pyproj.CRS(f"+proj=utm +zone={zone} +{hemi} +datum=WGS84")


def _to_utm(geom, utm: pyproj.CRS):
    t = pyproj.Transformer.from_crs(_WGS84, utm, always_xy=True).transform
    return shapely_transform(t, geom)


def _to_wgs84(geom, utm: pyproj.CRS):
    t = pyproj.Transformer.from_crs(utm, _WGS84, always_xy=True).transform
    return shapely_transform(t, geom)


def _strip_direction(road_facing: str) -> Tuple[str, str]:
    if road_facing == "north":
        return "top", "bottom"
    if road_facing == "east":
        return "right", "left"
    if road_facing == "west":
        return "left", "right"
    return "bottom", "top"


def _carve_strip(base, side: str, target_area: float):
    if base.is_empty or target_area <= 0:
        return None, base
    minx, miny, maxx, maxy = base.bounds
    width = maxx - minx
    height = maxy - miny

    if side in ("bottom", "top"):
        depth = max(1.0, target_area / max(width, 0.1))
        depth = min(depth, height * 0.45)
        if side == "bottom":
            strip_box = box(minx, miny, maxx, miny + depth)
        else:
            strip_box = box(minx, maxy - depth, maxx, maxy)
    else:
        depth = max(1.0, target_area / max(height, 0.1))
        depth = min(depth, width * 0.45)
        if side == "left":
            strip_box = box(minx, miny, minx + depth, maxy)
        else:
            strip_box = box(maxx - depth, miny, maxx, maxy)

    strip = base.intersection(strip_box)
    if strip.is_empty:
        return None, base
    return strip, base.difference(strip)


def _feature(geom, zone: str, color: str, utm: pyproj.CRS) -> Dict[str, Any]:
    geom_wgs = _to_wgs84(geom, utm)
    return {
        "type": "Feature",
        "geometry": mapping(geom_wgs),
        "properties": {
            "zone": zone,
            "area_sqm": round(geom.area, 1),
            "color": color,
        },
    }


def _to_polygons(geom) -> List[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if isinstance(geom, GeometryCollection):
        return [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []


def _limit_parts(geom, max_parts: int):
    polys = sorted(_to_polygons(geom), key=lambda p: p.area, reverse=True)
    if not polys:
        return geom
    if len(polys) <= max_parts:
        return geom
    return unary_union(polys[:max_parts])


def _finalize_layout(zone_geoms: Dict[str, Any], buildable, utm) -> List[Dict[str, Any]]:
    colors = {"building": "#4A90D9", "greenery": "#5cb85c", "parking": "#9B9B9B", "utility": "#c0692a"}
    geoms = [g for g in zone_geoms.values() if g is not None and not g.is_empty]
    used = unary_union(geoms) if geoms else None
    leftover = buildable.difference(used) if used else buildable
    if leftover and not leftover.is_empty:
        if zone_geoms.get("greenery") is None or zone_geoms["greenery"].is_empty:
            zone_geoms["greenery"] = leftover
        else:
            zone_geoms["greenery"] = unary_union([zone_geoms["greenery"], leftover])

    features: List[Dict[str, Any]] = []
    for zone in ("building", "greenery", "parking", "utility"):
        geom = zone_geoms.get(zone)
        if geom is not None and not geom.is_empty:
            f = _feature(geom, zone, colors[zone], utm)
            if f:
                features.append(f)
    return features


def generate_preference_plan(
    plot_geojson: Dict[str, Any],
    split: Dict[str, float],
    road_facing: str,
    num_floors: int,
) -> Dict[str, Any]:
    geom_raw = plot_geojson.get("geometry", plot_geojson)
    plot_wgs = shape(geom_raw)
    if not plot_wgs.is_valid:
        plot_wgs = plot_wgs.buffer(0)

    centroid = plot_wgs.centroid
    utm = _utm_crs(centroid.x, centroid.y)
    plot_utm = _to_utm(plot_wgs, utm)
    if not plot_utm.is_valid:
        plot_utm = plot_utm.buffer(0)

    area = plot_utm.area
    if area < 50:
        raise ValueError("Plot area is too small to generate a site plan.")

    # Uniform buildability inset for cleaner allocations.
    buildable = plot_utm.buffer(-3.0)
    if buildable.is_empty:
        buildable = plot_utm.buffer(-1.0)
    if buildable.is_empty:
        raise ValueError("Could not create a buildable area from this plot.")

    total = split["building"] + split["greenery"] + split["parking"] + split["utility"]
    if total <= 0:
        raise ValueError("Invalid preference split.")
    ratios = {k: v / total for k, v in split.items()}

    front_side, rear_side = _strip_direction(road_facing)
    remaining = buildable
    zone_geoms = {}

    # Parking near road edge.
    parking_target = area * ratios["parking"]
    parking, remaining = _carve_strip(remaining, front_side, parking_target)
    if parking and not parking.is_empty:
        zone_geoms["parking"] = parking

    # Greenery opposite to road edge.
    greenery_target = area * ratios["greenery"]
    greenery, remaining = _carve_strip(remaining, rear_side, greenery_target)
    if greenery and not greenery.is_empty:
        zone_geoms["greenery"] = greenery

    # Utility as a compact corner block.
    utility_target = area * ratios["utility"]
    minx, miny, maxx, maxy = remaining.bounds
    side = max(2.0, utility_target ** 0.5)
    utility_box = box(minx, miny, min(minx + side, maxx), min(miny + side, maxy))
    utility = remaining.intersection(utility_box)
    if utility and not utility.is_empty:
        remaining = remaining.difference(utility)
        zone_geoms["utility"] = _limit_parts(utility, 2)

    # Remaining core is building footprint.
    building = remaining
    if building and not building.is_empty:
        zone_geoms["building"] = building

    features = _finalize_layout(zone_geoms, buildable, utm)

    zone_areas = {f["properties"]["zone"]: f["properties"]["area_sqm"] for f in features}
    building_sqm = zone_areas.get("building", 0.0)
    stats = {
        "plot_area_sqm": round(area, 1),
        "building_sqm": round(building_sqm, 1),
        "greenery_sqm": round(zone_areas.get("greenery", 0.0), 1),
        "parking_sqm": round(zone_areas.get("parking", 0.0), 1),
        "utility_sqm": round(zone_areas.get("utility", 0.0), 1),
        "total_built_up_sqm": round(building_sqm * num_floors, 1),
    }

    return {"plot_area_sqm": round(area, 1), "zones": {"type": "FeatureCollection", "features": features}, "stats": stats}


def _split_to_ratios(split: Dict[str, float]) -> Dict[str, float]:
    total = split["building"] + split["greenery"] + split["parking"] + split["utility"]
    if total <= 0:
        raise ValueError("Invalid preference split.")
    return {k: v / total for k, v in split.items()}


def _zone_stats(features: List[Dict[str, Any]], area: float, floors: int) -> Dict[str, float]:
    zone_areas = {}
    for f in features:
        zone_areas[f["properties"]["zone"]] = zone_areas.get(f["properties"]["zone"], 0.0) + f["properties"]["area_sqm"]
    building_sqm = zone_areas.get("building", 0.0)
    return {
        "plot_area_sqm": round(area, 1),
        "building_sqm": round(building_sqm, 1),
        "greenery_sqm": round(zone_areas.get("greenery", 0.0), 1),
        "parking_sqm": round(zone_areas.get("parking", 0.0), 1),
        "utility_sqm": round(zone_areas.get("utility", 0.0), 1),
        "total_built_up_sqm": round(building_sqm * floors, 1),
    }


def _grid_strategy(buildable, area: float, ratios: Dict[str, float], utm, seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    minx, miny, maxx, maxy = buildable.bounds
    # Smaller cells for finer-grained zoning.
    cell = max(2.0, min((maxx - minx), (maxy - miny)) / 20)
    cells = {}
    i = 0
    x = minx
    while x < maxx:
        j = 0
        y = miny
        while y < maxy:
            c = box(x, y, min(x + cell, maxx), min(y + cell, maxy))
            if buildable.contains(c.centroid):
                cells[(i, j)] = c
            y += cell
            j += 1
        x += cell
        i += 1
    if not cells:
        return {"name": "Grid", "zones": {"type": "FeatureCollection", "features": []}, "stats": _zone_stats([], area, 1)}

    total = len(cells)
    counts = {k: int(ratios[k] * total) for k in ("building", "greenery", "parking", "utility")}
    names = ["building", "greenery", "parking", "utility"]
    colors = {"building": "#4A90D9", "greenery": "#5cb85c", "parking": "#9B9B9B", "utility": "#c0692a"}

    def neighbors(key):
        xk, yk = key
        cand = [(xk + 1, yk), (xk - 1, yk), (xk, yk + 1), (xk, yk - 1)]
        return [k for k in cand if k in cells]

    def connected_pick(available: set, count: int, max_clusters: int = 1):
        if count <= 0 or not available:
            return []
        seed_key = rng.choice(list(available))
        chosen = [seed_key]
        frontier = [seed_key]
        clusters = 1
        available.remove(seed_key)
        while frontier and len(chosen) < count:
            cur = frontier.pop(0)
            nbs = [n for n in neighbors(cur) if n in available]
            rng.shuffle(nbs)
            for n in nbs:
                chosen.append(n)
                frontier.append(n)
                available.remove(n)
                if len(chosen) >= count:
                    break
            if not frontier and len(chosen) < count and available and clusters < max_clusters:
                # Fallback: start another connected cluster from remaining cells.
                nxt = rng.choice(list(available))
                chosen.append(nxt)
                frontier.append(nxt)
                available.remove(nxt)
                clusters += 1
        return chosen

    available = set(cells.keys())
    zone_geoms = {}

    for n in names:
        cluster_limit = 2 if n == "utility" else 1
        pick_keys = connected_pick(available, counts[n], max_clusters=cluster_limit)
        pick = [cells[k] for k in pick_keys]
        if pick:
            geom = pick[0]
            for p in pick[1:]:
                geom = geom.union(p)
            if n == "utility":
                geom = _limit_parts(geom, 2)
            zone_geoms[n] = geom
    features = _finalize_layout(zone_geoms, buildable, utm)
    return {"name": "Grid", "zones": {"type": "FeatureCollection", "features": features}}


def _bsp_parts(poly, depth: int, rng: random.Random):
    if depth == 0:
        return [poly]
    minx, miny, maxx, maxy = poly.bounds
    if rng.random() > 0.5:
        s = rng.uniform(minx, maxx)
        p1 = poly.intersection(box(minx, miny, s, maxy))
        p2 = poly.intersection(box(s, miny, maxx, maxy))
    else:
        s = rng.uniform(miny, maxy)
        p1 = poly.intersection(box(minx, miny, maxx, s))
        p2 = poly.intersection(box(minx, s, maxx, maxy))
    out = []
    for p in (p1, p2):
        if not p.is_empty:
            out.extend(_bsp_parts(p, depth - 1, rng))
    return out


def _bsp_strategy(buildable, area: float, ratios: Dict[str, float], utm, seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    parts = [p for p in _bsp_parts(buildable, 3, rng) if not p.is_empty]
    rng.shuffle(parts)
    total = len(parts)
    counts = {k: int(ratios[k] * total) for k in ("building", "greenery", "parking", "utility")}
    names = ["building", "greenery", "parking", "utility"]
    colors = {"building": "#4A90D9", "greenery": "#5cb85c", "parking": "#9B9B9B", "utility": "#c0692a"}
    zone_geoms = {}
    idx = 0
    for n in names:
        pick = parts[idx:idx + counts[n]]
        idx += counts[n]
        if pick:
            geom = pick[0]
            for p in pick[1:]:
                geom = geom.union(p)
            if n == "utility":
                geom = _limit_parts(geom, 2)
            zone_geoms[n] = geom
    features = _finalize_layout(zone_geoms, buildable, utm)
    return {"name": "BSP", "zones": {"type": "FeatureCollection", "features": features}}


def _heuristic_strategy(buildable, area: float, ratios: Dict[str, float], utm, seed: int) -> Dict[str, Any]:
    _ = seed
    rings = [buildable.buffer(-d) for d in (8, 20, 35)]
    inner = rings[2] if not rings[2].is_empty else rings[1] if not rings[1].is_empty else rings[0]
    building = inner if inner and not inner.is_empty else buildable
    remaining = buildable.difference(building)
    parking, rem2 = _carve_strip(remaining, "bottom", area * ratios["parking"])
    greenery, rem3 = _carve_strip(rem2, "top", area * ratios["greenery"])
    utility, _ = _carve_strip(rem3, "left", area * ratios["utility"])
    if utility and not utility.is_empty:
        utility = _limit_parts(utility, 2)
    zone_geoms = {
        "building": building,
        "greenery": greenery,
        "parking": parking,
        "utility": utility,
    }
    features = _finalize_layout(zone_geoms, buildable, utm)
    return {"name": "Heuristic", "zones": {"type": "FeatureCollection", "features": features}}


def generate_preference_layouts(
    plot_geojson: Dict[str, Any],
    split: Dict[str, float],
    road_facing: str,
    num_floors: int,
) -> Dict[str, Any]:
    geom_raw = plot_geojson.get("geometry", plot_geojson)
    plot_wgs = shape(geom_raw)
    if not plot_wgs.is_valid:
        plot_wgs = plot_wgs.buffer(0)
    centroid = plot_wgs.centroid
    utm = _utm_crs(centroid.x, centroid.y)
    plot_utm = _to_utm(plot_wgs, utm)
    if not plot_utm.is_valid:
        plot_utm = plot_utm.buffer(0)
    area = plot_utm.area
    if area < 50:
        raise ValueError("Plot area is too small to generate a site plan.")
    buildable = plot_utm.buffer(-3.0)
    if buildable.is_empty:
        buildable = plot_utm.buffer(-1.0)
    if buildable.is_empty:
        raise ValueError("Could not create a buildable area from this plot.")
    _ = road_facing
    ratios = _split_to_ratios(split)
    layouts = [
        _grid_strategy(buildable, area, ratios, utm, 11),
        _bsp_strategy(buildable, area, ratios, utm, 29),
        _heuristic_strategy(buildable, area, ratios, utm, 47),
    ]
    for l in layouts:
        l["stats"] = _zone_stats(l["zones"]["features"], area, num_floors)
    return {"plot_area_sqm": round(area, 1), "layouts": layouts}