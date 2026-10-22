"""The open page must be able to notice a newly published forecast."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

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

    def test_version_file_uses_the_same_timestamp_as_the_page(self):
        payload = render.version_payload(self.when, "2026-10-22")
        self.assertEqual(payload["generated_at"], self.when.isoformat())
        self.assertIn(payload["generated_at"], self.page)
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
