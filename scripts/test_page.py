"""The open page must be able to notice a newly published forecast."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


if __name__ == "__main__":
    unittest.main()
