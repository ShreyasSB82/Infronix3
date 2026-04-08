import os
import json, sqlite3, uuid, httpx
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

# UrbanScribe module
from app.api.routes.site_plan import router as site_plan_router
# Generative layout planner
from app.api.routes.layout_planner import router as layout_planner_router
# Interior floor plan generator
from app.api.routes.interior import router as interior_router

app = FastAPI(title="LandMark + UrbanScribe + Layout Planner")

# ─── Register routes ────────────────────────────────────────────────────────
app.include_router(site_plan_router,      prefix="/api/site-plan")
app.include_router(layout_planner_router, prefix="/api/layout-planner")
app.include_router(interior_router,       prefix="/api/interior")

app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

# ─── Config endpoint (Mapbox token from .env) ─────────────────────────────────
@app.get("/api/config")
async def config():
    return {"ok": True}   # no API keys required — tiles are from free sources


# ─── Page routes ──────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("frontend/dist/index.html").read_text(encoding="utf-8")


@app.get("/landing", response_class=HTMLResponse)
async def landing():
    return Path("frontend/dist/index.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse)
async def app_page():
    return Path("templates/urbanscribe.html").read_text(encoding="utf-8")


@app.get("/index", response_class=HTMLResponse)
async def index_page():
    return Path("templates/index.html").read_text(encoding="utf-8")


@app.get("/urbanscribe", response_class=HTMLResponse)
async def urbanscribe():
    return Path("templates/urbanscribe.html").read_text(encoding="utf-8")


@app.get("/login", response_class=HTMLResponse)
async def login():
    return Path("templates/login.html").read_text(encoding="utf-8")


@app.get("/plot-details", response_class=HTMLResponse)
async def plot_details():
    return Path("templates/plot_details.html").read_text(encoding="utf-8")


@app.get("/smart-tower", response_class=HTMLResponse)
async def smart_tower():
    return Path("templates/smart_tower.html").read_text(encoding="utf-8")


@app.get("/interior-layout", response_class=HTMLResponse)
async def interior_layout():
    return Path("templates/interior_layout.html").read_text(encoding="utf-8")


@app.get("/layout-planner", response_class=HTMLResponse)
async def layout_planner():
    return Path("templates/layout_planner.html").read_text(encoding="utf-8")


@app.get("/viewer", response_class=HTMLResponse)
async def viewer():
    return Path("templates/viewer.html").read_text(encoding="utf-8")


# ─── LandMark plot storage (existing) ─────────────────────────────────────────
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
    coordinates: List[List[float]]
    area: Optional[float] = None


class Plot(BaseModel):
    id: str
    name: str
    coordinates: List[List[float]]
    area: Optional[float]
    created_at: str


@app.get("/api/plots", response_model=List[Plot])
async def list_plots():
    conn = _db()
    rows = conn.execute("SELECT * FROM plots ORDER BY created_at DESC").fetchall()
    conn.close()
    return [Plot(id=r["id"], name=r["name"],
                 coordinates=json.loads(r["coordinates"]),
                 area=r["area"], created_at=r["created_at"]) for r in rows]


@app.post("/api/plots", response_model=Plot, status_code=201)
async def create_plot(body: PlotCreate):
    plot_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    conn = _db()
    conn.execute(
        "INSERT INTO plots (id,name,coordinates,area,created_at) VALUES (?,?,?,?,?)",
        (plot_id, body.name, json.dumps(body.coordinates), body.area, created_at),
    )
    conn.commit()
    conn.close()
    return Plot(id=plot_id, name=body.name, coordinates=body.coordinates,
                area=body.area, created_at=created_at)


@app.delete("/api/plots/{plot_id}")
async def delete_plot(plot_id: str):
    conn = _db()
    cur = conn.execute("DELETE FROM plots WHERE id=?", (plot_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Plot not found")
    return {"ok": True}


@app.get("/api/geocode")
async def geocode(q: str):
    INDIA_VIEWBOX = "68.1,8.0,97.4,37.1"
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "json", "q": q, "limit": 5,
                    "countrycodes": "in", "viewbox": INDIA_VIEWBOX, "bounded": "0"},
            headers={"User-Agent": "LandMark/1.0 (hackathon)"},
        )
    results = resp.json()
    if not results:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "json", "q": q, "limit": 5},
                headers={"User-Agent": "LandMark/1.0 (hackathon)"},
            )
        results = resp.json()
    return results
