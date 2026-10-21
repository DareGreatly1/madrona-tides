"""Coefficient checks against the owner's written examples."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model


class FormulaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = model.load_config()

    def test_december_pressure_matches_the_writeup(self):
        # "a pressure of 977.31 ... will raise the ACTUAL tide level by 14.13 inches"
        inches = model.pressure_adjustment_inches(977.31, self.cfg)
        self.assertAlmostEqual(inches, 14.13, delta=0.01)

    def test_high_pressure_lowers_the_estimate(self):
        inches = model.pressure_adjustment_inches(1023.21, self.cfg)
        self.assertAlmostEqual(inches, -3.937, places=3)

    def test_due_west_wind_counts_in_full(self):
        westerly, inches = model.wind_adjustment_inches(48, 270, self.cfg)
        self.assertAlmostEqual(westerly, 48, places=5)
        self.assertAlmostEqual(inches, 19.2, places=5)

    def test_sse_wind_adds_nothing(self):
        westerly, inches = model.wind_adjustment_inches(30, 157.5, self.cfg)
        self.assertAlmostEqual(westerly, 0.0, places=5)
        self.assertEqual(inches, 0.0)

    def test_southwest_wind_is_partially_westerly(self):
        westerly, inches = model.wind_adjustment_inches(20, 225, self.cfg)
        self.assertAlmostEqual(westerly, 14.1421, places=3)
        self.assertAlmostEqual(inches, 5.6569, places=3)

    def test_november_river_term(self):
        above, inches = model.river_adjustment_inches(33.93, self.cfg)
        self.assertAlmostEqual(above, 13.93, places=2)
        self.assertAlmostEqual(inches, 16.716, places=3)

    def test_river_at_or_below_baseline_adds_nothing(self):
        above, inches = model.river_adjustment_inches(20, self.cfg)
        self.assertEqual((above, inches), (0.0, 0.0))
        above, inches = model.river_adjustment_inches(11.2, self.cfg)
        self.assertEqual(inches, 0.0)

    def test_piling_scale(self):
        self.assertAlmostEqual(model.steps_showing(10, self.cfg), 10)
        self.assertAlmostEqual(model.steps_showing(11, self.cfg), 9)
        self.assertAlmostEqual(model.steps_showing(15, self.cfg), 5)
        self.assertAlmostEqual(model.height_from_steps(5, self.cfg), 15)
        self.assertAlmostEqual(model.height_from_steps(9, self.cfg), 11)

    def test_november_owner_inputs_land_on_the_observed_height(self):
        result = model.apply_formula(11.50, 997.63, 48, 270, 33.93, self.cfg)
        self.assertAlmostEqual(result["predicted_actual_ft"], 15.00, delta=0.02)
        self.assertTrue(result["likely_flood"])

    def test_december_owner_inputs_are_short_of_15_feet(self):
        result = model.apply_formula(12.90, 977.31, 30, 157.5, 24.97, self.cfg)
        # Pressure and river explain about 1.68 ft; the photographed water was 15.0.
        self.assertAlmostEqual(result["predicted_actual_ft"], 14.58, delta=0.03)
        self.assertAlmostEqual(result["wind_adjust_in"], 0.0, places=5)
        self.assertTrue(result["likely_flood"])


if __name__ == "__main__":
    unittest.main()
