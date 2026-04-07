"""
Minimal SVG renderer for site-plan export.

Renders a GeoJSON FeatureCollection of zones into a basic SVG document
suitable for downloading as a vector drawing.
"""

from typing import Any, Dict, List


# ─── Colour defaults (fallback if feature doesn't carry one) ──────────────────

_ZONE_COLORS = {
    "building_footprint": "#4A90D9",
    "building":           "#4A90D9",
    "garden":             "#5cb85c",
    "green":              "#5cb85c",
    "parking":            "#9B9B9B",
    "utilities":          "#c0692a",
    "utility":            "#c0692a",
    "setback":            "#e8a020",
}


def _bounds(features: List[Dict]) -> tuple:
    """Return (minx, miny, maxx, maxy) across all polygons."""
    xs, ys = [], []
    for f in features:
        coords = f.get("geometry", {}).get("coordinates", [[]])
        ring = coords[0] if coords else []
        for pt in ring:
            xs.append(pt[0])
            ys.append(pt[1])
    if not xs:
        return (0, 0, 1, 1)
    return (min(xs), min(ys), max(xs), max(ys))


def render_svg(
    zones_geojson: Dict[str, Any],
    stats: Dict[str, Any],
    compliance: Dict[str, Any],
    plan_name: str = "Infronix Site Plan",
) -> str:
    """
    Convert a GeoJSON FeatureCollection into an SVG string.

    Parameters
    ----------
    zones_geojson : dict  – GeoJSON FeatureCollection with Polygon features
    stats         : dict  – summary stats (building_footprint_sqm, etc.)
    compliance    : dict  – compliance result (score, grade, etc.)
    plan_name     : str   – title rendered in the SVG header

    Returns
    -------
    str – complete SVG document as a string
    """
    features = zones_geojson.get("features", [])
    if not features:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"><text x="10" y="50">No features</text></svg>'

    minx, miny, maxx, maxy = _bounds(features)
    w = maxx - minx or 1
    h = maxy - miny or 1

    padding = max(w, h) * 0.08
    vb_x = minx - padding
    vb_y = miny - padding
    vb_w = w + padding * 2
    vb_h = h + padding * 2

    svg_width = 800
    svg_height = int(svg_width * vb_h / vb_w)

    lines: List[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_width}" height="{svg_height}" '
        f'viewBox="{vb_x} {vb_y} {vb_w} {vb_h}" '
        f'style="background:#0b0f19">'
    )

    # Title
    font_size = vb_h * 0.04
    lines.append(
        f'<text x="{vb_x + padding}" y="{vb_y + padding + font_size}" '
        f'fill="#60b4ff" font-family="Inter,sans-serif" font-size="{font_size:.2f}" '
        f'font-weight="600">{plan_name}</text>'
    )

    # Zone polygons
    for f in features:
        props = f.get("properties", {})
        zone = props.get("zone", "unknown")
        color = props.get("color", _ZONE_COLORS.get(zone, "#888"))
        label = props.get("label", zone)
        area = props.get("area_sqm", 0)

        coords = f.get("geometry", {}).get("coordinates", [[]])
        ring = coords[0] if coords else []
        if not ring:
            continue

        # SVG uses Y-down but geo uses Y-up; we flip by negating Y
        # Actually for a simple export we keep geo coords and set the viewBox
        points_str = " ".join(f"{pt[0]},{pt[1]}" for pt in ring)

        lines.append(
            f'<polygon points="{points_str}" '
            f'fill="{color}" fill-opacity="0.45" '
            f'stroke="{color}" stroke-width="{vb_w * 0.003:.4f}" '
            f'stroke-opacity="0.8"/>'
        )

        # Label at centroid
        if ring:
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            lbl_size = vb_h * 0.025
            lines.append(
                f'<text x="{cx}" y="{cy}" fill="white" font-family="Inter,sans-serif" '
                f'font-size="{lbl_size:.2f}" text-anchor="middle" '
                f'dominant-baseline="central">{label} ({area:.0f}m²)</text>'
            )

    # Stats footer
    score = compliance.get("score", "?")
    grade = compliance.get("grade", "?")
    footer_y = vb_y + vb_h - padding * 0.3
    footer_size = vb_h * 0.022
    lines.append(
        f'<text x="{vb_x + padding}" y="{footer_y}" '
        f'fill="rgba(255,255,255,0.6)" font-family="Inter,sans-serif" '
        f'font-size="{footer_size:.2f}">'
        f'Compliance: {score}/100 (Grade {grade}) · '
        f'Building: {stats.get("building_footprint_sqm", 0):.0f}m² · '
        f'Garden: {stats.get("garden_sqm", 0):.0f}m² · '
        f'Parking: {stats.get("parking_sqm", 0):.0f}m²'
        f'</text>'
    )

    lines.append("</svg>")
    return "\n".join(lines)
