from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json, sqlite3, uuid, httpx, io, ezdxf
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from app.api.routes.site_plan import router as site_plan_router
from app.api.routes.layout_planner import router as layout_planner_router

app = FastAPI(title="Infronix – Land Intelligence Platform")
app.include_router(site_plan_router, prefix="/api/site-plan")
app.include_router(layout_planner_router, prefix="/api/layout-planner")
templates = Jinja2Templates(directory="templates")
DB_PATH = "plots.db"
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    conn = _db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plots (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            coordinates TEXT NOT NULL,
            area        REAL,
            created_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

_init_db()

class PlotCreate(BaseModel):
    name: str
    coordinates: List[List[float]]   # [[lat, lng], ...]
    area: Optional[float] = None

class Plot(BaseModel):
    id: str
    name: str
    coordinates: List[List[float]]
    area: Optional[float]
    created_at: str

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request=request, name="landing.html")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/urbanscribe", response_class=HTMLResponse)
def urbanscribe_page(request: Request):
    return templates.TemplateResponse(request=request, name="urbanscribe.html")

@app.get("/layout-planner", response_class=HTMLResponse)
def layout_planner_page(request: Request):
    return templates.TemplateResponse(request=request, name="layout_planner.html")

@app.get("/api/config")
async def config():
    return {"ok": True}

@app.get("/api/plots", response_model=List[Plot])
async def list_plots():
    conn = _db()
    rows = conn.execute("SELECT * FROM plots ORDER BY created_at DESC").fetchall()
    conn.close()
    return [
        Plot(
            id=r["id"], name=r["name"],
            coordinates=json.loads(r["coordinates"]),
            area=r["area"], created_at=r["created_at"],
        )
        for r in rows
    ]

@app.post("/api/plots", response_model=Plot, status_code=201)
async def create_plot(body: PlotCreate):
    plot_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    conn = _db()
    conn.execute(
        "INSERT INTO plots (id, name, coordinates, area, created_at) VALUES (?, ?, ?, ?, ?)",
        (plot_id, body.name, json.dumps(body.coordinates), body.area, created_at),
    )
    conn.commit()
    conn.close()
    return Plot(id=plot_id, name=body.name, coordinates=body.coordinates,
                area=body.area, created_at=created_at)


@app.delete("/api/plots/{plot_id}")
async def delete_plot(plot_id: str):
    conn = _db()
    cur = conn.execute("DELETE FROM plots WHERE id = ?", (plot_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Plot not found")
    return {"ok": True}


@app.get("/api/geocode")
async def geocode(q: str):
    """Proxy Nominatim with India bias to avoid browser CORS issues."""
    # India bounding box: roughly 68°E–97°E, 8°N–37°N
    INDIA_VIEWBOX = "68.1,8.0,97.4,37.1"
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "json",
                "q": q,
                "limit": 5,
                "countrycodes": "in",       # restrict results to India
                "viewbox": INDIA_VIEWBOX,
                "bounded": "0",             # bias but don't hard-restrict
            },
            headers={"User-Agent": "LandMark/1.0 (hackathon)"},
        )
    results = resp.json()
    # If nothing found within India, fall back to global search
    if not results:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "json", "q": q, "limit": 5},
                headers={"User-Agent": "LandMark/1.0 (hackathon)"},
            )
        results = resp.json()
    return results


@app.get("/api/bhuvan-capabilities")
async def bhuvan_capabilities():
    """Fetch Bhuvan WMS GetCapabilities (proxied to avoid CORS on XHR)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://bhuvan-app1.nrsc.gov.in/2dresources/bhuvan/wms",
            params={"SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.1.1"},
        )
    return resp.text

# ----------------- Geometry / CAD Feature -----------------

@app.get("/plot-details", response_class=HTMLResponse)
def plot_details_page(request: Request):
    return templates.TemplateResponse(request=request, name="plot_details.html")

@app.get("/interior-layout", response_class=HTMLResponse)
def interior_layout_page(request: Request):
    return templates.TemplateResponse(request=request, name="interior_layout.html")


@app.get("/viewer", response_class=HTMLResponse)
def viewer_page(request: Request):
    return templates.TemplateResponse(request=request, name="viewer.html")

class LayoutPayload(BaseModel):
    plots: List[Dict[str, Any]]
    roads: List[Dict[str, Any]]
    utilities: Dict[str, List[Dict[str, Any]]]

@app.post("/api/export/dxf")
def export_dxf(payload: LayoutPayload):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    
    # Standard CAD Layers
    doc.layers.add("PLOTS", color=7)      # White/Black
    doc.layers.add("ROADS", color=8)      # Grey
    doc.layers.add("WATER", color=5)      # Blue
    doc.layers.add("SEWAGE", color=12)    # Dark Red/Brown
    doc.layers.add("ELECTRIC", color=2)   # Yellow
    
    for plot in payload.plots:
        pts = plot.get("points", [])
        if len(pts) > 2:
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "PLOTS"})
            
    for road in payload.roads:
        pts = road.get("centerline", [])
        # We export centerlines for CAD layout. Width can be added as lineweight or offset
        if pts:
            msp.add_lwpolyline(pts, dxfattribs={"layer": "ROADS"})
            
    # Utilities
    utils = payload.utilities
    for w in utils.get("water", []):
        msp.add_lwpolyline(w.get("path", []), dxfattribs={"layer": "WATER"})
    for s in utils.get("sewage", []):
        msp.add_lwpolyline(s.get("path", []), dxfattribs={"layer": "SEWAGE"})
    for e in utils.get("electric", []):
        msp.add_lwpolyline(e.get("path", []), dxfattribs={"layer": "ELECTRIC"})

    buf = io.StringIO()
    doc.write(buf)
    out_str = buf.getvalue()
    buf.close()
    
    return StreamingResponse(
        io.BytesIO(out_str.encode('utf-8')), 
        media_type="application/dxf",
        headers={"Content-Disposition": "attachment; filename=layout.dxf"}
    )

