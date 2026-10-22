"""Fetch today's inputs, update the history log, and write the static page.

    python scripts/build_site.py
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetchers
import model
import render

ROOT = model.ROOT
DATA = ROOT / "data"
SITE = ROOT / "site"
HISTORY_CSV = DATA / "history.csv"
HISTORY_JSONL = DATA / "history.jsonl"
LATEST_JSON = DATA / "latest.json"
BACKTEST_JSON = DATA / "backtest.json"
OBSERVATIONS = ROOT / "observations.csv"

CSV_FIELDS = [
    "run_generated_at",
    "run_date",
    "high_tide_time",
    "predicted_tide_ft",
    "pressure_mb",
    "pressure_source",
    "pressure_adjust_in",
    "wind_mph",
    "wind_dir_deg",
    "wind_compass",
    "wind_gust_mph",
    "westerly_mph",
    "wind_adjust_in",
    "wind_source",
    "river_ft",
    "river_source",
    "river_time",
    "river_adjust_in",
    "predicted_actual_ft",
    "steps_showing_est",
    "likely_flood",
    "flood_threshold_ft",
    "incomplete",
]


def num(value, digits=4):
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def load_history() -> list[dict]:
    if not HISTORY_JSONL.exists():
        return []
    runs = []
    for line in HISTORY_JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            runs.append(json.loads(line))
    return runs


def write_history(runs: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    HISTORY_JSONL.write_text(
        "".join(json.dumps(run, separators=(",", ":")) + "\n" for run in runs),
        encoding="utf-8",
    )
    with HISTORY_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for run in runs:
            for tide in run["tides"]:
                writer.writerow({field: tide.get(field, "") for field in CSV_FIELDS})


def load_observations(cfg: dict, zone: ZoneInfo) -> list[dict]:
    if not OBSERVATIONS.exists():
        return []
    rows = []
    with OBSERVATIONS.open(encoding="utf-8", newline="") as fh:
        for record in csv.DictReader(fh):
            raw_time = (record.get("observed_at") or "").strip()
            if not raw_time:
                continue
            when = datetime.fromisoformat(raw_time)
            if when.tzinfo is None:
                when = when.replace(tzinfo=zone)
            steps_text = (record.get("steps_showing") or "").strip()
            height_text = (record.get("actual_height_ft") or "").strip()
            steps = float(steps_text) if steps_text else None
            height = float(height_text) if height_text else None
            if height is None and steps is not None:
                height = model.height_from_steps(steps, cfg)
            rows.append({
                "observed_at": when,
                "steps_showing": steps,
                "actual_height_ft": height,
                "notes": (record.get("notes") or "").strip(),
            })
    rows.sort(key=lambda item: item["observed_at"])
    return rows


def load_backtest() -> dict | None:
    if not BACKTEST_JSON.exists():
        return None
    return json.loads(BACKTEST_JSON.read_text(encoding="utf-8"))


def wind_intervals(block: dict) -> list[tuple[datetime, datetime, float]]:
    uom = block.get("uom")
    parsed = fetchers.parse_nws_intervals(block.get("values") or [])
    return [(start, end, fetchers.to_mph(value, uom)) for start, end, value in parsed]


def direction_intervals(block: dict) -> list[tuple[datetime, datetime, float]]:
    return fetchers.parse_nws_intervals(block.get("values") or [])


def pressure_series_from_grid(block: dict) -> list[tuple[datetime, float]]:
    uom = block.get("uom")
    series = []
    for start, _end, value in fetchers.parse_nws_intervals(block.get("values") or []):
        series.append((start, fetchers.to_mb(value, uom)))
    return series


def grid_code(grid: dict) -> str:
    return f"{grid['grid_id']} {grid['grid_x']},{grid['grid_y']}"


def wind_from_grid(grid: dict) -> tuple[list, list, list] | None:
    props = grid["properties"]
    speeds = wind_intervals(props.get("windSpeed") or {})
    directions = direction_intervals(props.get("windDirection") or {})
    gusts = wind_intervals(props.get("windGust") or {})
    if speeds and directions:
        return speeds, directions, gusts
    return None


def resolve_forecast_wind(cfg: dict, beach_grid: dict | None) -> tuple[list, list, list, str, dict, list[str]]:
    """Wind at the beach, then the hourly forecast there, then the KNUW grid."""
    forecast = cfg["weather"]["forecast"]
    observation = cfg["weather"]["observation"]
    place = forecast["label"]
    notes: list[str] = []

    if beach_grid is not None:
        parsed = wind_from_grid(beach_grid)
        if parsed is not None:
            speeds, directions, gusts = parsed
            source = f"NWS forecast at {place} ({grid_code(beach_grid)})"
            return speeds, directions, gusts, source, beach_grid, notes
        hourly_url = beach_grid.get("forecast_url")
        if hourly_url:
            try:
                periods = fetchers.fetch_nws_hourly(hourly_url)
                hourly = fetchers.hourly_wind_intervals(periods)
            except fetchers.FetchError as exc:
                notes.append(f"The NWS hourly forecast at {place} was unavailable ({exc}).")
            else:
                if hourly["speeds"] and hourly["directions"]:
                    notes.append(
                        f"The NWS grid for {place} did not include wind speed and direction, "
                        "so the hourly forecast at that same point is used."
                    )
                    source = f"NWS hourly forecast at {place} ({grid_code(beach_grid)})"
                    return hourly["speeds"], hourly["directions"], hourly["gusts"], source, beach_grid, notes
                notes.append(f"The NWS hourly forecast at {place} did not include wind speed and direction.")
        else:
            notes.append(f"The NWS grid for {place} did not include wind speed and direction.")

    station = observation["label"]
    try:
        fallback = fetchers.fetch_nws_grid(observation["latitude"], observation["longitude"])
    except fetchers.FetchError as exc:
        raise fetchers.FetchError(
            f"NWS wind was unavailable at {place} and at {station} ({exc})."
        ) from exc
    parsed = wind_from_grid(fallback)
    if parsed is None:
        raise fetchers.FetchError(
            f"NWS wind was missing at {place} and the {station} grid also had no wind speed and direction."
        )
    notes.append(
        f"Forecast wind is from {observation['short_label']} ({grid_code(fallback)}) "
        f"because the {place} forecast had no wind."
    )
    speeds, directions, gusts = parsed
    source = (
        f"NWS forecast at {observation['short_label']} ({grid_code(fallback)}), "
        f"because the {place} forecast had no wind"
    )
    return speeds, directions, gusts, source, fallback, notes


def resolve_forecast_pressure(cfg: dict, beach_grid: dict | None) -> tuple[list, str, str]:
    """Pressure at the beach grid, then Open-Meteo at the beach, then Open-Meteo at KNUW."""
    forecast = cfg["weather"]["forecast"]
    observation = cfg["weather"]["observation"]
    place = forecast["label"]
    props = (beach_grid or {}).get("properties") or {}
    nws_pressure = pressure_series_from_grid(props.get("pressure") or {})
    if nws_pressure:
        return (
            nws_pressure,
            f"NWS sea-level pressure forecast at {place}",
            f"Sea-level pressure is the NWS grid forecast at {place}.",
        )
    try:
        points = fetchers.fetch_open_meteo_pressure(forecast["latitude"], forecast["longitude"])
    except fetchers.FetchError as exc:
        try:
            points = fetchers.fetch_open_meteo_pressure(
                observation["latitude"], observation["longitude"],
            )
        except fetchers.FetchError as fallback_exc:
            raise fetchers.FetchError(
                f"Sea-level pressure was unavailable at {place} ({exc}) "
                f"and at {observation['label']} ({fallback_exc})."
            ) from fallback_exc
        return (
            points,
            f"Open-Meteo sea-level pressure forecast at {observation['short_label']}",
            (
                f"Open-Meteo at {place} was unavailable ({exc}). "
                f"Sea-level pressure is the Open-Meteo forecast at {observation['label']}."
            ),
        )
    address = forecast.get("address") or place
    return (
        points,
        f"Open-Meteo sea-level pressure forecast at {place}",
        (
            f"The NWS forecast grid for {place} did not include pressure. "
            f"Sea-level pressure is the Open-Meteo forecast at {address}."
        ),
    )


def observation_snapshot(props: dict | None, zone: ZoneInfo) -> dict:
    if not props:
        return {}
    stamp = props.get("timestamp")
    when = datetime.fromisoformat(stamp) if stamp else None
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=zone)
    direction = props.get("windDirection") or {}
    direction_deg = direction.get("value")
    return {
        "time": when,
        "pressure_mb": fetchers.quantity_mb(props.get("seaLevelPressure")),
        "station_pressure_mb": fetchers.quantity_mb(props.get("barometricPressure")),
        "wind_mph": fetchers.quantity_mph(props.get("windSpeed")),
        "wind_dir_deg": None if direction_deg is None else float(direction_deg),
        "wind_compass": model.compass(None if direction_deg is None else float(direction_deg)),
        "wind_gust_mph": fetchers.quantity_mph(props.get("windGust")),
        "text": props.get("textDescription") or "",
    }


def build_tides(cfg: dict, now: datetime) -> tuple[list[dict], dict, list[str]]:
    zone = now.tzinfo
    warnings: list[str] = []
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Through the end of the day `forecast_days` ahead, so the last day is complete.
    end = (start + timedelta(days=cfg["forecast_days"])).replace(hour=23, minute=59, second=59)
    predictions = fetchers.fetch_noaa_predictions(
        cfg["tide"]["station_id"],
        start,
        end + timedelta(days=1),
    )
    station_name = fetchers.fetch_station_name(cfg["tide"]["station_id"])

    forecast = cfg["weather"]["forecast"]
    observation = cfg["weather"]["observation"]
    beach_grid = None
    try:
        beach_grid = fetchers.fetch_nws_grid(forecast["latitude"], forecast["longitude"])
    except fetchers.FetchError as exc:
        warnings.append(f"The NWS forecast grid for {forecast['label']} was unavailable ({exc}).")

    speeds, directions, gusts, wind_source, wind_grid, wind_notes = resolve_forecast_wind(cfg, beach_grid)
    warnings.extend(wind_notes)
    pressure_points, forecast_pressure_source, pressure_note = resolve_forecast_pressure(cfg, beach_grid)
    pressure_note += (
        f" A high tide within two hours of the latest {observation['short_label']} "
        f"({observation['station_id']}) observation uses that observed sea-level pressure instead."
    )

    knuw = observation_snapshot(
        fetchers.fetch_station_observation(observation["station_id"]),
        zone,
    )
    try:
        usgs = fetchers.fetch_usgs_series(cfg["river"]["usgs_site"])
    except fetchers.FetchError as exc:
        usgs = {"00065": [], "00060": []}
        warnings.append(f"USGS gauge was unavailable ({exc}).")
    stage_points = usgs["00065"]
    flow_points = usgs["00060"]
    usgs_stage = stage_points[-1] if stage_points else None
    usgs_flow = flow_points[-1] if flow_points else None
    current_source = f"USGS {cfg['river']['usgs_site']} current reading"
    if usgs_stage is None:
        try:
            observed = fetchers.fetch_nwps_observed(cfg["river"]["nws_lid"])
        except fetchers.FetchError as exc:
            observed = None
            warnings.append(f"Skagit observed stage was unavailable ({exc}).")
        if observed is not None:
            usgs_stage = (observed["time"], observed["stage_ft"])
            if observed.get("flow_cfs") is not None:
                usgs_flow = (observed["time"], observed["flow_cfs"])
            current_source = f"{cfg['river']['nws_lid']} observed stage"
            warnings.append("The current Skagit height is the National Weather Service gauge observation, because USGS did not respond.")

    try:
        river_forecast = fetchers.fetch_nwps_forecast(cfg["river"]["nws_lid"])
    except fetchers.FetchError as exc:
        river_forecast = []
        warnings.append(f"Skagit forecast was unavailable ({exc}). Future tides use the current gauge if there is one.")

    if usgs_stage is None and not river_forecast:
        warnings.append("No Skagit gauge reading or river forecast. River adjustments are missing.")

    river_note = (
        f"River forecast is National Water Prediction Service {cfg['river']['nws_lid']}. "
        "Tides outside that forecast use the current USGS reading."
    )
    if not river_forecast:
        river_note = "No MVEW1 forecast was available, so the river term uses the current USGS reading."

    tides = []
    used_current_river = False
    for row in predictions:
        if row.get("type") != "H":
            continue
        when = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=zone)
        if when < start or when > end:
            continue
        predicted = float(row["v"])
        speed_hit = fetchers.value_covering(speeds, when)
        direction_hit = fetchers.value_covering(directions, when)
        gust_hit = fetchers.value_covering(gusts, when)
        wind_mph = None if speed_hit is None else speed_hit[2]
        wind_dir = None if direction_hit is None else direction_hit[2]
        if wind_mph is not None and wind_mph < 0.5:
            wind_dir = 0.0 if wind_dir is None else wind_dir
        gust_mph = None if gust_hit is None else gust_hit[2]

        pressure_mb = None
        pressure_source = forecast_pressure_source
        obs_time = knuw.get("time")
        obs_pressure = knuw.get("pressure_mb")
        if (
            obs_time is not None
            and obs_pressure is not None
            and abs(when - obs_time) <= timedelta(hours=2)
        ):
            pressure_mb = obs_pressure
            pressure_source = (
                f"{observation['short_label']} ({observation['station_id']}) observed sea-level pressure"
            )
        else:
            pressure_mb = fetchers.pressure_at(pressure_points, when)

        river_ft = None
        river_source = ""
        river_time = None
        if river_forecast and river_forecast[0]["time"] <= when <= river_forecast[-1]["time"]:
            hit = fetchers.interpolate_stage(river_forecast, when)
            if hit is not None:
                river_ft = hit["stage_ft"]
                river_source = f"{cfg['river']['nws_lid']} forecast"
                river_time = when
        elif usgs_stage is not None:
            river_ft = usgs_stage[1]
            river_source = current_source
            river_time = usgs_stage[0]
            if when >= now:
                used_current_river = True

        incomplete = pressure_mb is None or wind_mph is None or wind_dir is None or river_ft is None
        result = {}
        if not incomplete:
            result = model.apply_formula(predicted, pressure_mb, wind_mph, wind_dir, river_ft, cfg)
        tides.append({
            "time": when,
            "passed": when < now,
            "incomplete": incomplete,
            "predicted_tide_ft": predicted,
            "pressure_mb": pressure_mb,
            "pressure_source": pressure_source,
            "pressure_adjust_in": result.get("pressure_adjust_in"),
            "wind_mph": wind_mph,
            "wind_dir_deg": wind_dir,
            "wind_compass": model.compass(wind_dir),
            "wind_gust_mph": gust_mph,
            "westerly_mph": result.get("westerly_mph"),
            "wind_adjust_in": result.get("wind_adjust_in"),
            "wind_source": wind_source,
            "river_ft": river_ft,
            "river_source": river_source,
            "river_time": river_time,
            "river_adjust_in": result.get("river_adjust_in"),
            "predicted_actual_ft": result.get("predicted_actual_ft"),
            "steps_showing": result.get("steps_showing_est"),
            "likely_flood": bool(result.get("likely_flood")),
        })

    if used_current_river:
        warnings.append("One or more high tides are outside the Skagit forecast, so those use the current gauge height.")

    tides.sort(key=lambda item: item["time"])
    current = {
        "station_name": station_name,
        "grid": grid_code(wind_grid),
        "pressure_note": pressure_note,
        "wind_note": wind_source if wind_source.endswith(".") else wind_source + ".",
        "river_note": river_note,
        "knuw": knuw,
        "usgs": {
            "time": None if usgs_stage is None else usgs_stage[0],
            "stage_ft": None if usgs_stage is None else usgs_stage[1],
            "flow_cfs": None if usgs_flow is None else usgs_flow[1],
        },
    }
    return tides, current, warnings


def serializable_conditions(current: dict) -> dict:
    knuw = dict(current.get("knuw") or {})
    if isinstance(knuw.get("time"), datetime):
        knuw["time"] = knuw["time"].isoformat()
    usgs = dict(current.get("usgs") or {})
    if isinstance(usgs.get("time"), datetime):
        usgs["time"] = usgs["time"].isoformat()
    return {
        "station_name": current.get("station_name"),
        "grid": current.get("grid"),
        "pressure_note": current.get("pressure_note"),
        "wind_note": current.get("wind_note"),
        "river_note": current.get("river_note"),
        "knuw": knuw,
        "usgs": usgs,
    }


def tide_record(tide: dict, generated: datetime, run_date: str, threshold: float) -> dict:
    return {
        "run_generated_at": generated.isoformat(),
        "run_date": run_date,
        "high_tide_time": tide["time"].isoformat(),
        "predicted_tide_ft": num(tide["predicted_tide_ft"]),
        "pressure_mb": num(tide["pressure_mb"]),
        "pressure_source": tide["pressure_source"],
        "pressure_adjust_in": num(tide["pressure_adjust_in"]),
        "wind_mph": num(tide["wind_mph"]),
        "wind_dir_deg": num(tide["wind_dir_deg"]),
        "wind_compass": tide["wind_compass"],
        "wind_gust_mph": num(tide["wind_gust_mph"]),
        "westerly_mph": num(tide["westerly_mph"]),
        "wind_adjust_in": num(tide["wind_adjust_in"]),
        "wind_source": tide["wind_source"],
        "river_ft": num(tide["river_ft"]),
        "river_source": tide["river_source"],
        "river_time": "" if tide["river_time"] is None else tide["river_time"].isoformat(),
        "river_adjust_in": num(tide["river_adjust_in"]),
        "predicted_actual_ft": num(tide["predicted_actual_ft"]),
        "steps_showing_est": num(tide["steps_showing"]),
        "likely_flood": "yes" if tide["likely_flood"] else "no",
        "flood_threshold_ft": num(threshold, 2),
        "incomplete": "yes" if tide["incomplete"] else "no",
    }


def main() -> None:
    cfg = model.load_config()
    zone = ZoneInfo(cfg["timezone"])
    now = datetime.now(zone)
    tides, current, warnings = build_tides(cfg, now)
    if not tides:
        raise fetchers.FetchError("NOAA returned no high tides in the forecast window")

    run_date = now.date().isoformat()
    runs = [run for run in load_history() if run.get("run_date") != run_date]
    records = [tide_record(tide, now, run_date, cfg["flood"]["likely_flood_ft"]) for tide in tides]
    runs.append({
        "generated_at": now.isoformat(),
        "run_date": run_date,
        "station_name": current.get("station_name"),
        "flood_threshold_ft": cfg["flood"]["likely_flood_ft"],
        "conditions": serializable_conditions(current),
        "warnings": warnings,
        "tides": records,
    })
    runs.sort(key=lambda run: run.get("run_date", ""))
    write_history(runs)

    latest = {
        "generated_at": now.isoformat(),
        "run_date": run_date,
        "station_name": current.get("station_name"),
        "warnings": warnings,
        "conditions": serializable_conditions(current),
        "tides": records,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(json.dumps(latest, indent=2) + "\n", encoding="utf-8")

    page = render.render_page({
        "config": cfg,
        "generated_at": now,
        "station_name": current.get("station_name"),
        "tides": tides,
        "current": current,
        "warnings": warnings,
        "observations": load_observations(cfg, zone),
        "history": runs,
        "backtest": load_backtest(),
    })
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "index.html").write_text(page, encoding="utf-8")
    (SITE / "latest.json").write_text(json.dumps(latest, indent=2) + "\n", encoding="utf-8")
    version = render.version_payload(now, run_date)
    (SITE / "version.json").write_text(json.dumps(version, indent=2) + "\n", encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Wrote {SITE / 'index.html'}")
    print(f"Station: {current.get('station_name')}")
    for tide in tides:
        mark = " FLOOD" if tide["likely_flood"] else ""
        state = "passed" if tide["passed"] else "upcoming"
        actual = "n/a" if tide["predicted_actual_ft"] is None else f"{tide['predicted_actual_ft']:.2f} ft"
        print(
            f"  {tide['time'].strftime('%Y-%m-%d %H:%M')} {state} "
            f"tide {tide['predicted_tide_ft']:.2f} ft  actual {actual}{mark}"
        )


if __name__ == "__main__":
    main()
