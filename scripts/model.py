"""Madrona Beach actual-tide estimate.

Coefficients live in config.json. This module only applies them.

Westerly component
------------------
Wind direction is meteorological: the direction the wind comes FROM,
degrees clockwise from north. The eastward component of the wind
(positive when the air is moving toward the east, which is a westerly
wind) is

    u_east = -speed_mph * sin(direction)

The adjustment uses only the from-the-west part, max(0, u_east).
Wind from the south, east, or southeast adds nothing and is not
subtracted. Madrona Beach faces west onto Saratoga Passage, so a
westerly wind is the one that piles water onto the beach.

Sustained speed is used. Gusts are recorded and shown, not added.
A due-west wind counts in full: 10 mph from the west adds
``inches_per_10_mph`` inches (4 inches with the original coefficients).
A southwest wind counts only its west-east component.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

COMPASS_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def load_config(path: Path | None = None) -> dict:
    with (path or CONFIG_PATH).open(encoding="utf-8") as fh:
        return json.load(fh)


def compass(direction_deg: float | None) -> str:
    if direction_deg is None:
        return ""
    index = int((direction_deg % 360.0) / 22.5 + 0.5) % 16
    return COMPASS_16[index]


def degrees_from_compass(label: str | None) -> float | None:
    """Meteorological degrees for a 16-point compass label such as WNW."""
    if not label:
        return None
    key = label.strip().upper()
    if key not in COMPASS_16:
        return None
    return COMPASS_16.index(key) * 22.5


def westerly_component_mph(speed_mph: float, direction_from_deg: float) -> float:
    """How many mph of the wind is coming from the west."""
    radians = math.radians(direction_from_deg % 360.0)
    eastward = -speed_mph * math.sin(radians)
    return max(0.0, eastward)


def pressure_adjustment_inches(pressure_mb: float, cfg: dict) -> float:
    """Inches of water added when sea-level pressure is below the reference.

    Equivalent to the owner's ((mb - 1013.21) * -0.3937). High pressure
    returns a negative number and lowers the estimate.
    """
    reference = cfg["pressure"]["reference_mb"]
    per_mb = cfg["pressure"]["inches_per_mb"]
    return (reference - pressure_mb) * per_mb


def wind_adjustment_inches(speed_mph: float, direction_from_deg: float, cfg: dict) -> tuple[float, float]:
    """Return (westerly_mph, inches of water)."""
    westerly = westerly_component_mph(speed_mph, direction_from_deg)
    inches = (westerly / 10.0) * cfg["wind"]["inches_per_10_mph"]
    return westerly, inches


def river_adjustment_inches(gauge_ft: float, cfg: dict) -> tuple[float, float]:
    """Return (feet above the baseline, inches of water). Below the baseline, both are 0."""
    baseline = cfg["river"]["baseline_ft"]
    per_foot = cfg["river"]["inches_per_foot_above_baseline"]
    above = max(0.0, gauge_ft - baseline)
    return above, above * per_foot


def predicted_actual_ft(tide_ft: float, pressure_in: float, wind_in: float, river_in: float) -> float:
    return tide_ft + (pressure_in + wind_in + river_in) / 12.0


def feet_per_step(cfg: dict) -> float:
    return cfg["pilings"]["inches_between_steps"] / 12.0


def steps_showing(height_ft: float, cfg: dict) -> float:
    """Estimated piling steps still above the water.

    The lowest of 10 steps is about a 10 ft tide, and the steps are about
    a foot apart, so an 11 ft tide leaves 9 steps showing and a 15 ft tide
    leaves 5. Values above the step count mean the water is still below
    the lowest step. Negative values mean the water is above the top step.
    """
    lowest = cfg["pilings"]["feet_at_lowest_step"]
    count = cfg["pilings"]["step_count"]
    return count - (height_ft - lowest) / feet_per_step(cfg)


def height_from_steps(steps: float, cfg: dict) -> float:
    lowest = cfg["pilings"]["feet_at_lowest_step"]
    count = cfg["pilings"]["step_count"]
    return lowest + (count - steps) * feet_per_step(cfg)


def apply_formula(
    tide_ft: float,
    pressure_mb: float,
    wind_mph: float,
    wind_dir_deg: float,
    river_ft: float,
    cfg: dict,
) -> dict:
    pressure_in = pressure_adjustment_inches(pressure_mb, cfg)
    westerly, wind_in = wind_adjustment_inches(wind_mph, wind_dir_deg, cfg)
    above, river_in = river_adjustment_inches(river_ft, cfg)
    actual = predicted_actual_ft(tide_ft, pressure_in, wind_in, river_in)
    return {
        "predicted_tide_ft": tide_ft,
        "pressure_mb": pressure_mb,
        "pressure_adjust_in": pressure_in,
        "wind_mph": wind_mph,
        "wind_dir_deg": wind_dir_deg,
        "wind_compass": compass(wind_dir_deg),
        "westerly_mph": westerly,
        "wind_adjust_in": wind_in,
        "river_ft": river_ft,
        "river_above_baseline_ft": above,
        "river_adjust_in": river_in,
        "predicted_actual_ft": actual,
        "steps_showing_est": steps_showing(actual, cfg),
        "likely_flood": actual >= cfg["flood"]["likely_flood_ft"],
    }
