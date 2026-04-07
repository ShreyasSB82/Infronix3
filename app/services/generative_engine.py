"""
Generative Site Planning Engine
Generates multiple diverse layout options using pluggable spatial strategies.

Strategies
----------
HeuristicStrategy  — Rule-based directional strips (parking near road, green rear)
GridStrategy       — Regular grid cells assigned by proximity scoring
BSPStrategy        — Binary Space Partitioning recursive splits
CompactStrategy    — Concentric rings: green belt → parking front → building core
PerimeterStrategy  — Green perimeter ring, building fills central mass

Input
-----
plot_geojson  : GeoJSON Feature or Geometry (Polygon, WGS84)
preferences   : {"building": 0.4, "green": 0.3, "parking": 0.2, "utility": 0.1}
                values are fractions (0–1) summing to 1.0
constraints   : {"setback_m": 3.0, "road_width_m": 6.0,
                 "road_facing": "south", "num_floors": 3}

Output
------
List of layout dicts sorted by score (best first).
Each layout: {layout_id, strategy, zones (GeoJSON FC), stats, score, score_breakdown}
"""

from __future__ import annotations

import math
import random
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyproj
from shapely.geometry import (
    GeometryCollection,
    MultiPolygon,
    Point,
    Polygon,
    box,
    mapping,
    shape,
)
from shapely.ops import transform as shapely_transform, unary_union


# ─── CRS helpers ──────────────────────────────────────────────────────────────

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


# ─── Geometry helpers ─────────────────────────────────────────────────────────

def _fix(geom):
    """Return a valid geometry (buffer(0) trick)."""
    if geom is None or geom.is_empty:
        return geom
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def _largest_poly(geom) -> Optional[Polygon]:
    """Extract the largest polygon from any geometry type."""
    if isinstance(geom, Polygon):
        return geom if not geom.is_empty else None
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        polys = [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
        return max(polys, key=lambda p: p.area) if polys else None
    return None


def _safe_intersection(a, b) -> Optional[object]:
    try:
        result = _fix(a.intersection(b))
        return result if (result and not result.is_empty) else None
    except Exception:
        return None


def _safe_difference(a, b):
    try:
        result = _fix(a.difference(b))
        return result if (result and not result.is_empty) else a
    except Exception:
        return a


def _shrink_to_target(geom: Polygon, target_area: float) -> Optional[Polygon]:
    """Iteratively buffer inward until area ≤ target_area."""
    if geom is None or geom.is_empty:
        return None
    if geom.area <= target_area * 1.05:
        return geom
    excess = geom.area - target_area
    step = max(0.3, min(math.sqrt(excess) * 0.05, 2.0))
    current = geom
    for _ in range(200):
        if current.area <= target_area * 1.05:
            break
        shrunk = current.buffer(-step)
        if shrunk is None or shrunk.is_empty or shrunk.area < 1.0:
            break
        p = _largest_poly(shrunk)
        if p is None:
            break
        current = _fix(p)
    return current


# ─── Zone metadata ────────────────────────────────────────────────────────────

ZONE_COLORS = {
    "building": "#4A90D9",
    "green":    "#5cb85c",
    "parking":  "#9B9B9B",
    "utility":  "#c0692a",
    "setback":  "#e8a020",
}

ZONE_LABELS = {
    "building": "Building Footprint",
    "green":    "Green Space",
    "parking":  "Parking Area",
    "utility":  "Utility Zone",
    "setback":  "Setback Zone",
}


def _make_feature(geom_utm, zone: str, utm, extra: dict = None) -> Optional[dict]:
    """Convert a UTM geometry to a WGS84 GeoJSON Feature."""
    if geom_utm is None or geom_utm.is_empty:
        return None
    p = _largest_poly(geom_utm) if not isinstance(geom_utm, Polygon) else geom_utm
    if p is None or p.area < 0.5:
        return None
    geom_wgs = _to_wgs84(p, utm)
    props = {
        "zone":     zone,
        "label":    ZONE_LABELS.get(zone, zone),
        "color":    ZONE_COLORS.get(zone, "#888"),
        "area_sqm": round(p.area, 1),
    }
    if extra:
        props.update(extra)
    return {"type": "Feature", "geometry": mapping(geom_wgs), "properties": props}


# ─── Input data classes ───────────────────────────────────────────────────────

@dataclass
class LayoutPreferences:
    building: float   # fraction 0–1
    green: float
    parking: float
    utility: float

    def validate(self):
        total = self.building + self.green + self.parking + self.utility
        if abs(total - 1.0) > 0.02:
            raise ValueError(f"Preferences must sum to 1.0, got {total:.3f}")
        for name, val in self.__dict__.items():
            if val < 0:
                raise ValueError(f"'{name}' cannot be negative")

    def as_dict(self) -> Dict[str, float]:
        return {
            "building": self.building,
            "green":    self.green,
            "parking":  self.parking,
            "utility":  self.utility,
        }


@dataclass
class LayoutConstraints:
    setback_m: float = 3.0
    road_width_m: float = 6.0
    road_facing: str = "south"   # north | south | east | west
    num_floors: int = 3


# ─── Setback helper ───────────────────────────────────────────────────────────

def _apply_setback(
    plot: Polygon,
    setback: float,
    road_facing: str,
) -> Tuple[Polygon, object]:
    """
    Apply uniform setback. Returns (buildable_polygon, setback_zone_geometry).
    """
    buildable = _fix(plot.buffer(-max(0.5, setback)))
    if buildable is None or buildable.is_empty:
        # Too small — use 10% inset
        buildable = _fix(plot.buffer(-max(0.1, plot.area**0.5 * 0.05)))
    p = _largest_poly(buildable)
    if p is None:
        p = plot
    setback_zone = _fix(plot.difference(p))
    return p, setback_zone


# ─── Road proximity helpers ───────────────────────────────────────────────────

def _road_dist_normalized(cx: float, cy: float, bounds, road_facing: str) -> float:
    """
    Returns 0 when centroid is AT the road edge, 1 when at opposite edge.
    """
    minx, miny, maxx, maxy = bounds
    w = max(maxx - minx, 0.1)
    h = max(maxy - miny, 0.1)
    if road_facing == "south":   return (cy - miny) / h
    if road_facing == "north":   return (maxy - cy) / h
    if road_facing == "east":    return (maxx - cx) / w
    if road_facing == "west":    return (cx - minx) / w
    return 0.5


def _opposite_facing(rf: str) -> str:
    return {"south": "north", "north": "south", "east": "west", "west": "east"}.get(rf, "north")


def _strip_rect(bounds, side: str, depth: float) -> Polygon:
    """Return a thin rectangle cut from the specified side of the bounding box."""
    minx, miny, maxx, maxy = bounds
    if side == "south":   return box(minx, miny,           maxx, miny + depth)
    if side == "north":   return box(minx, maxy - depth,   maxx, maxy)
    if side == "west":    return box(minx, miny,           minx + depth, maxy)
    if side == "east":    return box(maxx - depth, miny,   maxx, maxy)
    return box(minx, miny, maxx, miny + depth)


def _strip_depth(target_area: float, bounds, side: str, fraction_cap: float = 0.4) -> float:
    minx, miny, maxx, maxy = bounds
    if side in ("south", "north"):
        span = max(maxx - minx, 0.1)
        cap  = (maxy - miny) * fraction_cap
    else:
        span = max(maxy - miny, 0.1)
        cap  = (maxx - minx) * fraction_cap
    depth = max(2.0, target_area / span)
    return min(depth, cap)


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY BASE
# ══════════════════════════════════════════════════════════════════════════════

# A raw feature tuple: (zone_name, shapely_geom_utm, extra_props_dict)
RawFeature = Tuple[str, object, dict]


class LayoutStrategy(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    def generate(
        self,
        plot_utm: Polygon,
        prefs: LayoutPreferences,
        constraints: LayoutConstraints,
        rng: random.Random,
    ) -> List[RawFeature]:
        """
        Generate zone geometries (in UTM coordinates).
        Returns list of (zone_name, shapely_geom, extra_props).
        """


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 1 — HEURISTIC (directional strips)
# ══════════════════════════════════════════════════════════════════════════════

class HeuristicStrategy(LayoutStrategy):
    name = "heuristic"
    description = "Rule-based directional strips: parking near road, green at rear"

    def generate(self, plot_utm, prefs, constraints, rng):
        area = plot_utm.area
        buildable, sb_geom = _apply_setback(plot_utm, constraints.setback_m, constraints.road_facing)
        features: List[RawFeature] = []
        if sb_geom and not sb_geom.is_empty:
            features.append(("setback", sb_geom, {}))

        remaining = buildable
        rf = constraints.road_facing

        # 1. Parking — strip along road side
        parking_target = area * prefs.parking
        depth = _strip_depth(parking_target * rng.uniform(0.9, 1.1), remaining.bounds, rf)
        strip = _safe_intersection(remaining, _strip_rect(remaining.bounds, rf, depth))
        if strip and strip.area > 1.0:
            features.append(("parking", strip, {}))
            remaining = _fix(remaining.difference(strip))

        # 2. Green — strip at opposite (rear) side
        green_target = area * prefs.green
        rear = _opposite_facing(rf)
        depth = _strip_depth(green_target * rng.uniform(0.9, 1.1), remaining.bounds, rear)
        strip = _safe_intersection(remaining, _strip_rect(remaining.bounds, rear, depth))
        if strip and strip.area > 1.0:
            features.append(("green", strip, {}))
            remaining = _fix(remaining.difference(strip))

        # 3. Utility — small corner, away from road
        util_target = area * prefs.utility
        util = self._carve_corner(remaining, rf, util_target, rng)
        if util and util.area > 1.0:
            features.append(("utility", util, {}))
            remaining = _fix(remaining.difference(util))

        # 4. Building — central remainder (trimmed to target)
        building_target = area * prefs.building
        building = _shrink_to_target(remaining, building_target)
        if building and not building.is_empty:
            features.append(("building", building, {"num_floors": constraints.num_floors}))

        return features

    def _carve_corner(self, base, road_facing, target_area, rng):
        if base is None or base.is_empty or target_area < 1:
            return None
        minx, miny, maxx, maxy = base.bounds
        side = max(2.0, math.sqrt(target_area) * rng.uniform(0.9, 1.1))
        # prefer corner away from road
        corner_options = {
            "south": [box(minx, maxy-side, minx+side, maxy), box(maxx-side, maxy-side, maxx, maxy)],
            "north": [box(minx, miny, minx+side, miny+side), box(maxx-side, miny, maxx, miny+side)],
            "east":  [box(minx, miny, minx+side, miny+side), box(minx, maxy-side, minx+side, maxy)],
            "west":  [box(maxx-side, miny, maxx, miny+side), box(maxx-side, maxy-side, maxx, maxy)],
        }
        options = corner_options.get(road_facing, corner_options["south"])
        rect = rng.choice(options)
        result = _safe_intersection(base, rect)
        return _largest_poly(result) if result else None


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 2 — GRID (cell assignment by proximity)
# ══════════════════════════════════════════════════════════════════════════════

class GridStrategy(LayoutStrategy):
    name = "grid"
    description = "Regular grid cells assigned to zones by scored proximity"

    def generate(self, plot_utm, prefs, constraints, rng):
        area = plot_utm.area
        buildable, sb_geom = _apply_setback(plot_utm, constraints.setback_m, constraints.road_facing)
        features: List[RawFeature] = []
        if sb_geom and not sb_geom.is_empty:
            features.append(("setback", sb_geom, {}))

        # Grid cell size targeting ~25 cells
        n_cells = rng.randint(20, 35)
        cell_side = max(2.0, math.sqrt(buildable.area / n_cells))

        minx, miny, maxx, maxy = buildable.bounds
        cells = []
        x = minx
        while x < maxx:
            y = miny
            while y < maxy:
                cell = box(x, y, min(x + cell_side, maxx), min(y + cell_side, maxy))
                clipped = _safe_intersection(buildable, cell)
                if clipped and clipped.area > cell_side * cell_side * 0.08:
                    cells.append({
                        "geom": clipped,
                        "area": clipped.area,
                        "cx":   clipped.centroid.x,
                        "cy":   clipped.centroid.y,
                    })
                y += cell_side
            x += cell_side

        if not cells:
            return features

        bounds = buildable.bounds
        cx_c = (bounds[0] + bounds[2]) / 2
        cy_c = (bounds[1] + bounds[3]) / 2
        max_d = max(bounds[2]-bounds[0], bounds[3]-bounds[1])

        for c in cells:
            nd   = _road_dist_normalized(c["cx"], c["cy"], bounds, constraints.road_facing)
            dc   = math.hypot(c["cx"] - cx_c, c["cy"] - cy_c) / max(max_d, 0.1)
            jitter = rng.uniform(-0.06, 0.06)
            c["score"] = {
                "parking":  nd          + jitter,
                "green":    1.0 - nd    + jitter,
                "utility":  dc + 0.5    + jitter,
                "building": dc          + jitter,
            }

        targets = {
            "parking":  area * prefs.parking,
            "green":    area * prefs.green,
            "utility":  area * prefs.utility,
            "building": area * prefs.building,
        }
        assigned: Dict[str, List] = {z: [] for z in targets}
        assigned_area = {z: 0.0 for z in targets}
        pool = list(cells)

        for zone in ["parking", "utility", "green", "building"]:
            pool.sort(key=lambda c: c["score"][zone])
            for c in list(pool):
                if assigned_area[zone] >= targets[zone] * 0.92:
                    break
                assigned[zone].append(c["geom"])
                assigned_area[zone] += c["area"]
                pool.remove(c)

        # Overflow → building
        for c in pool:
            assigned["building"].append(c["geom"])

        for zone in ["parking", "green", "utility", "building"]:
            geoms = assigned[zone]
            if not geoms:
                continue
            merged = _fix(unary_union(geoms))
            if merged and not merged.is_empty:
                extra = {"num_floors": constraints.num_floors} if zone == "building" else {}
                features.append((zone, merged, extra))

        return features


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 3 — BSP (Binary Space Partitioning)
# ══════════════════════════════════════════════════════════════════════════════

class BSPStrategy(LayoutStrategy):
    name = "bsp"
    description = "Recursive binary splits produce organic rectangular zone shapes"

    def generate(self, plot_utm, prefs, constraints, rng):
        area = plot_utm.area
        buildable, sb_geom = _apply_setback(plot_utm, constraints.setback_m, constraints.road_facing)
        features: List[RawFeature] = []
        if sb_geom and not sb_geom.is_empty:
            features.append(("setback", sb_geom, {}))

        # BSP on bounding box, clip leaves to buildable polygon
        minx, miny, maxx, maxy = buildable.bounds
        leaves = self._split(box(minx, miny, maxx, maxy),
                             depth=0, max_depth=3,
                             min_area=area * 0.025, rng=rng)

        bounds = buildable.bounds
        cx_c = (bounds[0] + bounds[2]) / 2
        cy_c = (bounds[1] + bounds[3]) / 2
        max_d = max(bounds[2]-bounds[0], bounds[3]-bounds[1])

        scored = []
        for leaf in leaves:
            clipped = _safe_intersection(buildable, leaf)
            if clipped is None or clipped.area < 1.0:
                continue
            cx, cy = clipped.centroid.x, clipped.centroid.y
            nd = _road_dist_normalized(cx, cy, bounds, constraints.road_facing)
            dc = math.hypot(cx - cx_c, cy - cy_c) / max(max_d, 0.1)
            jitter = rng.uniform(-0.08, 0.08)
            scored.append({
                "geom": clipped,
                "area": clipped.area,
                "score": {
                    "parking":  nd          + jitter,
                    "green":    1.0 - nd    + jitter,
                    "utility":  dc + 0.5    + jitter,
                    "building": dc          + jitter,
                },
            })

        targets = {
            "parking":  area * prefs.parking,
            "green":    area * prefs.green,
            "utility":  area * prefs.utility,
            "building": area * prefs.building,
        }
        assigned: Dict[str, List] = {z: [] for z in targets}
        assigned_area = {z: 0.0 for z in targets}
        pool = list(scored)

        for zone in ["parking", "utility", "green", "building"]:
            pool.sort(key=lambda c: c["score"][zone])
            for leaf in list(pool):
                if assigned_area[zone] >= targets[zone] * 0.92:
                    break
                assigned[zone].append(leaf["geom"])
                assigned_area[zone] += leaf["area"]
                pool.remove(leaf)

        for leaf in pool:
            assigned["building"].append(leaf["geom"])

        for zone in ["parking", "green", "utility", "building"]:
            geoms = assigned[zone]
            if not geoms:
                continue
            merged = _fix(unary_union(geoms))
            if merged and not merged.is_empty:
                extra = {"num_floors": constraints.num_floors} if zone == "building" else {}
                features.append((zone, merged, extra))

        return features

    def _split(self, rect: Polygon, depth: int, max_depth: int,
               min_area: float, rng: random.Random) -> List[Polygon]:
        if depth >= max_depth or rect.area < min_area * 2:
            return [rect]
        minx, miny, maxx, maxy = rect.bounds
        w = maxx - minx
        h = maxy - miny

        # Prefer to split the longer axis; add small random bias
        split_h = (w > h * 1.1) or (w >= h and rng.random() < 0.5)
        if split_h:
            s = minx + rng.uniform(0.35, 0.65) * w
            return (self._split(box(minx, miny, s, maxy),    depth+1, max_depth, min_area, rng) +
                    self._split(box(s,    miny, maxx, maxy), depth+1, max_depth, min_area, rng))
        else:
            s = miny + rng.uniform(0.35, 0.65) * h
            return (self._split(box(minx, miny, maxx, s),    depth+1, max_depth, min_area, rng) +
                    self._split(box(minx, s,    maxx, maxy), depth+1, max_depth, min_area, rng))


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 4 — COMPACT (concentric rings)
# ══════════════════════════════════════════════════════════════════════════════

class CompactStrategy(LayoutStrategy):
    name = "compact"
    description = "Concentric rings: outer green belt → parking front → utility corner → building core"

    def generate(self, plot_utm, prefs, constraints, rng):
        area = plot_utm.area
        buildable, sb_geom = _apply_setback(plot_utm, constraints.setback_m, constraints.road_facing)
        features: List[RawFeature] = []
        if sb_geom and not sb_geom.is_empty:
            features.append(("setback", sb_geom, {}))

        # Green: outer ring inset from buildable
        green_target = area * prefs.green
        thickness = max(1.5, min(math.sqrt(green_target) * rng.uniform(0.4, 0.65),
                                 math.sqrt(buildable.area) * 0.25))
        inner = _fix(buildable.buffer(-thickness))
        inner_poly = _largest_poly(inner)

        if inner_poly and inner_poly.area > area * 0.04:
            green_ring = _fix(buildable.difference(inner_poly))
            if green_ring and not green_ring.is_empty:
                features.append(("green", green_ring, {}))
            zone = inner_poly
        else:
            zone = buildable

        # Parking: front strip
        rf = constraints.road_facing
        parking_target = area * prefs.parking
        depth = _strip_depth(parking_target * rng.uniform(0.9, 1.1), zone.bounds, rf, 0.32)
        strip = _safe_intersection(zone, _strip_rect(zone.bounds, rf, depth))
        if strip and strip.area > 1.0:
            features.append(("parking", strip, {}))
            zone = _fix(zone.difference(strip))

        # Utility: corner
        if zone and not zone.is_empty:
            util_target = area * prefs.utility
            side = max(2.0, math.sqrt(util_target) * rng.uniform(0.88, 1.1))
            minx, miny, maxx, maxy = zone.bounds
            options = {
                "south": [box(minx, maxy-side, minx+side, maxy), box(maxx-side, maxy-side, maxx, maxy)],
                "north": [box(minx, miny, minx+side, miny+side), box(maxx-side, miny, maxx, miny+side)],
                "east":  [box(minx, miny, minx+side, miny+side), box(minx, maxy-side, minx+side, maxy)],
                "west":  [box(maxx-side, miny, maxx, miny+side), box(maxx-side, maxy-side, maxx, maxy)],
            }
            rect = rng.choice(options.get(rf, options["south"]))
            util = _safe_intersection(zone, rect)
            if util and util.area > 1.0:
                features.append(("utility", util, {}))
                zone = _fix(zone.difference(util))

        # Building: central core
        if zone and not zone.is_empty:
            building = _shrink_to_target(zone, area * prefs.building)
            if building and not building.is_empty:
                features.append(("building", building, {"num_floors": constraints.num_floors}))

        return features


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 5 — PERIMETER (green boundary wrap)
# ══════════════════════════════════════════════════════════════════════════════

class PerimeterStrategy(LayoutStrategy):
    name = "perimeter"
    description = "Green perimeter belt wraps the plot boundary; building occupies central mass"

    def generate(self, plot_utm, prefs, constraints, rng):
        area = plot_utm.area
        buildable, sb_geom = _apply_setback(plot_utm, constraints.setback_m, constraints.road_facing)
        features: List[RawFeature] = []
        if sb_geom and not sb_geom.is_empty:
            features.append(("setback", sb_geom, {}))

        # Green: perimeter-proportional thickness
        green_target = area * prefs.green
        perimeter = buildable.length
        thickness = max(1.5, min(green_target / max(perimeter, 1.0) * rng.uniform(0.85, 1.15),
                                 math.sqrt(buildable.area) * 0.28))
        inner = _fix(buildable.buffer(-thickness))
        inner_poly = _largest_poly(inner)

        if inner_poly and inner_poly.area > area * 0.04:
            green_ring = _fix(buildable.difference(inner_poly))
            if green_ring and not green_ring.is_empty:
                features.append(("green", green_ring, {}))
            zone = inner_poly
        else:
            zone = buildable

        rf = constraints.road_facing

        # Parking: front strip
        parking_target = area * prefs.parking
        if zone and not zone.is_empty:
            depth = _strip_depth(parking_target * rng.uniform(0.9, 1.1), zone.bounds, rf, 0.3)
            strip = _safe_intersection(zone, _strip_rect(zone.bounds, rf, depth))
            if strip and strip.area > 1.0:
                features.append(("parking", strip, {}))
                zone = _fix(zone.difference(strip))

        # Utility: corner opposite road
        if zone and not zone.is_empty:
            util_target = area * prefs.utility
            side = max(2.0, math.sqrt(util_target) * rng.uniform(0.88, 1.1))
            minx, miny, maxx, maxy = zone.bounds
            rear_corners = {
                "south": box(minx, maxy-side, minx+side, maxy),
                "north": box(minx, miny, minx+side, miny+side),
                "east":  box(minx, maxy-side, minx+side, maxy),
                "west":  box(maxx-side, miny, maxx, miny+side),
            }
            rect = rear_corners.get(rf, rear_corners["south"])
            util = _safe_intersection(zone, rect)
            if util and util.area > 1.0:
                features.append(("utility", util, {}))
                zone = _fix(zone.difference(util))

        # Building: remaining central area
        if zone and not zone.is_empty:
            building = _shrink_to_target(zone, area * prefs.building)
            if building and not building.is_empty:
                features.append(("building", building, {"num_floors": constraints.num_floors}))

        return features


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score_layout(
    raw_features: List[RawFeature],
    prefs: LayoutPreferences,
    plot_area: float,
) -> Tuple[float, Dict[str, float]]:
    """
    Score a layout on four dimensions.
    Returns (total_score_0_to_1, breakdown_dict).
    """
    zone_areas: Dict[str, float] = {}
    for zone, geom, _ in raw_features:
        if zone == "setback":
            continue
        p = _largest_poly(geom) if not isinstance(geom, Polygon) else geom
        if p and not p.is_empty:
            zone_areas[zone] = zone_areas.get(zone, 0.0) + p.area

    # 1. Area accuracy — how close actual zone areas are to targets
    targets = {
        "building": plot_area * prefs.building,
        "green":    plot_area * prefs.green,
        "parking":  plot_area * prefs.parking,
        "utility":  plot_area * prefs.utility,
    }
    error = 0.0
    for zone, t in targets.items():
        if t > 0:
            error += abs(zone_areas.get(zone, 0.0) - t) / t
    area_accuracy = max(0.0, 1.0 - error / 4)

    # 2. Compactness — zone area / convex hull area ratio
    compact_vals = []
    for zone, geom, _ in raw_features:
        if zone == "setback":
            continue
        p = _largest_poly(geom) if not isinstance(geom, Polygon) else geom
        if p and not p.is_empty:
            ch_area = p.convex_hull.area
            if ch_area > 0:
                compact_vals.append(min(1.0, p.area / ch_area))
    compactness = float(np.mean(compact_vals)) if compact_vals else 0.5

    # 3. Regularity — zone area / bounding box area (penalises jagged shapes)
    reg_vals = []
    for zone, geom, _ in raw_features:
        if zone == "setback":
            continue
        p = _largest_poly(geom) if not isinstance(geom, Polygon) else geom
        if p and not p.is_empty:
            bx = (p.bounds[2] - p.bounds[0]) * (p.bounds[3] - p.bounds[1])
            if bx > 0:
                reg_vals.append(min(1.0, p.area / bx))
    regularity = float(np.mean(reg_vals)) if reg_vals else 0.5

    # 4. Coverage — how close building fraction is to target
    building_frac = zone_areas.get("building", 0.0) / max(plot_area, 1.0)
    coverage = max(0.0, 1.0 - abs(building_frac - prefs.building) * 3)

    total = (
        0.45 * area_accuracy +
        0.20 * compactness  +
        0.20 * regularity   +
        0.15 * coverage
    )
    return round(max(0.0, min(1.0, total)), 3), {
        "area_accuracy": round(area_accuracy, 3),
        "compactness":   round(compactness,   3),
        "regularity":    round(regularity,    3),
        "coverage":      round(coverage,      3),
    }


# ─── Registered strategies ────────────────────────────────────────────────────

_STRATEGIES: List[LayoutStrategy] = [
    HeuristicStrategy(),
    GridStrategy(),
    BSPStrategy(),
    CompactStrategy(),
    PerimeterStrategy(),
]


def list_strategies() -> List[Dict[str, str]]:
    """Return metadata for all available strategies."""
    return [{"name": s.name, "description": s.description} for s in _STRATEGIES]


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_multiple_layouts(
    plot_geojson: Dict[str, Any],
    preferences: Dict[str, float],
    constraints: Dict[str, Any],
    n_layouts: int = 5,
) -> List[Dict[str, Any]]:
    """
    Generate n_layouts diverse site plan options.

    Parameters
    ----------
    plot_geojson
        GeoJSON Feature or Geometry (Polygon, WGS84 [lng, lat]).
    preferences
        Fractional area allocations, e.g. {"building":0.4,"green":0.3,"parking":0.2,"utility":0.1}.
        Must sum to 1.0.
    constraints
        {"setback_m":3.0, "road_width_m":6.0, "road_facing":"south", "num_floors":3}
    n_layouts
        Number of top layouts to return (2–8).

    Returns
    -------
    List of layout dicts sorted by score descending, each with:
        layout_id, strategy, strategy_description, zones (GeoJSON FC),
        stats, score, score_breakdown, rank
    """
    # Parse preferences
    prefs = LayoutPreferences(
        building=float(preferences.get("building", 0.4)),
        green=float(preferences.get("green",    0.3)),
        parking=float(preferences.get("parking", 0.2)),
        utility=float(preferences.get("utility", 0.1)),
    )
    prefs.validate()

    # Parse constraints
    cons = LayoutConstraints(
        setback_m=float(constraints.get("setback_m", 3.0)),
        road_width_m=float(constraints.get("road_width_m", 6.0)),
        road_facing=str(constraints.get("road_facing", "south")),
        num_floors=int(constraints.get("num_floors", 3)),
    )

    # Parse geometry
    geom_raw = plot_geojson.get("geometry", plot_geojson)
    plot_wgs = _fix(shape(geom_raw))
    centroid  = plot_wgs.centroid
    utm       = _utm_crs(centroid.x, centroid.y)
    plot_utm  = _fix(_to_utm(plot_wgs, utm))
    plot_area = plot_utm.area

    if plot_area < 50:
        raise ValueError(
            f"Plot area {plot_area:.0f} sqm is too small (min 50 sqm)."
        )

    # Run each strategy with multiple random seeds for diversity
    results = []
    seed_base = 42
    attempts_per_strategy = max(2, math.ceil(n_layouts * 2 / len(_STRATEGIES)))

    for strategy in _STRATEGIES:
        for attempt in range(attempts_per_strategy):
            seed = seed_base + _STRATEGIES.index(strategy) * 100 + attempt
            rng = random.Random(seed)
            try:
                raw = strategy.generate(plot_utm, prefs, cons, rng)
            except Exception:
                continue

            # Convert UTM features → WGS84 GeoJSON
            geo_features = []
            zone_areas: Dict[str, float] = {}
            for zone, geom, extra in raw:
                p = _largest_poly(geom) if not isinstance(geom, Polygon) else geom
                if p is None or p.is_empty or p.area < 0.5:
                    continue
                feat = _make_feature(p, zone, utm, extra)
                if feat:
                    geo_features.append(feat)
                    if zone != "setback":
                        zone_areas[zone] = zone_areas.get(zone, 0.0) + p.area

            if not geo_features:
                continue

            score, breakdown = _score_layout(raw, prefs, plot_area)

            building_sqm = zone_areas.get("building", 0.0)
            green_sqm    = zone_areas.get("green",    0.0)
            parking_sqm  = zone_areas.get("parking",  0.0)
            utility_sqm  = zone_areas.get("utility",  0.0)

            results.append({
                "layout_id":            str(uuid.uuid4()),
                "strategy":             strategy.name,
                "strategy_description": strategy.description,
                "zones": {"type": "FeatureCollection", "features": geo_features},
                "stats": {
                    "plot_area_sqm":      round(plot_area,     1),
                    "building_sqm":       round(building_sqm,  1),
                    "green_sqm":          round(green_sqm,     1),
                    "parking_sqm":        round(parking_sqm,   1),
                    "utility_sqm":        round(utility_sqm,   1),
                    "building_pct":       round(building_sqm / plot_area * 100, 1),
                    "green_pct":          round(green_sqm    / plot_area * 100, 1),
                    "parking_pct":        round(parking_sqm  / plot_area * 100, 1),
                    "utility_pct":        round(utility_sqm  / plot_area * 100, 1),
                    "total_built_up_sqm": round(building_sqm * cons.num_floors, 1),
                    "floors":             cons.num_floors,
                },
                "score":           score,
                "score_breakdown": breakdown,
                "rank":            0,
            })

    if not results:
        raise ValueError(
            "All layout strategies failed. Check that the plot polygon is valid and large enough."
        )

    # Sort by score, deduplicate strategies (keep best per strategy), take top n
    results.sort(key=lambda r: r["score"], reverse=True)
    seen_strategies: set = set()
    deduped = []
    for r in results:
        if r["strategy"] not in seen_strategies:
            deduped.append(r)
            seen_strategies.add(r["strategy"])
    # Fill remaining slots with next best regardless of strategy
    remaining = [r for r in results if r not in deduped]
    final = (deduped + remaining)[:n_layouts]

    for i, r in enumerate(final):
        r["rank"] = i + 1

    return final