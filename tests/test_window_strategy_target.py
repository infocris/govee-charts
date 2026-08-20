"""Greedy window strategy toward a target indoor temperature."""

from __future__ import annotations

import unittest

from govee_charts.weather import build_window_scenarios, simulate_window_strategy


def _hourly_outdoor(temps: list[float], *, ts0: float = 1_700_000_000.0) -> list[dict]:
    return [
        {"ts": ts0 + (i + 1) * 3600.0, "temperature_c": t}
        for i, t in enumerate(temps)
    ]


class WindowStrategyTargetTests(unittest.TestCase):
    def test_target_opens_only_when_outdoor_helps(self):
        # Indoor starts at 27 °C, target 24 °C. Cool outdoor then warm.
        # Hour 1: open to cool toward target. Hour 2: close to avoid overshoot
        # below 24 while outdoor is still 20 °C. Hours 3–4: stay closed when warm.
        ts0 = 1_700_000_000.0
        outdoor = _hourly_outdoor([20.0, 20.0, 30.0, 30.0], ts0=ts0)
        temps, states = simulate_window_strategy(
            outdoor,
            t0=27.0,
            ts0=ts0,
            closed_delta=0.0,
            closed_tau_hours=12.0,
            open_delta=0.0,
            open_tau_hours=1.0,
            goal="target",
            target_temp_c=24.0,
        )
        self.assertEqual(len(temps), 4)
        self.assertEqual(states[0], "open")
        self.assertEqual(states[1], "closed")
        self.assertEqual(states[2], "closed")
        self.assertEqual(states[3], "closed")
        self.assertLess(temps[0], 27.0)
        self.assertLess(abs(temps[1] - 24.0), abs(temps[0] - 24.0) + 0.5)

    def test_build_scenarios_includes_strategy_target(self):
        ts0 = 1_700_000_000.0
        outdoor = _hourly_outdoor([18.0, 22.0], ts0=ts0)
        scenarios = build_window_scenarios(
            outdoor,
            t0=26.0,
            ts0=ts0,
            closed_delta=1.0,
            closed_tau_hours=8.0,
            target_temp_c=24.0,
        )
        self.assertIn("strategy_coolest", scenarios)
        self.assertIn("strategy_warmest", scenarios)
        self.assertIn("strategy_target", scenarios)
        tgt = scenarios["strategy_target"]
        self.assertEqual(tgt.get("target_temp_c"), 24.0)
        self.assertEqual(tgt.get("source"), "greedy_target")
        self.assertTrue(tgt.get("opening_plan"))

    def test_build_scenarios_omits_target_without_setpoint(self):
        ts0 = 1_700_000_000.0
        outdoor = _hourly_outdoor([18.0], ts0=ts0)
        scenarios = build_window_scenarios(
            outdoor,
            t0=26.0,
            ts0=ts0,
            closed_delta=1.0,
            closed_tau_hours=8.0,
        )
        self.assertNotIn("strategy_target", scenarios)


if __name__ == "__main__":
    unittest.main()
