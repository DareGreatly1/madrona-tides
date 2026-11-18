"""The open page must be able to notice a newly published forecast."""

from __future__ import annotations

import json
import sys
import unittest
import io
import urllib.error
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site
import fetchers
import model
import render


class RefreshMarkupTests(unittest.TestCase):
    def setUp(self):
        self.when = datetime(2026, 10, 22, 6, 40, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.page = render.render_page({
            "config": model.load_config(),
            "generated_at": self.when,
            "station_name": "Coupeville",
            "tides": [],
            "current": {},
            "warnings": [],
            "observations": [],
            "history": [],
            "backtest": None,
        })

    def test_last_updated_is_visible_and_machine_readable(self):
        iso = self.when.isoformat()
        self.assertIn(f'<time id="last-updated" datetime="{iso}">', self.page)
        self.assertIn("Last updated", self.page)
        self.assertEqual(self.page.count(f'datetime="{iso}"'), 2)
        self.assertIn(f'<meta name="forecast-generated-at" content="{iso}">', self.page)

    def test_poll_busts_the_pages_cache_and_reloads_on_a_new_timestamp(self):
        self.assertIn('fetch("version.json?t=" + Date.now()', self.page)
        self.assertIn('cache: "no-store"', self.page)
        self.assertIn("180000", self.page)
        self.assertIn("window.location.replace", self.page)
        self.assertIn("history.replaceState", self.page)
        self.assertIn('visibilityState === "hidden"', self.page)
        self.assertIn("sessionStorage", self.page)

    def test_forecast_is_the_beach_and_observations_stay_at_ault_field(self):
        cfg = model.load_config()
        forecast = cfg["weather"]["forecast"]
        observation = cfg["weather"]["observation"]
        self.assertEqual(forecast["address"], "279 Alder St, Camano Island, WA 98282")
        self.assertAlmostEqual(forecast["latitude"], 48.221356)
        self.assertAlmostEqual(forecast["longitude"], -122.533162)
        self.assertEqual(observation["station_id"], "KNUW")
        self.assertAlmostEqual(observation["latitude"], 48.3518)
        self.assertIn("Forecast at Madrona Beach, observations from Ault Field.", self.page)
        self.assertIn("api.weather.gov/points/48.221356,-122.533162", self.page)
        self.assertIn("stations/KNUW/observations/latest", self.page)
        self.assertNotIn("NWS forecast grid for KNUW", self.page)
        self.assertNotIn("Open-Meteo forecast at the KNUW coordinates", self.page)
        self.assertIn("Potential flooding above 14 ft.", self.page)
        self.assertNotIn("A high tide is flagged at", self.page)

    def test_utc_observation_time_is_shown_in_pacific(self):
        moment = datetime(2026, 10, 22, 12, 53, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(render.fmt_short(moment), "Oct 22, 5:53 AM")
        self.assertIn("5:53 AM PDT", render.fmt_when(moment))

    def test_hourly_wind_text_uses_the_midpoint(self):
        self.assertEqual(fetchers.parse_wind_speed_mph("5 to 10 mph"), 7.5)
        self.assertEqual(fetchers.parse_wind_speed_mph("Calm"), 0.0)
        periods = [{
            "startTime": "2026-10-22T15:00:00-07:00",
            "endTime": "2026-10-22T16:00:00-07:00",
            "windSpeed": "5 to 10 mph",
            "windDirection": "WNW",
            "windGust": "15 mph",
        }]
        parsed = fetchers.hourly_wind_intervals(periods)
        self.assertEqual(parsed["speeds"][0][2], 7.5)
        self.assertEqual(parsed["directions"][0][2], 292.5)
        self.assertEqual(parsed["gusts"][0][2], 15.0)

    def test_version_file_uses_the_same_timestamp_as_the_page(self):
        payload = render.version_payload(self.when, "2026-10-22")
        self.assertEqual(payload["generated_at"], self.when.isoformat())
        self.assertIn(payload["generated_at"], self.page)
        json.dumps(payload)


class NwsDurationTests(unittest.TestCase):
    def test_hour_periods_stay_the_same(self):
        self.assertEqual(fetchers.parse_duration("PT1H"), timedelta(hours=1))
        self.assertEqual(fetchers.parse_duration("PT3H"), timedelta(hours=3))
        self.assertEqual(fetchers.parse_duration("PT30M"), timedelta(minutes=30))
        self.assertEqual(fetchers.parse_duration("PT13H30M"), timedelta(hours=13, minutes=30))

    def test_day_period_that_stopped_the_november_7_build(self):
        self.assertEqual(fetchers.parse_duration("P1DT15H"), timedelta(days=1, hours=15))
        self.assertEqual(fetchers.parse_duration("P1D"), timedelta(days=1))
        self.assertEqual(fetchers.parse_duration("P7DT10H"), timedelta(days=7, hours=10))
        intervals = fetchers.parse_nws_intervals([{
            "validTime": "2026-11-07T18:00:00+00:00/P1DT15H",
            "value": 150,
        }])
        start, end, value = intervals[0]
        self.assertEqual(end - start, timedelta(days=1, hours=15))
        self.assertEqual(value, 150)

    def test_unknown_duration_still_fails(self):
        with self.assertRaises(fetchers.FetchError):
            fetchers.parse_duration("P1W")
        with self.assertRaises(fetchers.FetchError):
            fetchers.parse_duration("P1DT")


class PressureFallbackTests(unittest.TestCase):
    def setUp(self):
        self.zone = timezone.utc
        self.observed = "Ault Field (KNUW) observed sea-level pressure"
        self.held = "Ault Field (KNUW) observed sea-level pressure, held for this hour"
        self.forecast = "Open-Meteo sea-level pressure forecast at Madrona Beach"
        self.standard = "Standard pressure (1013.21 mb); no pressure adjustment"

    def choose(self, when, observations, forecast):
        return build_site.pressure_for_tide(
            when, observations, forecast, 1013.21,
            self.forecast, self.observed, self.held, self.standard,
        )

    def test_near_term_uses_the_knuw_observation(self):
        when = datetime(2026, 11, 15, 16, 0, tzinfo=self.zone)
        observations = [
            (datetime(2026, 11, 15, 12, 0, tzinfo=self.zone), 1000.0),
            (datetime(2026, 11, 15, 15, 30, tzinfo=self.zone), 1008.0),
        ]
        forecast = [(datetime(2026, 11, 15, 16, 0, tzinfo=self.zone), 1020.0)]
        pressure, source = self.choose(when, observations, forecast)
        self.assertEqual(pressure, 1008.0)
        self.assertEqual(source, self.observed)

    def test_later_hour_uses_the_forecast(self):
        when = datetime(2026, 11, 16, 16, 0, tzinfo=self.zone)
        observations = [(datetime(2026, 11, 15, 15, 0, tzinfo=self.zone), 1008.0)]
        forecast = [(datetime(2026, 11, 16, 16, 0, tzinfo=self.zone), 1022.0)]
        pressure, source = self.choose(when, observations, forecast)
        self.assertEqual(pressure, 1022.0)
        self.assertEqual(source, self.forecast)

    def test_missing_forecast_holds_the_latest_observation(self):
        when = datetime(2026, 11, 17, 4, 0, tzinfo=self.zone)
        observations = [
            (datetime(2026, 11, 15, 12, 0, tzinfo=self.zone), 1000.0),
            (datetime(2026, 11, 15, 18, 0, tzinfo=self.zone), 1004.0),
        ]
        pressure, source = self.choose(when, observations, None)
        self.assertEqual(pressure, 1004.0)
        self.assertEqual(source, self.held)

    def test_total_failure_uses_standard_pressure_with_no_adjustment(self):
        when = datetime(2026, 11, 15, 16, 0, tzinfo=self.zone)
        pressure, source = self.choose(when, [], None)
        self.assertEqual(pressure, 1013.21)
        self.assertEqual(source, self.standard)
        cfg = model.load_config()
        self.assertEqual(model.pressure_adjustment_inches(pressure, cfg), 0)

    def test_standard_pressure_note_is_on_the_page(self):
        note = "Pressure readings were unavailable, so this forecast adds no pressure adjustment."
        page = render.render_page({
            "config": model.load_config(),
            "generated_at": datetime(2026, 11, 15, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
            "station_name": "Coupeville",
            "tides": [],
            "current": {"pressure_alert": note},
            "warnings": [],
            "observations": [],
            "history": [],
            "backtest": None,
        })
        self.assertIn(f'id="pressure-note">{note}', page)

    def test_knuw_observations_collection_is_sea_level_pressure(self):
        original = fetchers.get_json

        def fake(url, headers=None):
            self.assertIn("/stations/KNUW/observations", url)
            self.assertNotIn("/latest", url)
            return {"features": [
                {"properties": {
                    "timestamp": "2026-11-15T16:00:00+00:00",
                    "seaLevelPressure": {"value": 101320, "unitCode": "wmoUnit:Pa"},
                }},
                {"properties": {
                    "timestamp": "2026-11-15T15:00:00+00:00",
                    "seaLevelPressure": {"value": None, "unitCode": "wmoUnit:Pa"},
                }},
                {"properties": {
                    "timestamp": "2026-11-15T17:00:00+00:00",
                    "seaLevelPressure": {"value": 101500, "unitCode": "wmoUnit:Pa"},
                }},
            ]}

        fetchers.get_json = fake
        try:
            series = fetchers.fetch_station_pressure_observations("KNUW")
        finally:
            fetchers.get_json = original
        self.assertEqual([item[1] for item in series], [1013.2, 1015.0])
        self.assertLess(series[0][0], series[1][0])


class OpenMeteoBackoffTests(unittest.TestCase):
    def http_error(self, code, retry_after=None):
        headers = EmailMessage()
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        return urllib.error.HTTPError(
            "https://api.open-meteo.com/v1/forecast",
            code,
            "error",
            headers,
            io.BytesIO(b""),
        )

    def test_429_backs_off_then_reads_pressure(self):
        pauses = []
        calls = {"n": 0}

        class Body:
            def read(self):
                return b'{"hourly":{"time":["2026-11-15T08:00"],"pressure_msl":[1011.5]}}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise self.http_error(429, retry_after=9)
            return Body()

        series = fetchers.fetch_open_meteo_pressure(
            48.221356, -122.533162, opener=opener, sleeper=pauses.append,
        )
        self.assertEqual(pauses, [9])
        self.assertEqual(series[0][1], 1011.5)

    def test_retry_after_is_capped_at_one_minute(self):
        pauses = []

        def opener(request, timeout):
            raise self.http_error(429, retry_after=600)

        with self.assertRaises(fetchers.FetchError):
            fetchers.get_with_backoff(
                "https://api.open-meteo.com/v1/forecast",
                opener=opener,
                sleeper=pauses.append,
                attempts=2,
            )
        self.assertEqual(pauses, [60])

    def test_timeout_is_retried(self):
        pauses = []
        calls = {"n": 0}

        class Body:
            def read(self):
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("handshake timed out")
            return Body()

        payload = fetchers.get_with_backoff(
            "https://api.open-meteo.com/v1/forecast",
            opener=opener,
            sleeper=pauses.append,
            attempts=2,
        )
        self.assertEqual(payload, b"ok")
        self.assertEqual(pauses, [5])

    def test_other_client_errors_are_not_retried(self):
        calls = {"n": 0}

        def opener(request, timeout):
            calls["n"] += 1
            raise self.http_error(400)

        with self.assertRaises(fetchers.FetchError):
            fetchers.get_with_backoff(
                "https://api.open-meteo.com/v1/forecast",
                opener=opener,
                sleeper=lambda seconds: None,
                attempts=4,
            )
        self.assertEqual(calls["n"], 1)


class DayRowTests(unittest.TestCase):
    def page(self, tides):
        return render.render_page({
            "config": model.load_config(),
            "generated_at": datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
            "station_name": "Coupeville",
            "tides": tides,
            "current": {},
            "warnings": [],
            "observations": [],
            "history": [],
            "backtest": None,
        })

    def tide(self, when, actual, predicted=10.0):
        return {"time": when, "predicted_actual_ft": actual, "predicted_tide_ft": predicted, "passed": False}

    def test_each_day_shows_its_highest_actual_tide(self):
        pacific = ZoneInfo("America/Los_Angeles")
        tides = [
            self.tide(datetime(2026, 11, 16, 4, 20, tzinfo=pacific), 10.2, predicted=10.4),
            self.tide(datetime(2026, 11, 16, 15, 5, tzinfo=pacific), 11.69, predicted=11.5),
            self.tide(datetime(2026, 11, 17, 5, 11, tzinfo=pacific), 14.04, predicted=12.0),
            self.tide(datetime(2026, 11, 17, 16, 0, tzinfo=pacific), 11.1, predicted=13.5),
        ]
        peaks = render.day_peaks(tides)
        self.assertEqual([item["date"].isoformat() for item in peaks], ["2026-11-16", "2026-11-17"])
        self.assertEqual(peaks[0]["tide"]["predicted_actual_ft"], 11.69)
        self.assertEqual(peaks[1]["tide"]["predicted_actual_ft"], 14.04)

        page = self.page(tides)
        self.assertIn('class="day-row"', page)
        self.assertIn("overflow-x: auto", page)
        self.assertIn("flex-wrap: nowrap", page)
        self.assertIn(">Monday<", page)
        self.assertIn(">Nov 16<", page)
        self.assertIn(">11.69 ft<", page)
        self.assertIn(">3:05 PM<", page)
        self.assertIn(">Tuesday<", page)
        self.assertIn(">Nov 17<", page)
        self.assertIn(">14.04 ft<", page)
        self.assertIn('class="day-tile level-green"', page)
        self.assertIn('class="day-tile level-red flood"', page)
        self.assertLess(page.index('class="day-row"'), page.index('class="card tide"'))

    def test_a_utc_evening_stays_on_the_pacific_day(self):
        # 07:00 UTC on Nov 17 is 11:00 PM PST on Nov 16.
        late = datetime(2026, 11, 17, 7, 0, tzinfo=timezone.utc)
        morning = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)
        peaks = render.day_peaks([
            self.tide(morning, 9.0),
            self.tide(late, 12.25),
        ])
        self.assertEqual(len(peaks), 1)
        self.assertEqual(peaks[0]["date"].isoformat(), "2026-11-16")
        self.assertEqual(peaks[0]["tide"]["predicted_actual_ft"], 12.25)
        self.assertEqual(render.fmt_clock(late), "11:00 PM")

    def test_fourteen_feet_is_highlighted_and_just_under_is_not(self):
        pacific = ZoneInfo("America/Los_Angeles")
        page = self.page([
            self.tide(datetime(2026, 11, 16, 15, 0, tzinfo=pacific), 13.94),
            self.tide(datetime(2026, 11, 17, 15, 0, tzinfo=pacific), 14.0),
        ])
        self.assertIn(">13.94 ft<", page)
        self.assertIn('<p class="day-height">14.00 ft</p>', page)
        self.assertIn('class="day-tile level-yellow"', page)
        self.assertIn('class="day-tile level-red flood"', page)

    def test_tile_border_colors_follow_the_height_boundaries(self):
        pacific = ZoneInfo("America/Los_Angeles")
        heights = [13.49, 13.50, 13.99, 14.00]
        page = self.page([
            self.tide(datetime(2026, 11, 16 + offset, 15, 0, tzinfo=pacific), height)
            for offset, height in enumerate(heights)
        ])
        self.assertEqual(render.tide_band(13.49, 14.0), "green")
        self.assertEqual(render.tide_band(13.50, 14.0), "yellow")
        self.assertEqual(render.tide_band(13.99, 14.0), "yellow")
        self.assertEqual(render.tide_band(14.00, 14.0), "red")
        self.assertIn('class="day-tile level-green"', page)
        self.assertEqual(page.count('class="day-tile level-yellow"'), 2)
        self.assertIn('class="day-tile level-red flood"', page)
        self.assertIn("border: 3px solid var(--line)", page)
        self.assertIn("border-color: #1f7a3a", page)
        self.assertIn("border-color: #c48a00", page)
        self.assertIn("border-color: #b42318", page)


if __name__ == "__main__":
    unittest.main()
