"""
Graph2plan-inspired algorithmic floor plan generator.

Strategy:
  1. Project building polygon to local UTM for metric operations.
  2. BSP-partition the axis-aligned bounding box into rectangular cells.
  3. Intersect each cell with the actual building polygon.
     - Cell ∩ building ≥ 88 % of cell area  →  kept as a RECTANGULAR room
       (the full rectangle is used so walls are perfectly straight).
     - Cell ∩ building  < 88 % of cell area  →  the real intersection polygon
       is kept as a TRIANGULAR / corner room (fills diagonal edges).
  4. Assign room types from a priority list (large rooms first).
  5. Render everything to an SVG string.
"""

import math
import random
from typing import Any, Dict, List, Tuple

import pyproj
from shapely.geometry import LineString, MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import split as shp_split
from shapely.ops import transform as shapely_transform, unary_union

# ── colour palette ────────────────────────────────────────────────────────────
ROOM_COLORS: Dict[str, str] = {
    "living":      "#3B82F6",   # vivid blue
    "kitchen":     "#F59E0B",   # amber
    "bedroom":     "#8B5CF6",   # violet
    "bathroom":    "#10B981",   # emerald
    "study":       "#F97316",   # orange
    "circulation": "#64748B",   # slate
    "utility":     "#0EA5E9",   # sky blue
    "corner":      "#A16207",   # dark amber / storage
}

ROOM_LABELS: Dict[str, str] = {
    "living":      "Living / Family",
    "kitchen":     "Kitchen + Dining",
    "bedroom":     "Bedroom",
    "bathroom":    "Bathroom",
    "study":       "Study / Office",
    "circulation": "Corridor",
    "utility":     "Utility",
    "corner":      "Corner Storage",
}

# ── CRS helpers ───────────────────────────────────────────────────────────────
_WGS84 = pyproj.CRS("EPSG:4326")


def _utm_crs(lon: float, lat: float) -> pyproj.CRS:
    zone = int((lon + 180) / 6) + 1
    hemi = "north" if lat >= 0 else "south"
    return pyproj.CRS(f"+proj=utm +zone={zone} +{hemi} +datum=WGS84")


def _to_utm(geom: Polygon, utm: pyproj.CRS) -> Polygon:
    t = pyproj.Transformer.from_crs(_WGS84, utm, always_xy=True).transform
    return shapely_transform(t, geom)


# ── BSP partitioning (splits the polygon itself, not the bounding box) ────────

def _extract_polygons(geom) -> List[Polygon]:
    """Recursively extract all simple Polygons from any geometry type."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        out: List[Polygon] = []
        for g in geom.geoms:
            out.extend(_extract_polygons(g))
        return out
    return []   # LineString, Point, etc. — ignore


def _split_one(poly: Polygon, ratio: float, rng: random.Random) -> List[Polygon]:
    """Split *poly* once with a single axis-aligned cut. Returns 1 or 2 Polygons."""
    minx, miny, maxx, maxy = poly.bounds
    w = maxx - minx
    h = maxy - miny
    try:
        if w >= h:
            x    = minx + w * ratio
            line = LineString([(x, miny - 1.0), (x, maxy + 1.0)])
        else:
            y    = miny + h * ratio
            line = LineString([(minx - 1.0, y), (maxx + 1.0, y)])

        # shp_split returns a GeometryCollection — flatten everything to Polygons
        parts = _extract_polygons(shp_split(poly, line))
        return parts if len(parts) >= 2 else [poly]
    except Exception:
        return [poly]


def _greedy_split(
    building: Polygon,
    n_target: int,
    rng: random.Random,
    min_area: float,
) -> List[Polygon]:

    cells: List[Polygon] = [building]
    stalled = 0                         # guard against unsplittable geometries

    while len(cells) < n_target and stalled < len(cells):
        cells.sort(key=lambda p: p.area, reverse=True)
        candidate = cells.pop(0)

        # Skip cells that are already very small
        if candidate.area < min_area:
            cells.insert(0, candidate)
            stalled += 1
            continue

        ratio  = 0.38 + rng.random() * 0.24
        pieces = _split_one(candidate, ratio, rng)

        if len(pieces) < 2:
            # This cell cannot be split (e.g. very thin triangle); leave it
            cells.insert(0, candidate)
            stalled += 1
        else:
            cells.extend(pieces)
            stalled = 0

    return cells


# ── room-type programme ───────────────────────────────────────────────────────

def _build_programme(bedrooms: int, bathrooms: int, has_study: bool) -> List[str]:
    """Ordered list of room types, large/important rooms first."""
    types: List[str] = ["living", "kitchen"]
    for _ in range(bedrooms):
        types.append("bedroom")
    for _ in range(bathrooms):
        types.append("bathroom")
    if has_study:
        types.append("study")
    types.append("circulation")
    types.append("utility")
    return types


# ── cell classification ───────────────────────────────────────────────────────

def _is_rectangular(poly: Polygon) -> bool:
    """
    True when the polygon is a near-perfect rectangle.

    Criterion: its area fills ≥ 90 % of its axis-aligned bounding box.
    This correctly classifies cells produced by straight H/V cuts as
    rectangular and cells clipped by diagonal building edges as triangular.
    """
    bbox_area = box(*poly.bounds).area
    return (poly.area / bbox_area) >= 0.90 if bbox_area > 0 else False


# ── single-floor generator ────────────────────────────────────────────────────

def _generate_floor(
    building: Polygon,
    programme: List[str],
    total_area: float,
    seed: int,
) -> List[Dict[str, Any]]:
    rng      = random.Random(seed)
    n        = len(programme)
    min_area = total_area * 0.004   # dust filter — only truly negligible slivers

    # Request n + 3 cells so diagonal edges can produce a few triangular corners
    # without crowding out programme rooms.
    n_target = n + 3

    # ── split the building polygon itself ─────────────────────────────────────
    cells = _greedy_split(building, n_target, rng, min_area)

    # Normalise: flatten any MultiPolygon / GeometryCollection → simple Polygons
    flat_cells: List[Polygon] = []
    for cell in cells:
        for poly in _extract_polygons(cell):
            if poly.area >= min_area:
                flat_cells.append(poly)

    # ── classify cells ────────────────────────────────────────────────────────
    rectangular_cells: List[Dict] = []
    triangular_cells:  List[Dict] = []

    for cell in flat_cells:
        entry = {"poly": cell, "area": cell.area}
        if _is_rectangular(cell):
            rectangular_cells.append(entry)
        else:
            triangular_cells.append(entry)

    # Sort largest → smallest so important rooms get the most space
    rectangular_cells.sort(key=lambda c: c["area"], reverse=True)
    triangular_cells.sort( key=lambda c: c["area"], reverse=True)

    rooms:    List[Dict[str, Any]] = []
    counters: Dict[str, int]       = {}

    # ── assign programme rooms to rectangular cells ───────────────────────────
    # Corner-friendly types that can also live in triangular cells
    corner_ok = {"bathroom", "utility", "circulation"}

    rect_idx = 0
    deferred: List[str] = []   # room types that must fall back to triangular cells

    for rtype in programme:
        if rect_idx < len(rectangular_cells):
            cell = rectangular_cells[rect_idx]
            rect_idx += 1
        else:
            # No rectangular cell left — defer to triangular or skip
            deferred.append(rtype)
            continue

        counters[rtype] = counters.get(rtype, 0) + 1
        suffix = f" {counters[rtype]}" if rtype in ("bedroom", "bathroom") else ""
        rooms.append({
            "name":     ROOM_LABELS[rtype] + suffix,
            "type":     rtype,
            "shape":    "rectangular",
            "area_sqm": round(cell["area"], 1),
            "coords":   list(cell["poly"].exterior.coords),
            "color":    ROOM_COLORS[rtype],
        })

    # ── assign deferred rooms to triangular cells (corner-friendly first) ─────
    tri_idx = 0
    for rtype in deferred:
        if tri_idx >= len(triangular_cells):
            break
        cell = triangular_cells[tri_idx]
        tri_idx += 1
        counters[rtype] = counters.get(rtype, 0) + 1
        suffix = f" {counters[rtype]}" if rtype in ("bedroom", "bathroom") else ""
        rooms.append({
            "name":     ROOM_LABELS[rtype] + suffix,
            "type":     rtype,
            "shape":    "triangular",
            "area_sqm": round(cell["area"], 1),
            "coords":   list(cell["poly"].exterior.coords),
            "color":    ROOM_COLORS[rtype],
        })

    # ── label remaining triangular cells as Corner Storage ────────────────────
    # These correspond to the diagonal-edge nooks in the building boundary
    for cell in triangular_cells[tri_idx:]:
        if cell["area"] < total_area * 0.006:   # truly tiny sliver — skip
            continue
        rooms.append({
            "name":     "Corner Storage",
            "type":     "corner",
            "shape":    "triangular",
            "area_sqm": round(cell["area"], 1),
            "coords":   list(cell["poly"].exterior.coords),
            "color":    ROOM_COLORS["corner"],
        })

    # ── any extra rectangular cells become additional storage ─────────────────
    for cell in rectangular_cells[rect_idx:]:
        rooms.append({
            "name":     "Storage",
            "type":     "utility",
            "shape":    "rectangular",
            "area_sqm": round(cell["area"], 1),
            "coords":   list(cell["poly"].exterior.coords),
            "color":    ROOM_COLORS["utility"],
        })

    return rooms


def _identify_walls_and_openings(building: Polygon, rooms: List[Dict], rng: random.Random):
    """
    Identify wall segments and procedurally place doors and windows.
    Windows go on exterior walls; doors go on interior walls (connecting to circulation if possible).
    """
    doors = []
    windows = []
    
    building_exterior = building.exterior
    
    for i, room in enumerate(rooms):
        poly = Polygon(room["coords"])
        if not poly.is_valid:
            poly = poly.buffer(0)
            
        coords = list(poly.exterior.coords)
        for j in range(len(coords) - 1):
            p1 = coords[j]
            p2 = coords[j+1]
            seg = LineString([p1, p2])
            mid = seg.centroid
            
            # ── Window placement (Exterior walls) ────────────────────────────
            # If segment is on the building boundary
            if building_exterior.distance(seg) < 0.01:
                if seg.length > 1.5:  # Minimum wall length for a window
                    windows.append({
                        "room_idx": i,
                        "pos": [mid.x, mid.y],
                        "width": 1.2,
                        "height": 1.4,
                        "elevation": 0.9,
                        "normal": [p2[1]-p1[1], p1[0]-p2[0]], # vector perpendicular to wall
                        "wall_seg": [p1, p2]
                    })
            
            # ── Door placement (Interior walls) ───────────────────────────────
            # Doors are harder: we only want one per room, ideally to circulation.
            # Simplified: if it's an interior wall and room is not circulation,
            # find the neighbor and place a door if neighbor is circulation.
            else:
                is_circulation = (room["type"] == "circulation")
                if not is_circulation:
                    # check if this segment touch another room
                    for k, peer in enumerate(rooms):
                        if i == k: continue
                        if peer["type"] == "circulation":
                            peer_poly = Polygon(peer["coords"])
                            if peer_poly.distance(seg) < 0.01:
                                # Candidate for a door to corridor
                                if seg.length > 1.0:
                                    # unique door per room
                                    if not any(d["room_idx"] == i for d in doors):
                                        doors.append({
                                            "room_idx": i,
                                            "peer_idx": k,
                                            "pos": [mid.x, mid.y],
                                            "width": 0.9,
                                            "height": 2.1,
                                            "normal": [p2[1]-p1[1], p1[0]-p2[0]],
                                            "wall_seg": [p1, p2]
                                        })
                                        break
    
    return doors, windows


# ── SVG renderer ──────────────────────────────────────────────────────────────
SVG_W, SVG_H, PAD = 620, 420, 24


def _svg_transform(building: Polygon):
    minx, miny, maxx, maxy = building.bounds
    w = maxx - minx or 1
    h = maxy - miny or 1
    scale = min((SVG_W - 2 * PAD) / w, (SVG_H - 2 * PAD) / h)
    ox = PAD + ((SVG_W - 2 * PAD) - w * scale) / 2
    oy = PAD + ((SVG_H - 2 * PAD) - h * scale) / 2

    def tx(x: float) -> float:
        return round((x - minx) * scale + ox, 2)

    def ty(y: float) -> float:          # SVG Y axis is flipped
        return round(SVG_H - ((y - miny) * scale + oy), 2)

    return tx, ty


def _poly_points(coords: List[Tuple], tx, ty) -> str:
    return " ".join(f"{tx(c[0])},{ty(c[1])}" for c in coords[:-1])


def _render_svg(building: Polygon, rooms: List[Dict], doors: List[Dict], windows: List[Dict]) -> str:
    tx, ty = _svg_transform(building)
    parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_W} {SVG_H}" '
        f'style="background:#0d1b2e;border-radius:10px;width:100%;height:auto">'
    ]

    # Building outline
    bpts = _poly_points(list(building.exterior.coords), tx, ty)
    parts.append(
        f'<polygon points="{bpts}" fill="none" '
        f'stroke="rgba(255,255,255,0.3)" stroke-width="2.5"/>'
    )

    for room in rooms:
        pts   = _poly_points(room["coords"], tx, ty)
        color = room["color"]

        # Solid room fill with white wall border
        parts.append(
            f'<polygon points="{pts}" fill="{color}" fill-opacity="0.82" '
            f'stroke="#ffffff" stroke-opacity="0.55" stroke-width="1.5"/>'
        )

        # Centroid label
        poly_shape = Polygon(room["coords"][:-1])
        cx, cy = tx(poly_shape.centroid.x), ty(poly_shape.centroid.y)
        name = room["name"]
        fs   = 9 if len(name) > 16 else 10

        # Drop-shadow for legibility
        parts.append(
            f'<text x="{cx}" y="{cy - 4}" font-size="{fs}" fill="rgba(0,0,0,0.55)" '
            f'text-anchor="middle" font-family="system-ui,sans-serif" '
            f'font-weight="700" dx="0.5" dy="0.5">{name}</text>'
        )
        parts.append(
            f'<text x="{cx}" y="{cy - 4}" font-size="{fs}" fill="white" '
            f'text-anchor="middle" font-family="system-ui,sans-serif" '
            f'font-weight="700">{name}</text>'
        )
        parts.append(
            f'<text x="{cx}" y="{cy + 9}" font-size="8" '
            f'fill="rgba(255,255,255,0.8)" text-anchor="middle" '
            f'font-family="system-ui,sans-serif">{room["area_sqm"]} m²</text>'
        )

    # ── Render doors (small brown rectangles) ────────────────────────────
    for d in doors:
        cx, cy = tx(d["pos"][0]), ty(d["pos"][1])
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="#8B4513" stroke="white" stroke-width="0.5"/>')

    # ── Render windows (thin cyan lines) ─────────────────────────────────
    for w in windows:
        cx, cy = tx(w["pos"][0]), ty(w["pos"][1])
        parts.append(f'<rect x="{cx-3}" y="{cy-1}" width="6" height="2" fill="#00ffff" opacity="0.8"/>')

    parts.append("</svg>")
    return "\n".join(parts)


# ── public entry point ────────────────────────────────────────────────────────

def generate_floor_plan(
    building_geojson: Dict[str, Any],
    num_floors: int,
    bedrooms: int,
    bathrooms: int,
    has_study: bool,
    style: str,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Generate a multi-floor plan.

    Returns a dict suitable for serialisation into ``InteriorResponse``.
    """
    # Parse + fix geometry
    geom = shape(building_geojson)
    if not geom.is_valid:
        geom = geom.buffer(0)

    bldg = geom
    total_area = bldg.area
    programme  = _build_programme(bedrooms, bathrooms, has_study)

    floors_out = []
    for f in range(1, num_floors + 1):
        rng = random.Random(seed + f * 7)
        rooms = _generate_floor(bldg, programme, total_area, seed=seed + f * 7)
        doors, windows = _identify_walls_and_openings(bldg, rooms, rng)
        svg   = _render_svg(bldg, rooms, doors, windows)
        
        floors_out.append({
            "floor": f,
            "rooms": [
                {
                    "name":     r["name"],
                    "type":     r["type"],
                    "shape":    r["shape"],
                    "area_sqm": r["area_sqm"],
                    "color":    r["color"],
                    "coords":   [[c[0], c[1]] for c in r["coords"]],
                }
                for r in rooms
            ],
            "doors": doors,
            "windows": windows,
            "boundary": [[c[0], c[1]] for c in list(bldg.exterior.coords)],
            "svg": svg,
        })

    return {
        "floors":         floors_out,
        "total_area_sqm": round(total_area, 1),
        "room_count":     len(programme),
    }
