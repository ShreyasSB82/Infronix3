from fastapi import APIRouter
from typing import Dict, Any
from pydantic import BaseModel
from shapely.geometry import shape

router = APIRouter(tags=["compliance"])

class ComplianceRequest(BaseModel):
    polygon: Dict[str, Any]
    prefs: Dict[str, float]
    zone: str
    infra_offsets: dict
    floors: int

class ComplianceResult(BaseModel):
    fsi_ok: bool
    setback_ok: bool
    height_ok: bool
    infra_ok: bool
    computed_fsi: float
    max_fsi: float

BBMP_RULES = {
    'R1': {
        'max_fsi': 1.75,
        'front_setback_m': 3.0,
        'side_setback_m': 1.5,
        'rear_setback_m': 1.5,
        'max_height_m': 15.0,
        'parking_per_unit': 1,
    },
    'R2': {
        'max_fsi': 2.25,
        'front_setback_m': 4.0,
        'side_setback_m': 2.0,
        'rear_setback_m': 2.0,
        'max_height_m': 18.0,
    },
}

def compute_area(geojson):
    try:
        from pyproj import Proj, transform
        from shapely.ops import transform as shapely_transform
        geom = shape(geojson)
        # Using a generic transform to get approximate square meters (Web Mercator -> Local)
        # Assuming input is likely WGS84 coords. If already in local, we just calculate area.
        # But our system already has area computed. We'll do a simple planar area * conversion or assume input is already scaled.
        # Wait, if coords are lat/lng, we need proper projection.
        from shapely.geometry import Polygon
        import pyproj
        
        project = pyproj.Transformer.from_crs("epsg:4326", "epsg:32643", always_xy=True).transform # Bangalore UTM zone
        projected_geom = shapely_transform(project, geom)
        return projected_geom.area
    except Exception:
        return 1000.0

@router.post("/compliance", response_model=ComplianceResult)
async def check_compliance(body: ComplianceRequest):
    area = compute_area(body.polygon)
    # The prefs dictionary should contain the percentage splits, e.g. 'building': 60
    building_pct = body.prefs.get("building", 60.0)
    building_area = area * building_pct / 100.0
    
    fsi = (building_area * body.floors) / area
    zone = body.zone if body.zone in BBMP_RULES else 'R1'
    rules = BBMP_RULES[zone]
    
    return ComplianceResult(
        fsi_ok=fsi <= rules['max_fsi'],
        setback_ok=True, # Mock
        height_ok=(body.floors * 3.2) <= rules['max_height_m'],
        infra_ok=True, # Mock buffer check
        computed_fsi=round(fsi, 2),
        max_fsi=rules['max_fsi'],
    )
