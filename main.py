from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
import json, sqlite3, uuid, httpx
from datetime import datetime
from pathlib import Path

app = FastAPI(title="LandMark – Land Selection Platform")

DB_PATH = "plots.db"


# --------------- Database ---------------

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


# --------------- Models ---------------

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


# --------------- Routes ---------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("templates/index.html").read_text()


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
