from typing import Dict, Any


def check_compliance(
    plot_area: float,
    building_footprint_sqm: float,
    garden_sqm: float,
    parking_spaces: int,
    num_floors: int,
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    violations = []
    warnings = []
    score = 100

    # Ground coverage
    ground_cov = building_footprint_sqm / plot_area if plot_area > 0 else 0
    if ground_cov > rules["ground_coverage"] + 0.01:
        excess = (ground_cov - rules["ground_coverage"]) * 100
        violations.append(
            f"Ground coverage {ground_cov:.1%} exceeds limit {rules['ground_coverage']:.0%} "
            f"(by {excess:.1f}%)"
        )
        score -= 25
    elif ground_cov > rules["ground_coverage"] * 0.95:
        warnings.append("Ground coverage is near the maximum allowed limit.")

    # FAR / FSI check
    total_built = building_footprint_sqm * num_floors
    far_achieved = total_built / plot_area if plot_area > 0 else 0
    if far_achieved > rules["far"] + 0.05:
        violations.append(
            f"FAR {far_achieved:.2f} exceeds permitted {rules['far']} for this zone."
        )
        score -= 20

    # Open space
    open_space_sqm = plot_area - building_footprint_sqm
    open_space_pct = (open_space_sqm / plot_area * 100) if plot_area > 0 else 0
    if open_space_pct < rules["min_open_space_pct"] - 1:
        violations.append(
            f"Open space {open_space_pct:.1f}% is below minimum {rules['min_open_space_pct']}%."
        )
        score -= 15

    # Garden minimum
    garden_pct = (garden_sqm / plot_area * 100) if plot_area > 0 else 0
    if garden_pct < rules["garden_pct"] * 0.8:
        warnings.append(
            f"Garden area ({garden_pct:.1f}%) is below recommended {rules['garden_pct']}%."
        )
        score -= 5

    # Parking
    required_slots = max(1, int(plot_area / 100 * rules["parking_ratio"]))
    if parking_spaces < required_slots:
        warnings.append(
            f"Parking: {parking_spaces} slots provided, {required_slots} recommended."
        )
        score -= 5

    # Building height check (informational only — we don't enforce here)
    max_permitted_floors = int(rules["max_height_m"] / 3.0)  # assume 3m floor-to-floor
    if num_floors > max_permitted_floors:
        violations.append(
            f"Building height ({num_floors} floors ≈ {num_floors*3}m) exceeds zone limit "
            f"of {rules['max_height_m']}m."
        )
        score -= 20

    score = max(0, score)

    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B+"
    elif score >= 70:
        grade = "B"
    elif score >= 60:
        grade = "C"
    else:
        grade = "F"

    return {
        "score": score,
        "grade": grade,
        "violations": violations,
        "warnings": warnings,
        "far_achieved": round(far_achieved, 2),
        "ground_coverage_pct": round(ground_cov * 100, 1),
        "open_space_pct": round(open_space_pct, 1),
        "parking_spaces": parking_spaces,
    }