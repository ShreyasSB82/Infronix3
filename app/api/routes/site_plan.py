import json, sqlite3, uuid
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.data.zoning_rules import ZONING_RULES
from app.models.site_plan import (
    ExportRequest,
    GenerateRequest,
    GenerateResponse,
    PreferenceGenerateRequest,
    PreferenceGenerateResponse,
    SavedPlanSummary,
)
from app.services.layout_engine import generate_layout
from app.services.Site_plan import generate_preference_layouts
from app.services.svg_renderer import render_svg

router = APIRouter(tags=["site-plan"])

DB_PATH = "plots.db"   # shared with existing LandMark DB

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_site_plan_db():
    conn = _db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_plans (
            id               TEXT PRIMARY KEY,
            plan_name        TEXT NOT NULL,
            zone_type        TEXT NOT NULL,
            plot_geojson     TEXT NOT NULL,
            zones_geojson    TEXT NOT NULL,
            plot_area_sqm    REAL,
            compliance_score INTEGER,
            stats_json       TEXT,
            compliance_json  TEXT,
            num_floors       INTEGER DEFAULT 1,
            created_at       TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


_init_site_plan_db()


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/zoning-rules/{zone_type}")
async def get_zoning_rules(zone_type: str):
    rules = ZONING_RULES.get(zone_type)
    if not rules:
        raise HTTPException(status_code=404, detail=f"Unknown zone type '{zone_type}'. "
                                                     f"Valid: {list(ZONING_RULES)}")
    return {"zone_type": zone_type, "rules": rules}


@router.post("/generate", response_model=GenerateResponse, status_code=200)
async def generate_site_plan(body: GenerateRequest):
    try:
        result = generate_layout(
            plot_geojson=body.plot_geojson,
            zone_type=body.zone_type,
            num_floors=body.num_floors,
            road_facing=body.road_facing,
            preferences=body.preferences.model_dump(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Layout engine error: {e}")

    zones_fc = {"type": "FeatureCollection", "features": result["features"]}
    compliance = result["compliance"]
    stats = {
        "building_footprint_sqm": result["building_footprint_sqm"],
        "total_built_up_sqm":     result["total_built_up_sqm"],
        "garden_sqm":             result["garden_sqm"],
        "parking_sqm":            result["parking_sqm"],
        "open_space_sqm":         result["open_space_sqm"],
    }

    plan_id = None
    if body.save:
        if not body.plan_name:
            raise HTTPException(status_code=400, detail="plan_name required when save=true")
        plan_id = str(uuid.uuid4())
        conn = _db()
        conn.execute(
            """INSERT INTO site_plans
               (id,plan_name,zone_type,plot_geojson,zones_geojson,
                plot_area_sqm,compliance_score,stats_json,compliance_json,num_floors,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (plan_id, body.plan_name, body.zone_type,
             json.dumps(body.plot_geojson), json.dumps(zones_fc),
             result["area_sqm"], compliance["score"],
             json.dumps(stats), json.dumps(compliance),
             body.num_floors, datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()

    return GenerateResponse(
        plan_id=plan_id,
        plot_area_sqm=result["area_sqm"],
        zones=zones_fc,
        compliance=compliance,
        stats=stats,
    )


@router.post("/preferences-generate", response_model=PreferenceGenerateResponse, status_code=200)
async def generate_preference_site_plan(body: PreferenceGenerateRequest):
    try:
        split = {
            "building": body.split.building,
            "greenery": body.split.greenery,
            "parking": body.split.parking,
            "utility": body.split.utility,
        }
        result = generate_preference_layouts(
            plot_geojson=body.plot_geojson,
            split=split,
            road_facing=body.road_facing,
            num_floors=body.num_floors,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preference planner error: {e}")

    return PreferenceGenerateResponse(
        plot_area_sqm=result["plot_area_sqm"],
        layouts=result["layouts"],
    )


@router.post("/export")
async def export_plan(body: ExportRequest):
    if body.format == "geojson":
        content = json.dumps(body.zones_geojson, indent=2).encode()
        return Response(
            content=content,
            media_type="application/geo+json",
            headers={"Content-Disposition": "attachment; filename=site_plan.geojson"},
        )

    # SVG (default)
    plan_name = "Infronix Site Plan"
    if body.plan_id:
        conn = _db()
        row = conn.execute("SELECT plan_name FROM site_plans WHERE id=?",
                           (body.plan_id,)).fetchone()
        conn.close()
        if row:
            plan_name = row["plan_name"]

    svg_str = render_svg(body.zones_geojson, body.stats, body.compliance, plan_name)
    return Response(
        content=svg_str.encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Content-Disposition": "attachment; filename=site_plan.svg"},
    )


@router.get("/plans", response_model=List[SavedPlanSummary])
async def list_plans():
    conn = _db()
    rows = conn.execute(
        "SELECT id,plan_name,zone_type,plot_area_sqm,compliance_score,created_at "
        "FROM site_plans ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return [
        SavedPlanSummary(
            plan_id=r["id"], plan_name=r["plan_name"], zone_type=r["zone_type"],
            plot_area_sqm=r["plot_area_sqm"] or 0,
            compliance_score=r["compliance_score"] or 0,
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str):
    conn = _db()
    row = conn.execute("SELECT * FROM site_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {
        "plan_id": row["id"],
        "plan_name": row["plan_name"],
        "zone_type": row["zone_type"],
        "plot_geojson": json.loads(row["plot_geojson"]),
        "zones": json.loads(row["zones_geojson"]),
        "plot_area_sqm": row["plot_area_sqm"],
        "compliance": json.loads(row["compliance_json"]),
        "stats": json.loads(row["stats_json"]),
        "num_floors": row["num_floors"],
        "created_at": row["created_at"],
    }

@router.post("/plans/{plan_id}/generate-floorplan")
async def generate_floorplan(plan_id: str):
    # TODO: Call Graph2Plan for interior layout of each building
    raise HTTPException(status_code=501, detail="Not implemented yet — Graph2Plan integration planned")


@router.post("/plans/{plan_id}/simulate-flood")
async def simulate_flood(plan_id: str):
    # TODO: Flood simulation using SRTM elevation data
    raise HTTPException(status_code=501, detail="Not implemented yet — SRTM flood simulation planned")


@router.post("/plans/{plan_id}/infrastructure")
async def route_infrastructure(plan_id: str):
    # TODO: Water/drainage/electrical line routing
    raise HTTPException(status_code=501, detail="Not implemented yet — infrastructure routing planned")


@router.get("/plans/{plan_id}/export/cad")
async def export_cad(plan_id: str):
    # TODO: DXF/DWG export for architects
    raise HTTPException(status_code=501, detail="Not implemented yet — DXF/DWG export planned")