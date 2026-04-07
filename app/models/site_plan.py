from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class Preferences(BaseModel):
    garden: bool = True
    parking: bool = True
    utilities_room: bool = True


class GenerateRequest(BaseModel):
    plot_geojson: Dict[str, Any]          # GeoJSON Feature with Polygon geometry
    zone_type: str = "residential"         # residential|commercial|mixed_use|institutional
    num_floors: int = Field(default=3, ge=1, le=15)
    road_facing: str = "south"             # north|south|east|west
    preferences: Preferences = Preferences()
    save: bool = False
    plan_name: Optional[str] = None


class ZoneFeature(BaseModel):
    type: str = "Feature"
    geometry: Dict[str, Any]
    properties: Dict[str, Any]


class ComplianceResult(BaseModel):
    score: int
    grade: str
    violations: List[str]
    warnings: List[str]
    far_achieved: float
    ground_coverage_pct: float
    open_space_pct: float
    parking_spaces: int


class PlanStats(BaseModel):
    building_footprint_sqm: float
    total_built_up_sqm: float
    garden_sqm: float
    parking_sqm: float
    open_space_sqm: float


class GenerateResponse(BaseModel):
    plan_id: Optional[str]
    plot_area_sqm: float
    zones: Dict[str, Any]                  # GeoJSON FeatureCollection
    compliance: ComplianceResult
    stats: PlanStats


class ExportRequest(BaseModel):
    plan_id: Optional[str] = None
    zones_geojson: Dict[str, Any]
    stats: Dict[str, Any]
    compliance: Dict[str, Any]
    format: str = "svg"                    # svg|geojson


class SavedPlanSummary(BaseModel):
    plan_id: str
    plan_name: str
    zone_type: str
    plot_area_sqm: float
    compliance_score: int
    created_at: str


class PreferenceSplit(BaseModel):
    building: float = Field(default=60, ge=0, le=100)
    greenery: float = Field(default=20, ge=0, le=100)
    parking: float = Field(default=10, ge=0, le=100)
    utility: float = Field(default=10, ge=0, le=100)


class PreferenceGenerateRequest(BaseModel):
    plot_geojson: Dict[str, Any]
    split: PreferenceSplit
    road_facing: str = "south"
    num_floors: int = Field(default=3, ge=1, le=20)


class PreferenceGenerateResponse(BaseModel):
    plot_area_sqm: float
    layouts: List[Dict[str, Any]]