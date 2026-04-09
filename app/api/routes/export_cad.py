"""
DXF Export Service for Infranix2
=================================
Converts the Infranix2 JSON formats (site plan zones + interior floor plan)
to a layered DXF file using ezdxf.

Endpoint: POST /api/export/dxf
JSON body restrictions:
  - Max body size: 5 MB (enforced by body_limit middleware in main.py)
  - Required top-level key: "site_plan" and/or "interior"
  - Coordinates must be numeric pairs (lon/lat or local metres)

DXF output layers:
  ZONES_<zone_type>  — site plan zone polygons
  ROOMS_<room_type>  — interior room polygons per floor
  BOUNDARY           — building exterior footprint
  DIMENSIONS         — auto-generated dimension lines (future)
"""

from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf import colors as dxf_colors
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse
import pyproj

router = APIRouter()

# ── coordinate helpers ────────────────────────────────────────────────────────

_WGS84 = pyproj.CRS("EPSG:4326")


def _is_geographic(coords: List[List[float]]) -> bool:
    """Guess whether coordinates are lon/lat (geographic) or local metres."""
    if not coords:
        return False
    x, y = coords[0][0], coords[0][1]
    return abs(x) <= 180 and abs(y) <= 90


def _centroid_lonlat(features: List[Dict]) -> Tuple[float, float]:
    xs, ys, n = 0.0, 0.0, 0
    for f in features:
        geom = f.get("geometry") or {}
        for ring in _iter_rings(geom):
            for pt in ring:
                xs += pt[0]; ys += pt[1]; n += 1
    return (xs / n, ys / n) if n else (0.0, 0.0)


def _iter_rings(geom: Dict):
    t = geom.get("type", "")
    coords = geom.get("coordinates", [])
    if t == "Polygon":
        yield from coords
    elif t == "MultiPolygon":
        for poly in coords:
            yield from poly


def _geo_to_metres(
    ring: List[List[float]], cx: float, cy: float
) -> List[Tuple[float, float]]:
    lat_rad = math.radians(cy)
    mlon = 111320 * math.cos(lat_rad)
    mlat = 111320
    return [((p[0] - cx) * mlon, (p[1] - cy) * mlat) for p in ring]


def _normalise_ring(
    ring: List[List[float]], cx: float, cy: float, is_geo: bool
) -> List[Tuple[float, float]]:
    if is_geo:
        return _geo_to_metres(ring, cx, cy)
    return [(p[0] - cx, p[1] - cy) for p in ring]


# ── DXF colour map ────────────────────────────────────────────────────────────

_ZONE_COLOURS: Dict[str, int] = {
    "building":  dxf_colors.CYAN,
    "greenery":  dxf_colors.GREEN,
    "parking":   dxf_colors.GRAY,
    "utility":   dxf_colors.YELLOW,
    "road":      dxf_colors.WHITE,
}

_ROOM_COLOURS: Dict[str, int] = {
    "living":      dxf_colors.BLUE,
    "kitchen":     dxf_colors.YELLOW,
    "bedroom":     dxf_colors.MAGENTA,
    "bathroom":    dxf_colors.CYAN,
    "study":       dxf_colors.RED,
    "circulation": dxf_colors.GRAY,
    "utility":     dxf_colors.GREEN,
    "corner":      dxf_colors.WHITE,
}

# AIA CAD Standard: Anti-Gravity + MEP layers
_AG_LAYERS: Dict[str, dict] = {
    "A-WALL-EXTR":   {"color": dxf_colors.WHITE},
    "A-WALL-INTR":   {"color": 8},
    "A-GLAZ":        {"color": dxf_colors.CYAN},
    "A-ROOF":        {"color": dxf_colors.MAGENTA},
    "S-COLS":        {"color": dxf_colors.RED},
    "S-BEAMS":       {"color": dxf_colors.YELLOW},
    "M-PIPE-WATER":  {"color": dxf_colors.BLUE},
    "M-PIPE-SWR":    {"color": dxf_colors.GREEN},
    "M-PIPE-SWD":    {"color": 94},
    "M-PIPE-CRYO":   {"color": dxf_colors.BLUE},
    "E-CONDUIT":     {"color": 30},
    "X-AGRAV-RINGS": {"color": 40},
    "X-AGRAV-VOID":  {"color": dxf_colors.CYAN},
    "X-AGRAV-SHAFT": {"color": dxf_colors.WHITE},
    "SITE-INFRA":    {"color": 94},
}

_DEFAULT_COLOUR = dxf_colors.WHITE


def _zone_colour(zone_type: str) -> int:
    return _ZONE_COLOURS.get((zone_type or "").lower(), _DEFAULT_COLOUR)


def _room_colour(room_type: str) -> int:
    return _ROOM_COLOURS.get((room_type or "").lower(), _DEFAULT_COLOUR)


# ── DXF layer helpers ─────────────────────────────────────────────────────────

def _ensure_layer(doc: ezdxf.document.Drawing, name: str, colour: int) -> str:
    """Create layer if missing, return layer name."""
    if name not in doc.layers:
        doc.layers.new(name, dxfattribs={"color": colour})
    return name


def _add_lwpolyline(
    msp,
    doc: ezdxf.document.Drawing,
    pts: List[Tuple[float, float]],
    layer: str,
    colour: int,
    closed: bool = True,
) -> None:
    """Add a 2-D closed polyline to model space."""
    _ensure_layer(doc, layer, colour)
    if len(pts) < 2:
        return
    lw = msp.add_lwpolyline(pts, dxfattribs={"layer": layer, "color": colour})
    lw.close(closed)


def _add_text_label(
    msp,
    doc: ezdxf.document.Drawing,
    text: str,
    x: float,
    y: float,
    layer: str,
    height: float = 0.5,
) -> None:
    _ensure_layer(doc, layer, dxf_colors.WHITE)
    msp.add_text(
        text,
        dxfattribs={
            "layer": layer,
            "height": height,
            "insert": (x, y),
            "halign": 1,
            "valign": 0,
        },
    )


# ── site plan section ─────────────────────────────────────────────────────────

def _write_site_plan(doc: ezdxf.document.Drawing, msp, site_plan: Dict) -> None:
    features: List[Dict] = (site_plan.get("zones") or {}).get("features") or []
    if not features:
        return

    sample_ring = None
    for f in features:
        for ring in _iter_rings(f.get("geometry") or {}):
            if ring:
                sample_ring = ring
                break
        if sample_ring:
            break

    is_geo = _is_geographic(sample_ring or [])
    cx, cy = _centroid_lonlat(features) if is_geo else (0.0, 0.0)

    for f in features:
        props = f.get("properties") or {}
        zone_type: str = (props.get("zone") or "zone").lower()
        layer_name = f"ZONES_{zone_type.upper()}"
        colour = _zone_colour(zone_type)

        geom = f.get("geometry") or {}
        for ring in _iter_rings(geom):
            pts = _normalise_ring(ring, cx, cy, is_geo)
            _add_lwpolyline(msp, doc, pts, layer_name, colour)

            # Centroid label
            if pts:
                lx = sum(p[0] for p in pts) / len(pts)
                ly = sum(p[1] for p in pts) / len(pts)
                label = f"{zone_type} ({props.get('area_sqm', ''):.1f} m²)" if props.get("area_sqm") else zone_type
                _add_text_label(msp, doc, label, lx, ly, f"LABELS_{zone_type.upper()}")


# ── interior / floor plan section ─────────────────────────────────────────────

FLOOR_SPACING = 30.0   # metres between stacked floor plans in DXF


def _write_interior(doc: ezdxf.document.Drawing, msp, interior: Dict) -> None:
    floors: List[Dict] = interior.get("floors") or []
    if not floors:
        return

    # Detect coordinate system from first room
    first_coords: List[List[float]] = []
    for fl in floors:
        for rm in fl.get("rooms") or []:
            if rm.get("coords"):
                first_coords = rm["coords"]
                break
        if first_coords:
            break

    is_geo = _is_geographic(first_coords)
    cx, cy = (0.0, 0.0)
    if is_geo and first_coords:
        all_x = [c[0] for c in first_coords]
        all_y = [c[1] for c in first_coords]
        cx = sum(all_x) / len(all_x)
        cy = sum(all_y) / len(all_y)

    for fl in floors:
        floor_num: int = fl.get("floor", 1)
        y_offset = (floor_num - 1) * FLOOR_SPACING

        # Building boundary
        boundary = fl.get("boundary") or []
        if boundary:
            pts = _normalise_ring(boundary, cx, cy, is_geo)
            pts = [(p[0], p[1] + y_offset) for p in pts]
            _add_lwpolyline(msp, doc, pts, "BOUNDARY", dxf_colors.WHITE)

        # Floor label
        _add_text_label(msp, doc, f"Floor {floor_num}", 0, y_offset - 2 if y_offset > 0 else -2, "LABELS_FLOORS", height=1.0)

        # Rooms
        for room in fl.get("rooms") or []:
            room_type = (room.get("type") or "room").lower()
            layer_name = f"ROOMS_{room_type.upper()}"
            colour = _room_colour(room_type)

            coords = room.get("coords") or []
            if len(coords) < 3:
                continue

            pts = _normalise_ring(coords, cx, cy, is_geo)
            pts = [(p[0], p[1] + y_offset) for p in pts]
            _add_lwpolyline(msp, doc, pts, layer_name, colour)

            # Room label at centroid
            lx = sum(p[0] for p in pts) / len(pts)
            ly = sum(p[1] for p in pts) / len(pts)
            label_parts = [room.get("name") or room_type]
            if room.get("area_sqm"):
                label_parts.append(f"{room['area_sqm']:.1f}m²")
            _add_text_label(msp, doc, " ".join(label_parts), lx, ly, layer_name, height=0.4)


# ── Anti-Gravity BIM section ──────────────────────────────────────────────────

def _circle_pts(cx: float, cy: float, r: float, n: int = 32) -> List[Tuple[float, float]]:
    """Generate n points approximating a circle for DXF lwpolyline."""
    return [
        (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _write_anti_gravity(
    doc: ezdxf.document.Drawing,
    msp,
    ag_config: Dict,
    cx: float,
    cy: float,
) -> None:
    """
    Write Anti-Gravity BIM elements to DXF:
      - Glass envelope             (A-GLAZ)
      - Superconducting shaft      (X-AGRAV-SHAFT)
      - Levitation rings per floor (X-AGRAV-RINGS)
      - Gravity void outline       (X-AGRAV-VOID)
      - Cryo helix approximation   (M-PIPE-CRYO)
      - MEP underground lines      (M-PIPE-WATER / M-PIPE-SWR / M-PIPE-SWD)
    """
    # Ensure all AG layers exist
    for layer_name, attrs in _AG_LAYERS.items():
        _ensure_layer(doc, layer_name, attrs["color"])

    floors     = int(ag_config.get("floors", 3))
    floor_h    = float(ag_config.get("floor_height", 3.2))
    bldg_w     = float(ag_config.get("building_width", 20.0))
    bldg_d     = float(ag_config.get("building_depth", 15.0))
    shaft_r    = float(ag_config.get("shaft_radius", 0.4))
    ring_r     = min(6.0, min(bldg_w, bldg_d) * 0.2)

    half_w, half_d = bldg_w / 2 + 0.25, bldg_d / 2 + 0.25

    # ── Glass envelope (plan view outline) ─────────────────────────────────────
    envelope_pts = [
        (cx - half_w, cy - half_d),
        (cx + half_w, cy - half_d),
        (cx + half_w, cy + half_d),
        (cx - half_w, cy + half_d),
    ]
    _add_lwpolyline(msp, doc, envelope_pts, "A-GLAZ", _AG_LAYERS["A-GLAZ"]["color"])
    _add_text_label(msp, doc, "Glass Curtain Wall", cx, cy + half_d + 0.5, "A-GLAZ", height=0.5)

    # ── Gravity void inner boundary ─────────────────────────────────────────────
    vhw, vhd = bldg_w / 2 - 1.0, bldg_d / 2 - 1.0
    void_pts = [
        (cx - vhw, cy - vhd),
        (cx + vhw, cy - vhd),
        (cx + vhw, cy + vhd),
        (cx - vhw, cy + vhd),
    ]
    _add_lwpolyline(msp, doc, void_pts, "X-AGRAV-VOID", _AG_LAYERS["X-AGRAV-VOID"]["color"])
    _add_text_label(msp, doc, "Gravity Void 12.5 T", cx, cy + vhd + 0.3, "X-AGRAV-VOID", height=0.4)

    # ── Superconducting shaft (circle in plan) ──────────────────────────────────
    shaft_pts = _circle_pts(cx, cy, shaft_r, n=32)
    _add_lwpolyline(msp, doc, shaft_pts, "X-AGRAV-SHAFT", _AG_LAYERS["X-AGRAV-SHAFT"]["color"])
    _add_text_label(msp, doc, "SC-Shaft YBCO 77K", cx + shaft_r + 0.2, cy, "X-AGRAV-SHAFT", height=0.4)

    # ── Levitation rings: outer + inner circle per floor ────────────────────────
    for i in range(floors):
        elev = (i + 0.5) * floor_h
        pts_outer = _circle_pts(cx, cy, ring_r, n=48)
        pts_inner = _circle_pts(cx, cy, ring_r - 0.25, n=48)
        _add_lwpolyline(msp, doc, pts_outer, "X-AGRAV-RINGS", _AG_LAYERS["X-AGRAV-RINGS"]["color"])
        _add_lwpolyline(msp, doc, pts_inner, "X-AGRAV-RINGS", _AG_LAYERS["X-AGRAV-RINGS"]["color"])
        _add_text_label(
            msp, doc,
            f"Ring F{i+1} @{elev:.1f}m 240kN",
            cx + ring_r + 0.3, cy + (i - floors / 2) * 0.6,
            "X-AGRAV-RINGS", height=0.35,
        )

    # ── Cryo cooling helix (approximated as polyline segments) ──────────────────
    cryo_r = shaft_r + 0.6
    turns  = floors * 2
    steps  = turns * 12
    prev: Optional[Tuple[float, float]] = None
    for step in range(steps + 1):
        angle = (step / steps) * turns * 2 * math.pi
        hx = cx + cryo_r * math.cos(angle)
        hy = cy + cryo_r * math.sin(angle)
        if prev is not None:
            _add_lwpolyline(
                msp, doc,
                [prev, (hx, hy)],
                "M-PIPE-CRYO", _AG_LAYERS["M-PIPE-CRYO"]["color"],
                closed=False,
            )
        prev = (hx, hy)
    _add_text_label(msp, doc, "LN\u2082 Cryo Loop 60mm", cx + cryo_r + 0.25, cy, "M-PIPE-CRYO", height=0.4)

    # ── Underground MEP connections ─────────────────────────────────────────────
    edge_south = cy - half_d
    # Water supply (BWSSB) from south
    _add_lwpolyline(
        msp, doc,
        [(cx - 1.0, edge_south - 5.0), (cx - 1.0, edge_south)],
        "M-PIPE-WATER", _AG_LAYERS["M-PIPE-WATER"]["color"], closed=False,
    )
    _add_text_label(msp, doc, "BWSSB DN25 -1.0m", cx - 1.0, edge_south - 5.8, "M-PIPE-WATER", height=0.35)

    edge_east = cx + half_w
    # Sewage (UGD) from east
    _add_lwpolyline(
        msp, doc,
        [(edge_east, cy + 1.0), (edge_east + 5.0, cy + 1.0)],
        "M-PIPE-SWR", _AG_LAYERS["M-PIPE-SWR"]["color"], closed=False,
    )
    _add_text_label(msp, doc, "UGD DN150 -1.5m", edge_east + 0.5, cy + 1.6, "M-PIPE-SWR", height=0.35)

    edge_north = cy + half_d
    # Stormwater (SWD) to north
    _add_lwpolyline(
        msp, doc,
        [(cx + 1.5, edge_north), (cx + 1.5, edge_north + 5.0)],
        "M-PIPE-SWD", _AG_LAYERS["M-PIPE-SWD"]["color"], closed=False,
    )
    _add_text_label(msp, doc, "SWD DN100 -0.6m", cx + 2.0, edge_north + 1.2, "M-PIPE-SWD", height=0.35)

    # ── BIM annotation summary ──────────────────────────────────────────────────
    _add_text_label(
        msp, doc,
        f"AG Core: YBCO | {floors}F | 12.5T | {floors * 240} kN | LN\u2082 77K | IS 456:2000 + Infronix-AG-001",
        cx - half_w, cy - half_d - 2.5,
        "X-AGRAV-SHAFT", height=0.65,
    )


# ── main endpoint ─────────────────────────────────────────────────────────────


@router.post("/dxf")
async def export_dxf(
    body: Dict[str, Any] = Body(
        ...,
        description="JSON with optional keys: site_plan (zones), interior (floors)",
    )
) -> StreamingResponse:
    """
    Convert Infranix2 layout JSON to a DXF CAD file.

    Accepts:
      - body.site_plan  → site plan with zones FeatureCollection
      - body.interior   → interior floor plan with floors array

    Returns: application/dxf file download
    """
    site_plan   = body.get("site_plan")
    interior    = body.get("interior")
    anti_gravity = body.get("anti_gravity")   # optional AG config

    if not site_plan and not interior:
        raise HTTPException(
            status_code=400,
            detail="Request body must contain at least one of: 'site_plan' or 'interior'",
        )

    doc = ezdxf.new(dxfversion="R2010")
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()

    if site_plan:
        _write_site_plan(doc, msp, site_plan)

    if interior:
        _write_interior(doc, msp, interior)

    # Write Anti-Gravity BIM elements if requested
    if anti_gravity:
        # Compute centroid from site plan features or default to 0,0
        cx, cy = 0.0, 0.0
        if site_plan:
            features = (site_plan.get("zones") or {}).get("features") or []
            if features:
                cx, cy = _centroid_lonlat(features)
                is_geo = _is_geographic(
                    next(
                        (r for f in features for r in _iter_rings(f.get("geometry") or {})),
                        []
                    )
                )
                if is_geo:
                    cx, cy = 0.0, 0.0  # centroid already normalised to local origin
        _write_anti_gravity(doc, msp, anti_gravity, cx, cy)

    # ezdxf write to a text stream then encode to bytes for HTTP response
    text_stream = io.StringIO()
    doc.write(text_stream)
    dxf_bytes = text_stream.getvalue().encode("utf-8")

    return StreamingResponse(
        io.BytesIO(dxf_bytes),
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=infranix_bim_export.dxf"},
    )
