"""The overnight schedule uses the Pacific date and skips a second publish."""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site
import forecast_schedule

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
PACIFIC = ZoneInfo("America/Los_Angeles")


class PacificDateTests(unittest.TestCase):
    def test_primary_cron_is_just_after_pacific_midnight(self):
        winter = build_site.pacific_now(datetime(2026, 1, 15, 8, 15, tzinfo=UTC))
        self.assertEqual(winter.date().isoformat(), "2026-01-15")
        self.assertEqual((winter.hour, winter.minute), (0, 15))
        self.assertEqual(winter.tzname(), "PST")

        summer = build_site.pacific_now(datetime(2026, 7, 15, 8, 15, tzinfo=UTC))
        self.assertEqual(summer.date().isoformat(), "2026-07-15")
        self.assertEqual((summer.hour, summer.minute), (1, 15))
        self.assertEqual(summer.tzname(), "PDT")

    def test_utc_evening_is_still_the_previous_pacific_day(self):
        # 07:30 UTC in January is 11:30 PM PST the day before.
        clock = datetime(2026, 1, 15, 7, 30, tzinfo=UTC)
        local = build_site.pacific_now(clock)
        self.assertEqual(local.date().isoformat(), "2026-01-14")
        start, end = build_site.forecast_bounds(clock, 5)
        self.assertEqual(start.isoformat(), "2026-01-14T00:00:00-08:00")
        # Five days ahead of Jan 14 is the end of Jan 19.
        self.assertEqual(end.isoformat(), "2026-01-19T23:59:59-08:00")

    def test_midnight_run_includes_today_and_excludes_yesterday(self):
        clock = datetime(2026, 1, 15, 8, 15, tzinfo=UTC)
        start, end = build_site.forecast_bounds(clock, 5)
        self.assertEqual(start.date().isoformat(), "2026-01-15")
        today = datetime(2026, 1, 15, 0, 5, tzinfo=PACIFIC)
        yesterday = datetime(2026, 1, 14, 23, 50, tzinfo=PACIFIC)
        last_day = datetime(2026, 1, 20, 12, 0, tzinfo=PACIFIC)
        after = datetime(2026, 1, 21, 0, 5, tzinfo=PACIFIC)
        self.assertLessEqual(start, today)
        self.assertLessEqual(today, end)
        self.assertLessEqual(last_day, end)
        self.assertLess(yesterday, start)
        self.assertLess(end, after)


class SkipTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_version(self, run_date: str) -> None:
        site = self.root / "site"
        site.mkdir(parents=True, exist_ok=True)
        (site / "version.json").write_text(
            json.dumps({"generated_at": "2026-01-15T00:20:00-08:00", "run_date": run_date}),
            encoding="utf-8",
        )

    def write_history(self, run_date: str) -> None:
        data = self.root / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "history.csv").write_text(
            "run_date,high_tide_time\n"
            f"{run_date},2026-01-15T15:00:00-08:00\n",
            encoding="utf-8",
        )

    def test_schedule_skips_when_version_json_is_today(self):
        self.write_version("2026-01-15")
        self.assertTrue(forecast_schedule.already_published(self.root, "2026-01-15"))
        self.assertFalse(forecast_schedule.should_publish("schedule", self.root, "2026-01-15"))

    def test_schedule_skips_when_only_history_has_today(self):
        self.write_history("2026-01-15")
        self.assertTrue(forecast_schedule.already_published(self.root, "2026-01-15"))
        self.assertFalse(forecast_schedule.should_publish("schedule", self.root, "2026-01-15"))

    def test_yesterdays_run_does_not_count_as_today(self):
        self.write_version("2026-01-14")
        self.write_history("2026-01-14")
        self.assertFalse(forecast_schedule.already_published(self.root, "2026-01-15"))
        self.assertTrue(forecast_schedule.should_publish("schedule", self.root, "2026-01-15"))

    def test_manual_run_publishes_even_when_today_exists(self):
        self.write_version("2026-01-15")
        self.write_history("2026-01-15")
        self.assertTrue(forecast_schedule.should_publish("workflow_dispatch", self.root, "2026-01-15"))

    def test_github_output_records_the_decision(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w+", delete=False)
        handle.close()
        self.addCleanup(lambda: os.remove(handle.name))
        previous = os.environ.get("GITHUB_OUTPUT")
        os.environ["GITHUB_OUTPUT"] = handle.name
        try:
            forecast_schedule.write_github_output(False)
            forecast_schedule.write_github_output(True)
        finally:
            if previous is None:
                os.environ.pop("GITHUB_OUTPUT", None)
            else:
                os.environ["GITHUB_OUTPUT"] = previous
        self.assertEqual(Path(handle.name).read_text(encoding="utf-8"), "publish=false\npublish=true\n")


class WorkflowFileTests(unittest.TestCase):
    def test_crons_are_the_midnight_run_and_two_backups(self):
        text = (ROOT / ".github" / "workflows" / "daily-forecast.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "15 8 * * *"', text)
        self.assertIn('cron: "15 10 * * *"', text)
        self.assertIn('cron: "15 12 * * *"', text)
        self.assertNotIn("30 13", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("forecast_schedule.py", text)
        self.assertIn("needs.build.outputs.publish == 'true'", text)


if __name__ == "__main__":
    unittest.main()
