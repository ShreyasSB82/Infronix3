from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict


class InteriorRequest(BaseModel):
    building_geojson: Dict[str, Any]          # GeoJSON Polygon geometry of the building footprint
    num_floors: int = Field(1, ge=1, le=20)
    bedrooms: int = Field(3, ge=1, le=10)
    bathrooms: int = Field(2, ge=1, le=8)
    has_study: bool = False
    style: str = "modern"                      # modern | compact | luxury


class RoomData(BaseModel):
    name: str
    type: str
    shape: str                                 # rectangular | triangular
    area_sqm: float
    color: str
    coords: List[List[float]]                  # [[lon, lat], ...] closed ring in WGS84


class FloorData(BaseModel):
    floor: int
    rooms: List[RoomData]
    doors: List[Dict[str, Any]] = []
    windows: List[Dict[str, Any]] = []
    boundary: Optional[List[List[float]]] = None
    svg: str


class InteriorResponse(BaseModel):
    floors: List[FloorData]
    total_area_sqm: float
    room_count: int
