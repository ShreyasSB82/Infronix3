from fastapi import APIRouter
from typing import Dict, Any
from pydantic import BaseModel

router = APIRouter(tags=["clearance"])

class ClearanceRequest(BaseModel):
    polygon: Dict[str, Any]
    point: list[float] = [0.0, 0.0]

class ClearanceResponse(BaseModel):
    drainageOffset: float
    waterMainOffset: float
    sewageTrunkOffset: float
    floodZone: str
    zoningClass: str
    isSelectable: bool

@router.post("/clearance", response_model=ClearanceResponse)
async def check_clearance(body: ClearanceRequest):
    # Mock infrastructural BBMP data response based on Bangalore specifications
    # In a full GIS system, this would query PostGIS or PMTiles locally.
    
    return ClearanceResponse(
        drainageOffset=4.2,      # SWD buffer
        waterMainOffset=2.1,     # BWSSB offset
        sewageTrunkOffset=8.5,   # UGD trunk offset
        floodZone="safe",
        zoningClass="R1",
        isSelectable=True
    )
