"""Hindcast the two photographed floods and write data/backtest.json.

Run from the repo root or from anywhere:

    python scripts/backtest.py

The daily page build reads this file. It does not refetch the historical
weather, so a flaky archive does not take the morning forecast down.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetchers
import model

ROOT = model.ROOT
PT = ZoneInfo("America/Los_Angeles")

# Transcribed from the owner's spreadsheet images in the background write-up.
# Pressure, river, and wind adjustments in that sheet are in feet.
EVENTS = [
    {
        "id": "2021-11-15",
        "label": "November 15, 2021",
        "photo_time": "2021-11-15T15:02:09-08:00",
        "image": "images/2021-11-15.jpg",
        "observed_steps": 5,
        "observed_height_ft": 15.0,
        "narrative": (
            "The photo is time-stamped 3:02 PM. The owner's spreadsheet "
            "records 5 steps still showing and an actual height of 15 ft, "
            "3.50 ft above the tide value in that sheet. The write-up says "
            "the westerly wind pushed water over the berm where the boats are kept."
        ),
        "owner": {
            "predicted_tide_ft": 11.50,
            "pressure_inhg": 29.46,
            "pressure_mb": 997.63,
            "wind_text": "W 48 gust 60",
            "wind_mph": 48.0,
            "wind_dir_deg": 270.0,
            "wind_gust_mph": 60.0,
            "river_ft": 33.93,
            "sheet_pressure_ft": 0.51,
            "sheet_river_ft": 1.393,
            "sheet_wind_ft": 1.60,
            "sheet_delta_ft": 3.50,
        },
    },
    {
        "id": "2022-12-27",
        "label": "December 27, 2022",
        "photo_time": "2022-12-27T08:45:14-08:00",
        "image": "images/2022-12-27.jpg",
        "observed_steps": 5,
        "observed_height_ft": 15.0,
        "narrative": (
            "The photo is time-stamped 8:45 AM. The owner's spreadsheet "
            "records 5 steps still showing and an actual height of 15 ft, "
            "2.10 ft above the tide value in that sheet. The write-up says "
            "the Skagit was sending about 54,000 cubic feet of water into "
            "the bay every second."
        ),
        "owner": {
            "predicted_tide_ft": 12.90,
            "pressure_inhg": 28.86,
            "pressure_mb": 977.31,
            "wind_text": "SSE 30 gust 41",
            "wind_mph": 30.0,
            "wind_dir_deg": 157.5,
            "wind_gust_mph": 41.0,
            "river_ft": 24.97,
            "sheet_pressure_ft": 1.18,
            "sheet_river_ft": 0.497,
            "sheet_wind_ft": 0.0,
            "sheet_delta_ft": 2.10,
        },
    },
]


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.isoformat()


def _nearest_high(predictions: list[dict], moment: datetime) -> dict | None:
    highs = []
    for row in predictions:
        if row.get("type") != "H":
            continue
        when = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=PT)
        highs.append({"time": when, "predicted_tide_ft": float(row["v"])})
    if not highs:
        return None
    best = min(highs, key=lambda item: abs((item["time"] - moment).total_seconds()))
    if abs((best["time"] - moment).total_seconds()) > 6 * 3600:
        return None
    return best


def _nearest_value(points: list[tuple[datetime, float]], moment: datetime, hours: float = 2.0):
    if not points:
        return None
    when, value = min(points, key=lambda item: abs((item[0] - moment).total_seconds()))
    if abs((when - moment).total_seconds()) > hours * 3600:
        return None
    return {"time": when, "value": value}


def build_event(event: dict, cfg: dict) -> dict:
    photo = datetime.fromisoformat(event["photo_time"])
    window_start = photo - timedelta(hours=12)
    window_end = photo + timedelta(hours=12)
    predictions = fetchers.fetch_noaa_predictions(cfg["tide"]["station_id"], window_start, window_end)
    high = _nearest_high(predictions, photo)
    if high is None:
        raise fetchers.FetchError(f"No NOAA high tide near {event['id']}")

    asos = fetchers.fetch_iem_asos(photo)
    weather = fetchers.nearest_row(asos, photo, max_hours=2)
    if weather is None or weather["pressure_mb"] is None or weather["wind_mph"] is None or weather["wind_dir_deg"] is None:
        raise fetchers.FetchError(f"KNUW observations missing near {event['id']}")

    usgs = fetchers.fetch_usgs_series(cfg["river"]["usgs_site"], photo - timedelta(hours=6), photo + timedelta(hours=6))
    stage = _nearest_value(usgs["00065"], photo, hours=3)
    flow = _nearest_value(usgs["00060"], photo, hours=3)
    if stage is None:
        raise fetchers.FetchError(f"USGS gauge height missing near {event['id']}")

    owner = event["owner"]
    owner_formula = model.apply_formula(
        owner["predicted_tide_ft"],
        owner["pressure_mb"],
        owner["wind_mph"],
        owner["wind_dir_deg"],
        owner["river_ft"],
        cfg,
    )
    retrieved_formula = model.apply_formula(
        high["predicted_tide_ft"],
        weather["pressure_mb"],
        weather["wind_mph"],
        weather["wind_dir_deg"],
        stage["value"],
        cfg,
    )
    observed = event["observed_height_ft"]
    return {
        "id": event["id"],
        "label": event["label"],
        "photo_time": event["photo_time"],
        "image": event["image"],
        "narrative": event["narrative"],
        "observed_steps": event["observed_steps"],
        "observed_height_ft": observed,
        "owner_inputs": owner,
        "owner_formula": owner_formula,
        "owner_error_ft": owner_formula["predicted_actual_ft"] - observed,
        "retrieved": {
            "tide_time": _iso(high["time"]),
            "predicted_tide_ft": high["predicted_tide_ft"],
            "tide_source": f"NOAA predictions {cfg['tide']['station_id']} MLLW, high nearest the photo",
            "weather_time": _iso(weather["time"]),
            "pressure_mb": weather["pressure_mb"],
            "wind_mph": weather["wind_mph"],
            "wind_dir_deg": weather["wind_dir_deg"],
            "wind_gust_mph": weather["gust_mph"],
            "wind_knots": weather["wind_knots"],
            "gust_knots": weather["gust_knots"],
            "weather_source": "Iowa Environmental Mesonet ASOS archive, station NUW (KNUW), nearest hour",
            "river_time": _iso(stage["time"]),
            "river_ft": stage["value"],
            "river_cfs": None if flow is None else flow["value"],
            "river_source": f"USGS {cfg['river']['usgs_site']} instantaneous gauge height nearest the photo",
        },
        "retrieved_formula": retrieved_formula,
        "retrieved_error_ft": retrieved_formula["predicted_actual_ft"] - observed,
    }


def main() -> None:
    cfg = model.load_config()
    events = [build_event(event, cfg) for event in EVENTS]
    payload = {
        "generated_at": datetime.now(PT).isoformat(),
        "observed_height_note": (
            "Both photos were read by the owner as 5 of 10 steps showing. "
            "On the piling scale in the write-up, that is 15.0 ft."
        ),
        "events": events,
    }
    destination = ROOT / "data" / "backtest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {destination}")
    for event in events:
        print(
            f"{event['id']}: owner-input estimate {event['owner_formula']['predicted_actual_ft']:.2f} ft "
            f"(error {event['owner_error_ft']:+.2f}); "
            f"retrieved estimate {event['retrieved_formula']['predicted_actual_ft']:.2f} ft "
            f"(error {event['retrieved_error_ft']:+.2f}); observed {event['observed_height_ft']:.2f} ft"
        )


if __name__ == "__main__":
    main()
