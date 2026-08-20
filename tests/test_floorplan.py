"""Floor-plan compile: areas, edges, façades, immutable mode."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from govee_charts.apartment import ApartmentLayout
from govee_charts.floorplan import (
    apply_plan_to_layout,
    compile_plan,
    duplicate_plan,
    empty_plan,
    load_plans,
    partition_faces_from_walls,
    save_plans,
    validate_plan_update,
)


def _free_plan() -> dict:
    plan = empty_plan(name="T3 free", mode="free")
    plan["north_deg"] = 0.0
    plan["meters_per_unit"] = 0.1  # 10 units = 1 m
    plan["envelope"] = {"type": "rect", "x": 0, "y": 0, "w": 100, "h": 60}
    # Two rooms sharing a vertical wall at x=60
    plan["shapes"] = [
        {
            "id": "s1",
            "type": "rect",
            "room_id": "living",
            "label": "Living",
            "x": 0,
            "y": 0,
            "w": 60,
            "h": 60,
        },
        {
            "id": "s2",
            "type": "rect",
            "room_id": "bedroom",
            "label": "Bedroom",
            "x": 60,
            "y": 0,
            "w": 40,
            "h": 60,
        },
        {
            "id": "s3",
            "type": "rect",
            "room_id": "corridor",
            "label": "Corridor",
            "x": 20,
            "y": 20,
            "w": 20,
            "h": 20,
        },
    ]
    # corridor is nested — for adjacency we use edge contact; corridor touches living
    # Adjust corridor to sit on the shared edge better: place as strip at bottom of living
    plan["shapes"][2] = {
        "id": "s3",
        "type": "rect",
        "room_id": "corridor",
        "label": "Corridor",
        "x": 0,
        "y": 40,
        "w": 60,
        "h": 20,
    }
    # living above corridor
    plan["shapes"][0] = {
        "id": "s1",
        "type": "rect",
        "room_id": "living",
        "label": "Living",
        "x": 0,
        "y": 0,
        "w": 60,
        "h": 40,
    }
    plan["openings"] = [
        {
            "id": "o1",
            "kind": "door",
            "x1": 25,
            "y1": 40,
            "x2": 35,
            "y2": 40,
            "room_a": "living",
            "room_b": "corridor",
        },
        {
            "id": "o2",
            "kind": "door",
            "x1": 60,
            "y1": 20,
            "x2": 60,
            "y2": 30,
            "room_a": "living",
            "room_b": "bedroom",
        },
    ]
    return plan


class FloorplanCompileTests(unittest.TestCase):
    def test_free_areas_and_facades(self):
        compiled = compile_plan(_free_plan())
        self.assertTrue(compiled["ok"], compiled.get("warnings"))
        by_id = {r["id"]: r for r in compiled["rooms"]}
        self.assertIn("living", by_id)
        self.assertIn("bedroom", by_id)
        self.assertIn("corridor", by_id)
        # 60*40 * 0.01 = 24 m²
        self.assertAlmostEqual(by_id["living"]["area_m2"], 24.0, places=2)
        # 40*60 * 0.01 = 24 m²
        self.assertAlmostEqual(by_id["bedroom"]["area_m2"], 24.0, places=2)
        # living has N (top), W (left) façades when north_deg=0
        self.assertIn("n", by_id["living"]["exterior"])
        self.assertIn("w", by_id["living"]["exterior"])
        # bedroom has N, E, S
        self.assertIn("e", by_id["bedroom"]["exterior"])
        # corridor at bottom: S and W
        self.assertIn("s", by_id["corridor"]["exterior"])
        self.assertTrue(compiled["corridor_ok"])

    def test_free_door_edges(self):
        compiled = compile_plan(_free_plan())
        edges = {(e["a"], e["b"], e["kind"]) for e in compiled["edges"]}
        # lexicographic pairs
        self.assertIn(("corridor", "living", "door"), edges)
        self.assertIn(("bedroom", "living", "door"), edges)

    def test_wall_without_opening(self):
        plan = _free_plan()
        plan["openings"] = []
        # living and bedroom still share edge → wall
        compiled = compile_plan(plan)
        edges = {(e["a"], e["b"], e["kind"]) for e in compiled["edges"]}
        self.assertIn(("bedroom", "living", "wall"), edges)

    def test_mode_immutable(self):
        plan = empty_plan(name="P", mode="free")
        with self.assertRaises(ValueError):
            validate_plan_update(plan, {"mode": "partition", "name": "P"})

    def test_duplicate_keeps_mode(self):
        plan = empty_plan(name="P", mode="partition")
        clone = duplicate_plan(plan)
        self.assertEqual(clone["mode"], "partition")
        self.assertNotEqual(clone["id"], plan["id"])

    def test_duplicate_room_id_rejected(self):
        plan = _free_plan()
        plan["shapes"].append(
            {
                "id": "dup",
                "type": "rect",
                "room_id": "living",
                "x": 10,
                "y": 10,
                "w": 10,
                "h": 10,
            }
        )
        with self.assertRaises(ValueError):
            validate_plan_update(plan, {"shapes": plan["shapes"]})

    def test_partition_faces_and_compile(self):
        plan = empty_plan(name="Part", mode="partition")
        plan["meters_per_unit"] = 0.1
        plan["envelope"] = {"type": "rect", "x": 0, "y": 0, "w": 100, "h": 50}
        plan["walls"] = [
            {"id": "w1", "x1": 50, "y1": 0, "x2": 50, "y2": 50},
        ]
        faces = partition_faces_from_walls(plan["envelope"], plan["walls"])
        self.assertEqual(len(faces), 2)
        faces[0]["room_id"] = "living"
        faces[1]["room_id"] = "bedroom"
        # Need corridor for corridor_ok warning check — add horizontal wall
        plan["walls"].append({"id": "w2", "x1": 0, "y1": 30, "x2": 50, "y2": 30})
        faces = partition_faces_from_walls(plan["envelope"], plan["walls"])
        self.assertGreaterEqual(len(faces), 3)
        faces[0]["room_id"] = "living"
        faces[1]["room_id"] = "corridor"
        faces[2]["room_id"] = "bedroom"
        # Ensure unique ids across remaining faces
        for i, f in enumerate(faces[3:], start=3):
            f["room_id"] = f"other" if i == 3 else ""
            if i > 3:
                break
        # Only three named rooms if we leave extras unnamed — but "other" is ok
        named = [f for f in faces if f.get("room_id")]
        # Avoid duplicate other
        seen = set()
        for f in faces:
            rid = f.get("room_id") or ""
            if not rid:
                continue
            if rid in seen:
                f["room_id"] = ""
            seen.add(rid)
        plan["faces"] = faces
        plan["openings"] = [
            {
                "id": "d1",
                "kind": "door",
                "x1": 50,
                "y1": 10,
                "x2": 50,
                "y2": 20,
                "room_a": "living",
                "room_b": "bedroom",
            }
        ]
        compiled = compile_plan(plan)
        self.assertTrue(compiled["ok"], compiled)
        ids = {r["id"] for r in compiled["rooms"]}
        self.assertIn("living", ids)
        self.assertIn("bedroom", ids)

    def test_apply_to_layout(self):
        layout = ApartmentLayout.from_dict(
            {
                "enabled": True,
                "rooms": [{"id": "kitchen", "area_m2": 5, "exterior": [], "label": "K"}],
                "edges": [],
            }
        )
        compiled = apply_plan_to_layout(layout, _free_plan())
        self.assertTrue(compiled["ok"])
        self.assertIn("living", layout.rooms)
        self.assertNotIn("kitchen", layout.rooms)

    def test_persist_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apartment_plans.json"
            store = {"active_plan_id": None, "plans": [_free_plan()]}
            save_plans(store, path)
            loaded = load_plans(path)
            self.assertEqual(len(loaded["plans"]), 1)
            self.assertEqual(loaded["plans"][0]["mode"], "free")
            self.assertEqual(len(loaded["plans"][0]["shapes"]), 3)

    def test_north_rotation_changes_facade(self):
        plan = _free_plan()
        plan["shapes"] = [
            {
                "id": "s1",
                "room_id": "living",
                "x": 0,
                "y": 0,
                "w": 100,
                "h": 60,
                "type": "rect",
                "label": "Living",
            },
            {
                "id": "s2",
                "room_id": "corridor",
                "x": 40,
                "y": 20,
                "w": 20,
                "h": 20,
                "type": "rect",
                "label": "Corridor",
            },
        ]
        # Nested corridor won't touch envelope — living has all four sides
        plan["shapes"][1] = {
            "id": "s2",
            "room_id": "corridor",
            "x": 0,
            "y": 40,
            "w": 30,
            "h": 20,
            "type": "rect",
            "label": "Corridor",
        }
        plan["shapes"][0] = {
            "id": "s1",
            "room_id": "living",
            "x": 0,
            "y": 0,
            "w": 100,
            "h": 40,
            "type": "rect",
            "label": "Living",
        }
        plan["openings"] = []
        plan["north_deg"] = 0
        c0 = compile_plan(plan)
        living0 = next(r for r in c0["rooms"] if r["id"] == "living")
        plan["north_deg"] = 90
        c1 = compile_plan(plan)
        living1 = next(r for r in c1["rooms"] if r["id"] == "living")
        # Top edge: was N, after +90° clockwise becomes E
        self.assertIn("n", living0["exterior"])
        self.assertIn("e", living1["exterior"])


if __name__ == "__main__":
    unittest.main()
