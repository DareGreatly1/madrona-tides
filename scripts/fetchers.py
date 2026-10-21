"""Public data sources. No API keys.

Tide predictions: NOAA CO-OPS, station 9447929, datum MLLW, feet.
Wind forecast: api.weather.gov gridpoint forecast at KNUW.
Sea-level pressure: the NWS grid pressure series when it is published,
otherwise the Open-Meteo sea-level pressure forecast at the same
coordinates. The latest KNUW observation (also api.weather.gov) is
kept for the "right now" panel and for a high tide within two hours
of that observation.
Skagit River: USGS 12200500 instantaneous gauge height, and the
National Water Prediction Service forecast for MVEW1 (NWRFC / NWS).
"""

from __future__ import annotations

import csv
import http.client
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

USER_AGENT = "MadronaBeachTides/1.0 (https://github.com/DareGreatly1/madrona-tides; informational tide estimate)"
KMH_TO_MPH = 0.621371
MS_TO_MPH = 2.236936
KT_TO_MPH = 1.15078


class FetchError(RuntimeError):
    pass


def _request(url: str, headers: dict | None = None, timeout: int = 45) -> bytes:
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        merged.update(headers)
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=merged)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"GET failed for {url}: {last}") from last


def get_json(url: str, headers: dict | None = None) -> dict | list:
    raw = _request(url, headers=headers)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise FetchError(f"Invalid JSON from {url}") from exc


def get_text(url: str, headers: dict | None = None) -> str:
    return _request(url, headers=headers).decode("utf-8", errors="replace")


def parse_duration(spec: str) -> timedelta:
    """Parse an ISO-8601 duration such as PT1H, PT3H, or PT30M."""
    if not spec.startswith("PT"):
        raise FetchError(f"Unsupported duration {spec}")
    body = spec[2:]
    hours = 0
    minutes = 0
    if "H" in body:
        hour_text, body = body.split("H", 1)
        hours = int(hour_text or "0")
    if body.endswith("M"):
        minutes = int(body[:-1] or "0")
    elif body:
        raise FetchError(f"Unsupported duration {spec}")
    return timedelta(hours=hours, minutes=minutes)


def parse_nws_intervals(values: list[dict]) -> list[tuple[datetime, datetime, float]]:
    intervals = []
    for item in values:
        if item.get("value") is None or not item.get("validTime"):
            continue
        start_text, duration = item["validTime"].split("/", 1)
        start = datetime.fromisoformat(start_text)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = start + parse_duration(duration)
        intervals.append((start, end, float(item["value"])))
    return intervals


def value_covering(intervals: list[tuple[datetime, datetime, float]], moment: datetime):
    """Interval containing moment, else the nearest interval start within 3 hours."""
    containing = [item for item in intervals if item[0] <= moment < item[1]]
    if containing:
        containing.sort(key=lambda item: item[1] - item[0])
        return containing[0]
    if not intervals:
        return None
    nearest = min(intervals, key=lambda item: abs((item[0] - moment).total_seconds()))
    if abs((nearest[0] - moment).total_seconds()) > 3 * 3600:
        return None
    return nearest


def to_mph(value: float, uom: str | None) -> float:
    unit = (uom or "").lower()
    if "km_h" in unit or "km/h" in unit:
        return value * KMH_TO_MPH
    if "m_s" in unit or "m/s" in unit:
        return value * MS_TO_MPH
    if "kt" in unit or "knot" in unit:
        return value * KT_TO_MPH
    if "mi_h" in unit or "mph" in unit:
        return value
    raise FetchError(f"Unrecognized wind speed unit: {uom}")


def to_mb(value: float, uom: str | None) -> float:
    unit = (uom or "").lower()
    if "pa" in unit and "hpa" not in unit:
        return value / 100.0
    if value > 2000:
        return value / 100.0
    return value


def fetch_noaa_predictions(station_id: str, begin: datetime, end: datetime) -> list[dict]:
    params = {
        "begin_date": begin.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "station": station_id,
        "product": "predictions",
        "datum": "MLLW",
        "time_zone": "lst_ldt",
        "interval": "hilo",
        "units": "english",
        "format": "json",
    }
    url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" + urllib.parse.urlencode(params)
    payload = get_json(url)
    if not isinstance(payload, dict) or "predictions" not in payload:
        message = payload.get("error", payload) if isinstance(payload, dict) else payload
        raise FetchError(f"NOAA tide predictions failed: {message}")
    return payload["predictions"]


def fetch_station_name(station_id: str) -> str:
    url = f"https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{station_id}.json"
    try:
        payload = get_json(url)
        station = payload["stations"][0]
        return station.get("name") or station_id
    except (FetchError, KeyError, IndexError, TypeError):
        return station_id


def fetch_nws_grid(latitude: float, longitude: float) -> dict:
    headers = {"Accept": "application/geo+json"}
    points_url = f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}"
    points = get_json(points_url, headers=headers)
    if not isinstance(points, dict):
        raise FetchError("NWS points lookup failed")
    props = points["properties"]
    grid_url = props["forecastGridData"]
    grid = get_json(grid_url, headers=headers)
    if not isinstance(grid, dict):
        raise FetchError("NWS grid forecast failed")
    return {
        "grid_id": props.get("gridId"),
        "grid_x": props.get("gridX"),
        "grid_y": props.get("gridY"),
        "forecast_url": props.get("forecastHourly"),
        "properties": grid["properties"],
    }


def fetch_knuw_observation() -> dict | None:
    url = "https://api.weather.gov/stations/KNUW/observations/latest"
    try:
        payload = get_json(url, headers={"Accept": "application/geo+json"})
    except FetchError:
        return None
    if not isinstance(payload, dict):
        return None
    props = payload.get("properties") or {}
    return props


def quantity_mb(quantity: dict | None) -> float | None:
    if not quantity or quantity.get("value") is None:
        return None
    return to_mb(float(quantity["value"]), quantity.get("unitCode"))


def quantity_mph(quantity: dict | None) -> float | None:
    if not quantity or quantity.get("value") is None:
        return None
    return to_mph(float(quantity["value"]), quantity.get("unitCode"))


def fetch_open_meteo_pressure(latitude: float, longitude: float) -> list[tuple[datetime, float]]:
    params = {
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "hourly": "pressure_msl",
        "timezone": "America/Los_Angeles",
        "forecast_days": "7",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    payload = get_json(url)
    if not isinstance(payload, dict) or "hourly" not in payload:
        raise FetchError("Open-Meteo pressure forecast failed")
    hourly = payload["hourly"]
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/Los_Angeles")
    series = []
    for stamp, pressure in zip(hourly["time"], hourly["pressure_msl"]):
        if pressure is None:
            continue
        moment = datetime.fromisoformat(stamp).replace(tzinfo=zone)
        series.append((moment, float(pressure)))
    if not series:
        raise FetchError("Open-Meteo returned no pressure values")
    return series


def pressure_at(series: list[tuple[datetime, float]], moment: datetime) -> float | None:
    if not series:
        return None
    earlier = [item for item in series if item[0] <= moment]
    later = [item for item in series if item[0] >= moment]
    if earlier and later and earlier[-1][0] != later[0][0]:
        left = earlier[-1]
        right = later[0]
        span = (right[0] - left[0]).total_seconds()
        if span <= 0 or span > 3 * 3600:
            return left[1]
        weight = (moment - left[0]).total_seconds() / span
        return left[1] + (right[1] - left[1]) * weight
    nearest = min(series, key=lambda item: abs((item[0] - moment).total_seconds()))
    if abs((nearest[0] - moment).total_seconds()) > 3 * 3600:
        return None
    return nearest[1]


def fetch_usgs_series(site: str, start: datetime | None = None, end: datetime | None = None) -> dict[str, list[tuple[datetime, float]]]:
    params = {
        "format": "json",
        "sites": site,
        "parameterCd": "00065,00060",
    }
    if start is not None:
        params["startDT"] = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if end is not None:
        params["endDT"] = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if start is None and end is None:
        params["period"] = "P1D"
    url = "https://waterservices.usgs.gov/nwis/iv/?" + urllib.parse.urlencode(params)
    payload = get_json(url)
    if not isinstance(payload, dict):
        raise FetchError("USGS response was not JSON")
    series: dict[str, list[tuple[datetime, float]]] = {"00065": [], "00060": []}
    try:
        time_series = payload["value"]["timeSeries"]
    except (KeyError, TypeError) as exc:
        raise FetchError("USGS response did not include time series") from exc
    for entry in time_series:
        code = entry["variable"]["variableCode"][0]["value"]
        if code not in series:
            continue
        for row in entry["values"][0].get("value") or []:
            if row.get("value") in (None, "", "-999999"):
                continue
            moment = datetime.fromisoformat(row["dateTime"])
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            series[code].append((moment, float(row["value"])))
    for code in series:
        series[code].sort(key=lambda item: item[0])
        # Collapse duplicate timestamps from overlapping series.
        deduped: dict[datetime, float] = {}
        for moment, value in series[code]:
            deduped[moment] = value
        series[code] = sorted(deduped.items())
    return series


def fetch_nwps_observed(lid: str) -> dict | None:
    """Latest observed stage from the National Water Prediction Service.

    Used when the USGS instantaneous service is unavailable. Stage is feet.
    Secondary flow is thousands of cubic feet per second.
    """
    url = f"https://api.water.noaa.gov/nwps/v1/gauges/{lid}"
    payload = get_json(url)
    if not isinstance(payload, dict):
        return None
    observed = (payload.get("status") or {}).get("observed") or {}
    if observed.get("primary") is None or not observed.get("validTime"):
        return None
    moment = datetime.fromisoformat(observed["validTime"].replace("Z", "+00:00"))
    flow = observed.get("secondary")
    return {
        "time": moment,
        "stage_ft": float(observed["primary"]),
        "flow_cfs": None if flow is None else float(flow) * 1000.0,
    }


def fetch_nwps_forecast(lid: str) -> list[dict]:
    url = f"https://api.water.noaa.gov/nwps/v1/gauges/{lid}/stageflow"
    payload = get_json(url)
    if not isinstance(payload, dict) or "forecast" not in payload:
        raise FetchError(f"No NWPS forecast for {lid}")
    forecast = payload["forecast"]
    points = []
    for row in forecast.get("data") or []:
        if row.get("primary") is None or not row.get("validTime"):
            continue
        moment = datetime.fromisoformat(row["validTime"].replace("Z", "+00:00"))
        secondary = row.get("secondary")
        points.append({
            "time": moment,
            "stage_ft": float(row["primary"]),
            "flow_kcfs": None if secondary is None else float(secondary),
            "issued": forecast.get("issuedTime"),
        })
    points.sort(key=lambda item: item["time"])
    return points


def interpolate_stage(points: list[dict], moment: datetime) -> dict | None:
    if not points:
        return None
    earlier = [item for item in points if item["time"] <= moment]
    later = [item for item in points if item["time"] >= moment]
    if earlier and later:
        left = earlier[-1]
        right = later[0]
        if left["time"] == right["time"]:
            return dict(left)
        span = (right["time"] - left["time"]).total_seconds()
        if span > 18 * 3600:
            return None
        weight = (moment - left["time"]).total_seconds() / span
        stage = left["stage_ft"] + (right["stage_ft"] - left["stage_ft"]) * weight
        return {"time": moment, "stage_ft": stage, "bracket": [left["time"].isoformat(), right["time"].isoformat()]}
    nearest = min(points, key=lambda item: abs((item["time"] - moment).total_seconds()))
    if abs((nearest["time"] - moment).total_seconds()) > 6 * 3600:
        return None
    return dict(nearest)


def fetch_iem_asos(day: datetime) -> list[dict]:
    """Hourly KNUW (IEM station NUW) observations for one Pacific calendar day."""
    params = [
        ("station", "NUW"),
        ("data", "drct"),
        ("data", "sknt"),
        ("data", "gust"),
        ("data", "mslp"),
        ("year1", str(day.year)),
        ("month1", str(day.month)),
        ("day1", str(day.day)),
        ("year2", str(day.year)),
        ("month2", str(day.month)),
        ("day2", str(day.day)),
        ("tz", "America/Los_Angeles"),
        ("format", "onlycomma"),
        ("latlon", "no"),
        ("elev", "no"),
        ("missing", "M"),
        ("trace", "T"),
        ("direct", "no"),
        ("report_type", "3"),
    ]
    url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" + urllib.parse.urlencode(params)
    text = get_text(url)
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/Los_Angeles")
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        if not record.get("valid"):
            continue
        moment = datetime.strptime(record["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=zone)
        def num(field: str) -> float | None:
            raw = (record.get(field) or "").strip()
            if raw in ("", "M", "null"):
                return None
            return float(raw)

        direction = num("drct")
        knots = num("sknt")
        gust = num("gust")
        pressure = num("mslp")
        rows.append({
            "time": moment,
            "wind_dir_deg": direction,
            "wind_mph": None if knots is None else knots * KT_TO_MPH,
            "wind_knots": knots,
            "gust_mph": None if gust is None else gust * KT_TO_MPH,
            "gust_knots": gust,
            "pressure_mb": pressure,
        })
    return rows


def nearest_row(rows: list[dict], moment: datetime, max_hours: float = 2.0) -> dict | None:
    if not rows:
        return None
    best = min(rows, key=lambda row: abs((row["time"] - moment).total_seconds()))
    if abs((best["time"] - moment).total_seconds()) > max_hours * 3600:
        return None
    return best
