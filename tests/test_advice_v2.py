"""Advice model v2: façade air, exhaust plume, HVAC isolate. v1 unchanged."""

from __future__ import annotations

import unittest

from govee_charts.apartment import (
    advise_climate_v2,
    room_window_air_c,
    suggest_cooling_airflow,
    suggest_cooling_airflow_v2,
)


def _room(
    rid: str,
    temp_c: float,
    *,
    exterior: tuple[str, ...] = ("s",),
    window: str = "closed",
    sensors: list | None = None,
    facade: float | None = None,
    label: str | None = None,
) -> dict:
    row = {
        "id": rid,
        "label": label or rid.title(),
        "temp_c": temp_c,
        "exterior": list(exterior),
        "window_state": window,
        "sensors": sensors or [],
    }
    if facade is not None:
        row["facade_temp_c"] = facade
    return row


def _ext_sensor(temp_c: float) -> dict:
    return {"zone": "exterior", "temperature_c": temp_c, "name": "facade"}


class AdviceV2Tests(unittest.TestCase):
    def test_hot_facade_hold_while_v1_still_cools_on_station(self):
        rooms = [
            _room(
                "living",
                25.0,
                exterior=("s",),
                sensors=[_ext_sensor(27.2)],
            ),
            _room(
                "bedroom",
                24.8,
                exterior=("n",),
                sensors=[_ext_sensor(27.0)],
            ),
        ]
        edges = [
            {
                "a": "living",
                "b": "bedroom",
                "kind": "door",
                "opening": "open",
            }
        ]
        station = 20.0
        v1 = suggest_cooling_airflow(rooms, edges, outdoor_temp_c=station)
        self.assertNotEqual(v1.get("mode"), "hold")
        self.assertIsNotNone(v1.get("inlet"))

        v2 = suggest_cooling_airflow_v2(rooms, edges, outdoor_temp_c=station)
        self.assertEqual(v2.get("mode"), "hold")
        self.assertIsNone(v2.get("inlet"))
        advice = v2.get("advice") or {}
        self.assertEqual(advice.get("mode"), "hold")
        kinds = {r["id"]: r["kind"] for r in advice.get("rooms") or []}
        self.assertEqual(kinds.get("living"), "close")
        self.assertEqual(kinds.get("bedroom"), "close")

    def test_hvac_on_no_cooling_inlet(self):
        rooms = [
            _room("living", 26.0, exterior=("s",), sensors=[_ext_sensor(18.0)]),
            _room("bedroom", 24.0, exterior=("n",), sensors=[_ext_sensor(18.0)]),
        ]
        edges = [
            {
                "a": "living",
                "b": "bedroom",
                "kind": "door",
                "opening": "open",
            }
        ]
        hvac = {"active": True, "room": "bedroom"}
        advice = advise_climate_v2(
            rooms, edges, outdoor_temp_c=18.0, hvac=hvac
        )
        self.assertEqual(advice.get("mode"), "hvac_isolate")
        self.assertTrue(advice.get("hvac_isolate"))
        self.assertTrue(advice.get("hvac_close_door"))
        for row in advice.get("rooms") or []:
            self.assertEqual(row.get("kind"), "close")

        v2 = suggest_cooling_airflow_v2(
            rooms, edges, outdoor_temp_c=18.0, hvac=hvac
        )
        self.assertEqual(v2.get("mode"), "hold")
        self.assertIsNone(v2.get("inlet"))
        self.assertTrue(
            any("AC is on" in a for a in (v2.get("actions") or []))
        )

        v1 = suggest_cooling_airflow(rooms, edges, outdoor_temp_c=18.0)
        self.assertNotEqual(v1.get("mode"), "hold")

    def test_exhaust_plume_ignored_falls_back_to_station(self):
        indoor = 25.0
        station = 20.0
        room = _room(
            "kitchen",
            indoor,
            sensors=[_ext_sensor(25.2)],
        )
        twindow, source = room_window_air_c(room, station)
        self.assertEqual(source, "plume_fallback")
        self.assertAlmostEqual(twindow, station, places=2)

        advice = advise_climate_v2(
            [room], [], outdoor_temp_c=station, outdoor_humidity=40.0
        )
        rows = advice.get("rooms") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("window_source"), "plume_fallback")
        self.assertEqual(rows[0].get("kind"), "open")
        self.assertEqual(advice.get("mode"), "cooling")

    def test_v1_hold_when_station_not_cooler(self):
        rooms = [_room("living", 24.0, sensors=[_ext_sensor(26.0)])]
        v1 = suggest_cooling_airflow(rooms, [], outdoor_temp_c=24.0)
        self.assertEqual(v1.get("mode"), "hold")
        v2 = suggest_cooling_airflow_v2(rooms, [], outdoor_temp_c=24.0)
        self.assertEqual(v2.get("mode"), "hold")


if __name__ == "__main__":
    unittest.main()
