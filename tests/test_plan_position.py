from __future__ import annotations

import unittest

from govee_charts.plan_position import (
    decode_plan_position,
    encode_plan_position,
    normalize_plan_patch,
)


class PlanPositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rect = {"x": 100.0, "y": 50.0, "w": 200.0, "h": 100.0}

    def test_round_trip_top_wall(self) -> None:
        enc = encode_plan_position(self.rect, x=150.0, y=60.0)
        self.assertEqual(enc["plan_wall"], "n")
        pt = decode_plan_position(self.rect, **enc)
        self.assertAlmostEqual(pt["x"], 150.0)
        self.assertAlmostEqual(pt["y"], 60.0)

    def test_round_trip_right_wall(self) -> None:
        enc = encode_plan_position(self.rect, x=290.0, y=80.0)
        self.assertEqual(enc["plan_wall"], "e")
        pt = decode_plan_position(self.rect, **enc)
        self.assertAlmostEqual(pt["x"], 290.0, places=3)
        self.assertAlmostEqual(pt["y"], 80.0, places=3)

    def test_normalize_clear(self) -> None:
        out = normalize_plan_patch(plan_wall=None)
        self.assertIsNone(out["plan_wall"])
        self.assertIsNone(out["plan_u"])

    def test_normalize_requires_uv_with_wall(self) -> None:
        with self.assertRaises(ValueError):
            normalize_plan_patch(plan_wall="n", plan_u=0.5)


if __name__ == "__main__":
    unittest.main()
