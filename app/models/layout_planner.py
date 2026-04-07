from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class LayoutPreferencesInput(BaseModel):
    """
    Percentage-based area allocations (each 1–99).
    Auto-normalized to sum to 100 if they don't.
    """
    building: float = Field(default=40.0, gt=0, le=99, description="Building %")
    green:    float = Field(default=30.0, gt=0, le=99, description="Green space %")
    parking:  float = Field(default=20.0, gt=0, le=99, description="Parking %")
    utility:  float = Field(default=10.0, gt=0, le=99, description="Utility %")

    @model_validator(mode="after")
    def normalize_to_100(self) -> "LayoutPreferencesInput":
        total = self.building + self.green + self.parking + self.utility
        if abs(total - 100.0) > 0.5:
            # Auto-normalize
            self.building = self.building / total * 100
            self.green    = self.green    / total * 100
            self.parking  = self.parking  / total * 100
            self.utility  = self.utility  / total * 100
        return self

    def as_fractions(self) -> Dict[str, float]:
        return {
            "building": round(self.building / 100, 4),
            "green":    round(self.green    / 100, 4),
            "parking":  round(self.parking  / 100, 4),
            "utility":  round(self.utility  / 100, 4),
        }


class LayoutConstraintsInput(BaseModel):
    setback_m:    float = Field(default=3.0,  ge=0.5, le=20.0, description="Setback distance (m)")
    road_width_m: float = Field(default=6.0,  ge=3.0, le=30.0, description="Road width (m)")
    road_facing:  str   = Field(default="south",                description="Road-facing direction")
    num_floors:   int   = Field(default=3,    ge=1,   le=20,    description="Number of floors")

    @model_validator(mode="after")
    def validate_road_facing(self) -> "LayoutConstraintsInput":
        valid = {"north", "south", "east", "west"}
        if self.road_facing not in valid:
            raise ValueError(f"road_facing must be one of {valid}")
        return self


class MultiLayoutRequest(BaseModel):
    plot_geojson: Dict[str, Any]
    preferences:  LayoutPreferencesInput   = LayoutPreferencesInput()
    constraints:  LayoutConstraintsInput   = LayoutConstraintsInput()
    n_layouts:    int = Field(default=5, ge=2, le=8)


class MultiLayoutResponse(BaseModel):
    layouts:          List[Dict[str, Any]]
    plot_area_sqm:    float
    preferences_used: Dict[str, float]   # fractions used after normalization
    n_generated:      int