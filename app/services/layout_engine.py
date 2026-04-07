"""
UrbanScribe Site Layout Engine
Deterministic geometry-based layout generator using Shapely + pyproj.

Input:  GeoJSON Feature (Polygon in WGS84) + config
Output: GeoJSON FeatureCollection of zones + stats dict
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import pyproj
from shapely.geometry import (
    box,
    mapping,
    shape,
    MultiPolygon,
    Polygon,
    GeometryCollection,
)
from shapely.ops import transform as shapely_transform, unary_union

from app.data.zoning_rules import ZONING_RULES
from app.services.compliance_checker import check_compliance


# ─── CRS helpers ──────────────────────────────────────────────────────────────

def _utm_crs(lon: float, lat: float) -> pyproj.CRS:
    zone = int((lon + 180) / 6) + 1
    hemi = "north" if lat >= 0 else "south"
    return pyproj.CRS(f"+proj=utm +zone={zone} +{hemi} +datum=WGS84")


def _transformer(src: pyproj.CRS, dst: pyproj.CRS):
    return pyproj.Transformer.from_crs(src, dst, always_xy=True).transform


_WGS84 = pyproj.CRS("EPSG:4326")


def _to_utm(geom, utm: pyproj.CRS):
    return shapely_transform(_transformer(_WGS84, utm), geom)


def _to_wgs84(geom, utm: pyproj.CRS):
    return shapely_transform(_transformer(utm, _WGS84), geom)


# ─── Geometry helpers ─────────────────────────────────────────────────────────

def _fix(geom):
    """Fix potentially invalid geometry."""
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def _largest_polygon(geom) -> Optional[Polygon]:
    """Return the largest polygon from a geometry (handles Multi/Collection)."""
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        polys = [g for g in geom.geoms if isinstance(g, Polygon)]
        return max(polys, key=lambda p: p.area) if polys else None
    return None


def _setback_polygon(plot_utm: Polygon, rules: Dict, road_facing: str) -> Polygon:
    """
    Apply directional setbacks.
    Strategy: find bounding box edges, assign front/rear/side setbacks
    based on road_facing direction, then clip.
    """
    minx, miny, maxx, maxy = plot_utm.bounds
    w = maxx - minx
    h = maxy - miny

    # Map road_facing to bounding-box offsets
    offsets = {
        "south": dict(left=rules["setback_side"],  right=rules["setback_side"],
                      bottom=rules["setback_front"], top=rules["setback_rear"]),
        "north": dict(left=rules["setback_side"],  right=rules["setback_side"],
                      bottom=rules["setback_rear"],  top=rules["setback_front"]),
        "west":  dict(left=rules["setback_front"], right=rules["setback_rear"],
                      bottom=rules["setback_side"],  top=rules["setback_side"]),
        "east":  dict(left=rules["setback_rear"],  right=rules["setback_front"],
                      bottom=rules["setback_side"],  top=rules["setback_side"]),
    }.get(road_facing, dict(left=rules["setback_side"], right=rules["setback_side"],
                            bottom=rules["setback_front"], top=rules["setback_rear"]))

    sb_box = box(
        minx + offsets["left"],
        miny + offsets["bottom"],
        maxx - offsets["right"],
        maxy - offsets["top"],
    )
    buildable = _fix(plot_utm.intersection(sb_box))
    return buildable


def _shrink_to_coverage(geom: Polygon, target_area: float) -> Polygon:
    """Iteratively shrink a polygon until its area ≤ target_area."""
    if geom.area <= target_area:
        return geom
    step = 0.5  # metres per iteration
    current = geom
    for _ in range(200):
        if current.area <= target_area:
            break
        shrunk = current.buffer(-step)
        if shrunk.is_empty or shrunk.area < 1:
            break
        p = _largest_polygon(shrunk)
        if p is None:
            break
        current = _fix(p)
    return current


def _strip(base: Polygon, direction: str, area_needed: float, min_strip: float = 2.0
           ) -> Tuple[Optional[Polygon], Polygon]:
    """
    Carve a rectangular strip of approx area_needed sqm from `base`,
    aligned to the specified edge direction.
    Returns (strip_polygon, remainder).
    """
    if base.is_empty or area_needed < 1:
        return None, base

    minx, miny, maxx, maxy = base.bounds
    bw = maxx - minx
    bh = maxy - miny

    if direction in ("bottom", "south"):
        strip_h = max(min_strip, area_needed / max(bw, 0.1))
        strip_h = min(strip_h, bh * 0.4)
        strip_rect = box(minx, miny, maxx, miny + strip_h)
    elif direction in ("top", "north"):
        strip_h = max(min_strip, area_needed / max(bw, 0.1))
        strip_h = min(strip_h, bh * 0.4)
        strip_rect = box(minx, maxy - strip_h, maxx, maxy)
    elif direction in ("left", "west"):
        strip_w = max(min_strip, area_needed / max(bh, 0.1))
        strip_w = min(strip_w, bw * 0.4)
        strip_rect = box(minx, miny, minx + strip_w, maxy)
    else:  # right / east
        strip_w = max(min_strip, area_needed / max(bh, 0.1))
        strip_w = min(strip_w, bw * 0.4)
        strip_rect = box(maxx - strip_w, miny, maxx, maxy)

    strip = _fix(base.intersection(strip_rect))
    if strip.is_empty or strip.area < 1:
        return None, base

    remainder = _fix(base.difference(strip))
    return strip, remainder


def _road_opposite(road_facing: str) -> str:
    return {"south": "top", "north": "bottom",
            "west": "right", "east": "left"}.get(road_facing, "top")


def _feature(geom_utm, zone: str, label: str, color: str, utm: pyproj.CRS,
             extra_props: Optional[Dict] = None) -> Optional[Dict]:
    if geom_utm is None or geom_utm.is_empty or geom_utm.area < 0.5:
        return None
    p = _largest_polygon(geom_utm)
    if p is None:
        return None
    geom_wgs = _to_wgs84(p, utm)
    props = {"zone": zone, "label": label, "color": color,
             "area_sqm": round(p.area, 1)}
    if extra_props:
        props.update(extra_props)
    return {"type": "Feature", "geometry": mapping(geom_wgs), "properties": props}


# ─── Main entry point ─────────────────────────────────────────────────────────

def generate_layout(
    plot_geojson: Dict[str, Any],
    zone_type: str,
    num_floors: int,
    road_facing: str,
    preferences: Dict[str, bool],
) -> Dict[str, Any]:
    """
    Generate a deterministic site layout.
    Returns dict with keys: features (list), area_sqm, building_footprint_sqm,
    garden_sqm, parking_sqm, parking_spaces, open_space_sqm, compliance.
    """
    rules = ZONING_RULES.get(zone_type)
    if rules is None:
        raise ValueError(f"Unknown zone_type '{zone_type}'")

    # ── 1. Parse + validate ──────────────────────────────────────────────────
    geom_raw = plot_geojson.get("geometry", plot_geojson)
    plot_wgs = _fix(shape(geom_raw))

    centroid = plot_wgs.centroid
    utm = _utm_crs(centroid.x, centroid.y)

    plot_utm = _fix(_to_utm(plot_wgs, utm))
    area_sqm = plot_utm.area

    if area_sqm < rules["min_plot_sqm"]:
        raise ValueError(
            f"Plot area {area_sqm:.0f} sqm is below the minimum "
            f"{rules['min_plot_sqm']} sqm for {zone_type} zone."
        )

    # ── 2. Setbacks → buildable envelope ────────────────────────────────────
    buildable = _setback_polygon(plot_utm, rules, road_facing)
    buildable = _largest_polygon(buildable)
    if buildable is None or buildable.is_empty:
        raise ValueError("Plot is too small to satisfy the required setbacks.")

    setback_zone = _fix(plot_utm.difference(buildable))

    # ── 3. Building footprint ─────────────────────────────────────────────────
    max_footprint = area_sqm * rules["ground_coverage"]
    building_footprint = _shrink_to_coverage(buildable, max_footprint)
    building_footprint_sqm = building_footprint.area

    # ── 4. Remaining open land ────────────────────────────────────────────────
    remaining = _fix(plot_utm.difference(building_footprint))

    # ── 5. Garden  (rear of the plot, opposite the road) ─────────────────────
    garden: Optional[Polygon] = None
    garden_sqm = 0.0
    if preferences.get("garden", True):
        garden_target = area_sqm * rules["garden_pct"] / 100
        garden_dir = _road_opposite(road_facing)
        garden, remaining = _strip(remaining, garden_dir, garden_target)
        if garden:
            garden_sqm = garden.area

    # ── 6. Parking (near road, same side as road_facing) ─────────────────────
    parking: Optional[Polygon] = None
    parking_sqm = 0.0
    parking_spaces = 0
    if preferences.get("parking", True):
        total_built = building_footprint_sqm * num_floors
        parking_spaces = max(1, int(total_built / 100 * rules["parking_ratio"]))
        parking_area_needed = parking_spaces * 12.5   # 2.5m × 5m per bay
        park_dir = {"south": "bottom", "north": "top",
                    "west": "left", "east": "right"}.get(road_facing, "bottom")
        parking, remaining = _strip(remaining, park_dir, parking_area_needed)
        if parking:
            parking_sqm = parking.area

    # ── 7. Utility room (small corner, away from garden) ─────────────────────
    utilities: Optional[Polygon] = None
    if preferences.get("utilities_room", True) and not remaining.is_empty:
        util_target = 9.0  # 3m × 3m
        util_dir = {"south": "right", "north": "left",
                    "west": "bottom", "east": "top"}.get(road_facing, "right")
        utilities, remaining = _strip(remaining, util_dir, util_target, min_strip=2.5)

    # ── 8. Compliance check ───────────────────────────────────────────────────
    compliance = check_compliance(
        plot_area=area_sqm,
        building_footprint_sqm=building_footprint_sqm,
        garden_sqm=garden_sqm,
        parking_spaces=parking_spaces,
        num_floors=num_floors,
        rules=rules,
    )

    # ── 9. Assemble GeoJSON features ──────────────────────────────────────────
    features: List[Dict] = []

    def push(geom, zone, label, color, extra=None):
        f = _feature(geom, zone, label, color, utm, extra)
        if f:
            features.append(f)

    push(setback_zone,        "setback",            "Setback Zone",       "#e8a020")
    push(building_footprint,  "building_footprint", "Building Footprint", "#4A90D9",
         {"floors": num_floors,
          "total_built_up_sqm": round(building_footprint_sqm * num_floors, 1)})
    if garden:
        push(garden,  "garden",    "Garden / Green Space", "#5cb85c")
    if parking:
        push(parking, "parking",   "Parking Area",         "#9B9B9B",
             {"parking_spaces": parking_spaces})
    if utilities:
        push(utilities, "utilities", "Utility Room",       "#c0692a")

    open_space_sqm = area_sqm - building_footprint_sqm

    return {
        "features": features,
        "area_sqm": round(area_sqm, 1),
        "building_footprint_sqm": round(building_footprint_sqm, 1),
        "total_built_up_sqm": round(building_footprint_sqm * num_floors, 1),
        "garden_sqm": round(garden_sqm, 1),
        "parking_sqm": round(parking_sqm, 1),
        "parking_spaces": parking_spaces,
        "open_space_sqm": round(open_space_sqm, 1),
        "compliance": compliance,
    }