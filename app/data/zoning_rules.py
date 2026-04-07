# Zoning rules for Indian cities
# Based on CMDA (Chennai), BBMP (Bangalore), BMC (Mumbai) development control regulations

ZONING_RULES = {
    "residential": {
        "label": "Residential",
        "far": 1.5,                     # Floor Area Ratio (FSI)
        "ground_coverage": 0.40,         # Max ground coverage fraction
        "setback_front": 4.5,            # Metres
        "setback_rear": 3.0,
        "setback_side": 1.5,
        "max_height_m": 15.0,
        "min_open_space_pct": 25,        # % of plot
        "parking_ratio": 0.25,           # slots per 100 sqm built-up
        "garden_pct": 10,                # % of plot area for garden
        "road_width_m": 9.0,
        "min_plot_sqm": 100,
        "min_building_gap_m": 3.0,
    },
    "commercial": {
        "label": "Commercial",
        "far": 3.0,
        "ground_coverage": 0.60,
        "setback_front": 6.0,
        "setback_rear": 4.5,
        "setback_side": 3.0,
        "max_height_m": 30.0,
        "min_open_space_pct": 15,
        "parking_ratio": 1.0,
        "garden_pct": 5,
        "road_width_m": 12.0,
        "min_plot_sqm": 200,
        "min_building_gap_m": 6.0,
    },
    "mixed_use": {
        "label": "Mixed Use",
        "far": 2.5,
        "ground_coverage": 0.50,
        "setback_front": 5.0,
        "setback_rear": 3.5,
        "setback_side": 2.0,
        "max_height_m": 24.0,
        "min_open_space_pct": 20,
        "parking_ratio": 0.5,
        "garden_pct": 8,
        "road_width_m": 12.0,
        "min_plot_sqm": 150,
        "min_building_gap_m": 4.5,
    },
    "institutional": {
        "label": "Institutional",
        "far": 1.75,
        "ground_coverage": 0.35,
        "setback_front": 7.5,
        "setback_rear": 6.0,
        "setback_side": 4.5,
        "max_height_m": 18.0,
        "min_open_space_pct": 35,
        "parking_ratio": 0.75,
        "garden_pct": 15,
        "road_width_m": 12.0,
        "min_plot_sqm": 500,
        "min_building_gap_m": 9.0,
    },
}
