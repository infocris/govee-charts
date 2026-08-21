"""Floor-plan geometry: persist editable plans and compile to ApartmentLayout."""

from __future__ import annotations

import copy
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from govee_charts.apartment import (
    ORIENTATIONS,
    ApartmentLayout,
    EdgeSpec,
    RoomSpec,
    compass_from_deg,
)
from govee_charts.categories import ROOM_LABELS, ROOMS

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLANS_PATH = ROOT / "data" / "apartment_plans.json"

PLAN_MODES = frozenset({"free", "partition"})
OPENING_KINDS = frozenset({"door", "window"})
# Shared edge longer than this fraction of the shorter shared span → wall_partial.
WALL_PARTIAL_FRAC = 0.35
# Coincidence / snap tolerance in canvas units.
EDGE_EPS = 0.75
_OUTDOOR_IDS = frozenset({"", "outdoor", "ext", "exterior", "outside"})


def _is_outdoor_room_id(rid: str) -> bool:
    return str(rid or "").strip().lower() in _OUTDOOR_IDS


def _rooms_with_exterior_windows(openings: list[dict[str, Any]]) -> set[str]:
    """Room ids that have a window opening onto outdoor."""
    out: set[str] = set()
    for op in openings or []:
        if str(op.get("kind") or "").strip().lower() != "window":
            continue
        a = str(op.get("room_a") or "").strip().lower()
        b = str(op.get("room_b") or "").strip().lower()
        if _is_outdoor_room_id(a) and b and not _is_outdoor_room_id(b):
            out.add(b)
        elif _is_outdoor_room_id(b) and a and not _is_outdoor_room_id(a):
            out.add(a)
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_plan_id() -> str:
    return f"plan-{uuid.uuid4().hex[:12]}"


def empty_store() -> dict[str, Any]:
    return {"active_plan_id": None, "plans": []}


def empty_plan(
    *,
    name: str,
    mode: str,
    plan_id: str | None = None,
) -> dict[str, Any]:
    mode_n = str(mode or "").strip().lower()
    if mode_n not in PLAN_MODES:
        raise ValueError(f"mode must be one of {sorted(PLAN_MODES)}")
    return {
        "id": plan_id or _new_plan_id(),
        "name": str(name or "Untitled").strip() or "Untitled",
        "mode": mode_n,
        "north_deg": 0.0,
        "meters_per_unit": 0.05,
        "envelope": {"type": "rect", "x": 40, "y": 40, "w": 400, "h": 280},
        "shapes": [],
        "walls": [],
        "faces": [],
        "openings": [],
        "updated_at": _now_iso(),
    }


def load_plans(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_PLANS_PATH
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                plans = data.get("plans")
                if not isinstance(plans, list):
                    plans = []
                active = data.get("active_plan_id")
                if active is not None:
                    active = str(active)
                return {"active_plan_id": active, "plans": [_normalize_plan(p) for p in plans if isinstance(p, dict)]}
    except Exception as exc:
        logger.warning("Apartment plans unreadable: %s", exc)
    return empty_store()


def save_plans(store: dict[str, Any], path: Path | None = None) -> None:
    path = path or DEFAULT_PLANS_PATH
    payload = {
        "active_plan_id": store.get("active_plan_id"),
        "plans": list(store.get("plans") or []),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception as exc:
        logger.warning("Apartment plans write failed: %s", exc)
        raise


def _normalize_plan(raw: dict[str, Any]) -> dict[str, Any]:
    mode = str(raw.get("mode") or "free").strip().lower()
    if mode not in PLAN_MODES:
        mode = "free"
    plan = empty_plan(name=str(raw.get("name") or "Untitled"), mode=mode, plan_id=str(raw.get("id") or _new_plan_id()))
    try:
        plan["north_deg"] = float(raw.get("north_deg") or 0.0) % 360.0
    except (TypeError, ValueError):
        plan["north_deg"] = 0.0
    try:
        mpu = float(raw.get("meters_per_unit") or 0.05)
    except (TypeError, ValueError):
        mpu = 0.05
    plan["meters_per_unit"] = max(1e-4, mpu)
    env = raw.get("envelope")
    if isinstance(env, dict):
        plan["envelope"] = _normalize_rect(env, fallback=plan["envelope"])
    plan["shapes"] = [
        s for s in (_normalize_shape(x) for x in (raw.get("shapes") or [])) if s
    ]
    plan["walls"] = [
        w for w in (_normalize_wall(x) for x in (raw.get("walls") or [])) if w
    ]
    plan["faces"] = [
        f for f in (_normalize_face(x) for x in (raw.get("faces") or [])) if f
    ]
    plan["openings"] = [
        o for o in (_normalize_opening(x) for x in (raw.get("openings") or [])) if o
    ]
    plan["updated_at"] = str(raw.get("updated_at") or plan["updated_at"])
    return plan


def _normalize_rect(raw: dict[str, Any], *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fb = fallback or {"type": "rect", "x": 0, "y": 0, "w": 100, "h": 80}
    try:
        x = float(raw.get("x", fb["x"]))
        y = float(raw.get("y", fb["y"]))
        w = float(raw.get("w", fb["w"]))
        h = float(raw.get("h", fb["h"]))
    except (TypeError, ValueError):
        return dict(fb)
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return {"type": "rect", "x": x, "y": y, "w": max(1.0, w), "h": max(1.0, h)}


def _normalize_shape(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    rid = str(raw.get("room_id") or "").strip().lower()
    sid = str(raw.get("id") or "").strip() or f"shape-{uuid.uuid4().hex[:8]}"
    rect = _normalize_rect(raw)
    out: dict[str, Any] = {
        "id": sid,
        "type": "rect",
        "room_id": rid,
        "label": str(raw.get("label") or "").strip(),
        "x": rect["x"],
        "y": rect["y"],
        "w": rect["w"],
        "h": rect["h"],
    }
    locked = bool(raw.get("area_locked"))
    area_m2 = None
    if raw.get("area_m2") is not None:
        try:
            area_m2 = max(0.0, float(raw["area_m2"]))
        except (TypeError, ValueError):
            area_m2 = None
    out["area_locked"] = locked and area_m2 is not None and area_m2 > 0
    if area_m2 is not None and area_m2 > 0:
        out["area_m2"] = round(area_m2, 3)
    return out


def _normalize_face(raw: Any) -> dict[str, Any] | None:
    shape = _normalize_shape(raw)
    if not shape:
        return None
    shape["id"] = str(raw.get("id") or shape["id"]).strip() or shape["id"]
    return shape


def _normalize_wall(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        x1 = float(raw.get("x1"))
        y1 = float(raw.get("y1"))
        x2 = float(raw.get("x2"))
        y2 = float(raw.get("y2"))
    except (TypeError, ValueError):
        return None
    # Force axis-aligned.
    if abs(x2 - x1) >= abs(y2 - y1):
        y2 = y1
    else:
        x2 = x1
    if abs(x2 - x1) < EDGE_EPS and abs(y2 - y1) < EDGE_EPS:
        return None
    return {
        "id": str(raw.get("id") or "").strip() or f"wall-{uuid.uuid4().hex[:8]}",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
    }


def _normalize_opening(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "door").strip().lower()
    if kind not in OPENING_KINDS:
        kind = "door"
    try:
        x1 = float(raw.get("x1"))
        y1 = float(raw.get("y1"))
        x2 = float(raw.get("x2"))
        y2 = float(raw.get("y2"))
    except (TypeError, ValueError):
        return None
    if abs(x2 - x1) < EDGE_EPS and abs(y2 - y1) < EDGE_EPS:
        return None
    room_a = str(raw.get("room_a") or "").strip().lower()
    room_b = str(raw.get("room_b") or "").strip().lower()
    return {
        "id": str(raw.get("id") or "").strip() or f"open-{uuid.uuid4().hex[:8]}",
        "kind": kind,
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "room_a": room_a,
        "room_b": room_b,
    }


def find_plan(store: dict[str, Any], plan_id: str) -> dict[str, Any] | None:
    pid = str(plan_id or "").strip()
    for plan in store.get("plans") or []:
        if isinstance(plan, dict) and str(plan.get("id")) == pid:
            return plan
    return None


def plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": plan.get("id"),
        "name": plan.get("name"),
        "mode": plan.get("mode"),
        "updated_at": plan.get("updated_at"),
        "room_count": _plan_room_count(plan),
    }


def _plan_room_count(plan: dict[str, Any]) -> int:
    mode = plan.get("mode")
    items = plan.get("shapes") if mode == "free" else plan.get("faces")
    n = 0
    for item in items or []:
        if isinstance(item, dict) and str(item.get("room_id") or "").strip():
            n += 1
    return n


def active_plan_meta(store: dict[str, Any] | None) -> dict[str, Any] | None:
    if not store:
        return None
    pid = store.get("active_plan_id")
    if not pid:
        return None
    plan = find_plan(store, str(pid))
    if not plan:
        return None
    return {
        "id": plan["id"],
        "name": plan.get("name"),
        "mode": plan.get("mode"),
    }


# --- Geometry helpers -------------------------------------------------------


def _rect_edges(rect: dict[str, Any]) -> list[tuple[str, float, float, float, float]]:
    """Return (side, x1, y1, x2, y2) for N/E/S/W edges of a rect (y grows down)."""
    x, y, w, h = float(rect["x"]), float(rect["y"]), float(rect["w"]), float(rect["h"])
    return [
        ("n", x, y, x + w, y),  # top → north if north_deg=0
        ("e", x + w, y, x + w, y + h),
        ("s", x, y + h, x + w, y + h),
        ("w", x, y, x, y + h),
    ]


def _seg_len(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def _overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    lo = max(min(a0, a1), min(b0, b1))
    hi = min(max(a0, a1), max(b0, b1))
    return max(0.0, hi - lo)


def _rect_area(rect: dict[str, Any]) -> float:
    return max(0.0, float(rect["w"]) * float(rect["h"]))


def _rect_intersection_area(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Axis-aligned intersection area in canvas units."""
    ax, ay, aw, ah = float(a["x"]), float(a["y"]), float(a["w"]), float(a["h"])
    bx, by, bw, bh = float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"])
    ow = _overlap_1d(ax, ax + aw, bx, bx + bw)
    oh = _overlap_1d(ay, ay + ah, by, by + bh)
    return ow * oh


def _point_in_rect(x: float, y: float, rect: dict[str, Any], *, pad: float = 0.0) -> bool:
    rx, ry = float(rect["x"]), float(rect["y"])
    rw, rh = float(rect["w"]), float(rect["h"])
    return (rx - pad) <= x <= (rx + rw + pad) and (ry - pad) <= y <= (ry + rh + pad)


def _is_nested_inside(inner: dict[str, Any], outer: dict[str, Any]) -> bool:
    """True when ``inner`` mostly sits inside ``outer`` (simple hole-in-room case).

    Uses center containment plus ≥85% of the smaller footprint overlapping the larger.
    """
    ia = _rect_area(inner)
    oa = _rect_area(outer)
    if ia <= 0 or oa <= 0 or ia >= oa - 1e-6:
        return False
    cx = float(inner["x"]) + float(inner["w"]) / 2.0
    cy = float(inner["y"]) + float(inner["h"]) / 2.0
    if not _point_in_rect(cx, cy, outer):
        return False
    overlap = _rect_intersection_area(inner, outer)
    return overlap >= 0.85 * ia


def _shared_edge_length(
    a: dict[str, Any], b: dict[str, Any]
) -> float:
    """Length of shared boundary between two axis-aligned rects (0 if none)."""
    ax, ay, aw, ah = float(a["x"]), float(a["y"]), float(a["w"]), float(a["h"])
    bx, by, bw, bh = float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"])
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    # Vertical shared edge (a right of b or vice versa)
    best = 0.0
    if abs(ax2 - bx) <= EDGE_EPS or abs(bx2 - ax) <= EDGE_EPS:
        best = max(best, _overlap_1d(ay, ay2, by, by2))
    # Horizontal shared edge
    if abs(ay2 - by) <= EDGE_EPS or abs(by2 - ay) <= EDGE_EPS:
        best = max(best, _overlap_1d(ax, ax2, bx, bx2))
    return best


def _edge_on_envelope(
    side: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    envelope: dict[str, Any],
) -> bool:
    ex, ey, ew, eh = (
        float(envelope["x"]),
        float(envelope["y"]),
        float(envelope["w"]),
        float(envelope["h"]),
    )
    if side == "n":
        return abs(y1 - ey) <= EDGE_EPS and abs(y2 - ey) <= EDGE_EPS
    if side == "s":
        return abs(y1 - (ey + eh)) <= EDGE_EPS and abs(y2 - (ey + eh)) <= EDGE_EPS
    if side == "w":
        return abs(x1 - ex) <= EDGE_EPS and abs(x2 - ex) <= EDGE_EPS
    if side == "e":
        return abs(x1 - (ex + ew)) <= EDGE_EPS and abs(x2 - (ex + ew)) <= EDGE_EPS
    return False


def _side_to_orientation(side: str, north_deg: float) -> str:
    """Map canvas side (n=top, e=right, …) to compass given north_deg (0 → +Y up / top = north)."""
    # Canvas: top = geometric north when north_deg=0. Meteorological façade normal.
    base = {"n": 0.0, "e": 90.0, "s": 180.0, "w": 270.0}[side]
    # Rotating the plan clockwise by north_deg means the top edge faces north_deg.
    facing = (base + float(north_deg)) % 360.0
    return compass_from_deg(facing) or "n"


def _opening_covers_pair(
    opening: dict[str, Any],
    room_a: str,
    room_b: str,
) -> bool:
    a = str(opening.get("room_a") or "").strip().lower()
    b = str(opening.get("room_b") or "").strip().lower()
    if not a or not b:
        return False
    pair = {a, b}
    return pair == {room_a, room_b}


def _opening_length_on_shared(
    openings: list[dict[str, Any]],
    room_a: str,
    room_b: str,
) -> tuple[float, str | None]:
    """Total opening length between two rooms and preferred kind (door > window)."""
    total = 0.0
    kind: str | None = None
    for op in openings:
        if not _opening_covers_pair(op, room_a, room_b):
            continue
        total += _seg_len(
            float(op["x1"]), float(op["y1"]), float(op["x2"]), float(op["y2"])
        )
        k = str(op.get("kind") or "door")
        if kind is None or (k == "door" and kind != "door"):
            kind = k
    return total, kind


def _label_for_room(room_id: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    return ROOM_LABELS.get(room_id, room_id.replace("_", " ").title())


def _rooms_from_rects(
    rects: list[dict[str, Any]],
    *,
    envelope: dict[str, Any],
    meters_per_unit: float,
    north_deg: float,
    openings: list[dict[str, Any]],
) -> tuple[dict[str, RoomSpec], list[EdgeSpec], float]:
    """Build RoomSpec / EdgeSpec from named rectangles.

    Nested / overlapping free shapes: the smaller footprint is treated as a
    separate room with walls around it; its canvas area is subtracted from the
    larger room (unless that room has a locked ``area_m2``).
    """
    mpu2 = float(meters_per_unit) ** 2
    named = [r for r in rects if str(r.get("room_id") or "").strip()]

    # Pair nesting: smaller mostly inside larger → subtract + wall.
    nested_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for i, a in enumerate(named):
        for b in named[i + 1 :]:
            if _is_nested_inside(a, b):
                nested_pairs.append((a, b))  # a inside b
            elif _is_nested_inside(b, a):
                nested_pairs.append((b, a))  # b inside a

    subtract_canvas: dict[str, float] = {}
    for inner, outer in nested_pairs:
        oid = str(outer.get("id") or "")
        if outer.get("area_locked"):
            continue
        subtract_canvas[oid] = subtract_canvas.get(oid, 0.0) + _rect_intersection_area(
            inner, outer
        )

    rooms: dict[str, RoomSpec] = {}
    windowed = _rooms_with_exterior_windows(openings)
    for rect in named:
        rid = str(rect.get("room_id") or "").strip().lower()
        if rid in rooms:
            raise ValueError(f"Duplicate room_id in plan: {rid}")
        geo_area = _rect_area(rect) * mpu2
        area = geo_area
        if rect.get("area_locked") and rect.get("area_m2") is not None:
            try:
                locked = float(rect["area_m2"])
                if locked > 0:
                    area = locked
            except (TypeError, ValueError):
                pass
        else:
            sid = str(rect.get("id") or "")
            area = max(0.0, geo_area - subtract_canvas.get(sid, 0.0) * mpu2)
        if area <= 0:
            continue
        exteriors: list[str] = []
        for side, x1, y1, x2, y2 in _rect_edges(rect):
            if not _edge_on_envelope(side, x1, y1, x2, y2, envelope):
                continue
            # Need meaningful length on the envelope
            if _seg_len(x1, y1, x2, y2) < EDGE_EPS * 2:
                continue
            o = _side_to_orientation(side, north_deg)
            if o not in exteriors:
                exteriors.append(o)
        # Stable compass order
        exteriors_t = tuple(o for o in ORIENTATIONS if o in exteriors)
        rooms[rid] = RoomSpec(
            id=rid,
            area_m2=round(area, 3),
            exterior=exteriors_t,
            label=_label_for_room(rid, str(rect.get("label") or "").strip()),
            has_window=rid in windowed,
        )

    edges: list[EdgeSpec] = []
    seen: set[tuple[str, str]] = set()

    def _add_edge(ra: str, rb: str, shared: float, *, force_wall: bool = False) -> None:
        if ra not in rooms or rb not in rooms:
            return
        key = (ra, rb) if ra < rb else (rb, ra)
        if key in seen:
            return
        seen.add(key)
        open_len, open_kind = _opening_length_on_shared(openings, ra, rb)
        if open_kind == "door" or (open_len > EDGE_EPS and open_kind != "window"):
            kind = "door"
        elif open_len > EDGE_EPS * 2 and open_len >= max(shared, 1.0) * WALL_PARTIAL_FRAC:
            kind = "wall_partial"
        elif open_len > EDGE_EPS:
            kind = "wall_partial"
        else:
            kind = "wall"
        if force_wall and kind == "wall":
            kind = "wall"
        edges.append(EdgeSpec(a=key[0], b=key[1], kind=kind))

    for i, a in enumerate(named):
        for b in named[i + 1 :]:
            ra = str(a["room_id"]).strip().lower()
            rb = str(b["room_id"]).strip().lower()
            shared = _shared_edge_length(a, b)
            if shared >= EDGE_EPS:
                _add_edge(ra, rb, shared)

    # Nested rooms: treat the hole perimeter as a wall (or door if opening drawn).
    for inner, outer in nested_pairs:
        ra = str(inner["room_id"]).strip().lower()
        rb = str(outer["room_id"]).strip().lower()
        peri = 2.0 * (float(inner["w"]) + float(inner["h"]))
        _add_edge(ra, rb, peri, force_wall=True)

    # Exterior openings with kind=door on envelope don't change edges;
    # façades already drive outdoor connections via exterior list.
    total_area = sum(r.area_m2 for r in rooms.values())
    return rooms, edges, total_area


def partition_faces_from_walls(
    envelope: dict[str, Any],
    walls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Split envelope into rectangles using axis-aligned interior walls (guillotine/BSP)."""
    ex = float(envelope["x"])
    ey = float(envelope["y"])
    ew = float(envelope["w"])
    eh = float(envelope["h"])
    cells: list[dict[str, Any]] = [
        {"x": ex, "y": ey, "w": ew, "h": eh}
    ]
    for wall in walls:
        x1, y1, x2, y2 = (
            float(wall["x1"]),
            float(wall["y1"]),
            float(wall["x2"]),
            float(wall["y2"]),
        )
        vertical = abs(x2 - x1) < EDGE_EPS
        horizontal = abs(y2 - y1) < EDGE_EPS
        if not vertical and not horizontal:
            continue
        next_cells: list[dict[str, Any]] = []
        for cell in cells:
            cx, cy, cw, ch = (
                float(cell["x"]),
                float(cell["y"]),
                float(cell["w"]),
                float(cell["h"]),
            )
            cx2, cy2 = cx + cw, cy + ch
            if vertical:
                x = (x1 + x2) / 2.0
                y_lo, y_hi = min(y1, y2), max(y1, y2)
                # Wall must span meaningfully inside the cell
                if x <= cx + EDGE_EPS or x >= cx2 - EDGE_EPS:
                    next_cells.append(cell)
                    continue
                if y_hi < cy + EDGE_EPS or y_lo > cy2 - EDGE_EPS:
                    next_cells.append(cell)
                    continue
                # Split if wall covers most of the cell height (or fully crosses)
                cover = _overlap_1d(y_lo, y_hi, cy, cy2)
                if cover < min(ch, abs(y_hi - y_lo)) - EDGE_EPS and cover < ch * 0.9:
                    next_cells.append(cell)
                    continue
                left_w = x - cx
                right_w = cx2 - x
                if left_w >= 1.0:
                    next_cells.append({"x": cx, "y": cy, "w": left_w, "h": ch})
                if right_w >= 1.0:
                    next_cells.append({"x": x, "y": cy, "w": right_w, "h": ch})
            else:
                y = (y1 + y2) / 2.0
                x_lo, x_hi = min(x1, x2), max(x1, x2)
                if y <= cy + EDGE_EPS or y >= cy2 - EDGE_EPS:
                    next_cells.append(cell)
                    continue
                if x_hi < cx + EDGE_EPS or x_lo > cx2 - EDGE_EPS:
                    next_cells.append(cell)
                    continue
                cover = _overlap_1d(x_lo, x_hi, cx, cx2)
                if cover < min(cw, abs(x_hi - x_lo)) - EDGE_EPS and cover < cw * 0.9:
                    next_cells.append(cell)
                    continue
                top_h = y - cy
                bot_h = cy2 - y
                if top_h >= 1.0:
                    next_cells.append({"x": cx, "y": cy, "w": cw, "h": top_h})
                if bot_h >= 1.0:
                    next_cells.append({"x": cx, "y": y, "w": cw, "h": bot_h})
        cells = next_cells

    faces: list[dict[str, Any]] = []
    for i, cell in enumerate(cells):
        faces.append(
            {
                "id": f"face-{i + 1}",
                "type": "rect",
                "room_id": "",
                "label": "",
                "x": cell["x"],
                "y": cell["y"],
                "w": cell["w"],
                "h": cell["h"],
            }
        )
    return faces


def merge_face_room_ids(
    faces: list[dict[str, Any]],
    previous: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve room_id assignments when faces are recomputed (center containment)."""
    out: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for face in faces:
        cx = float(face["x"]) + float(face["w"]) / 2.0
        cy = float(face["y"]) + float(face["h"]) / 2.0
        matched = None
        for prev in previous:
            px, py, pw, ph = (
                float(prev["x"]),
                float(prev["y"]),
                float(prev["w"]),
                float(prev["h"]),
            )
            if px - EDGE_EPS <= cx <= px + pw + EDGE_EPS and py - EDGE_EPS <= cy <= py + ph + EDGE_EPS:
                rid = str(prev.get("room_id") or "").strip().lower()
                if rid and rid not in used_ids:
                    matched = prev
                    break
        row = dict(face)
        if matched:
            rid = str(matched.get("room_id") or "").strip().lower()
            row["room_id"] = rid
            row["label"] = str(matched.get("label") or "").strip()
            if rid:
                used_ids.add(rid)
            # Prefer stable id when geometry matches closely
            if abs(float(matched["x"]) - float(face["x"])) < EDGE_EPS * 2:
                row["id"] = matched.get("id") or row["id"]
        out.append(row)
    return out


def compile_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """
    Compile a floor plan into apartment layout dict fragments.

    Returns {rooms, edges, area_m2, warnings, corridor_ok}.
    """
    plan = _normalize_plan(plan)
    mode = plan["mode"]
    envelope = plan["envelope"]
    mpu = float(plan["meters_per_unit"])
    north = float(plan["north_deg"])
    openings = list(plan.get("openings") or [])
    warnings: list[str] = []

    if mode == "free":
        rects = [s for s in plan.get("shapes") or [] if str(s.get("room_id") or "").strip()]
        if not rects:
            warnings.append("No named room shapes yet.")
    else:
        faces = list(plan.get("faces") or [])
        if not faces and plan.get("walls"):
            faces = partition_faces_from_walls(envelope, list(plan.get("walls") or []))
            faces = merge_face_room_ids(faces, list(plan.get("faces") or []))
        rects = [f for f in faces if str(f.get("room_id") or "").strip()]
        unnamed = [f for f in faces if not str(f.get("room_id") or "").strip()]
        if unnamed:
            warnings.append(f"{len(unnamed)} compartment(s) have no room id.")
        if not rects:
            warnings.append("No named compartments yet.")

    try:
        rooms, edges, total_area = _rooms_from_rects(
            rects,
            envelope=envelope,
            meters_per_unit=mpu,
            north_deg=north,
            openings=openings,
        )
    except ValueError as exc:
        return {
            "rooms": [],
            "edges": [],
            "area_m2": 0.0,
            "warnings": [str(exc)],
            "corridor_ok": False,
            "ok": False,
            "error": str(exc),
        }

    if not rooms:
        warnings.append("Compile produced no rooms.")

    corridor_ok = "corridor" in rooms
    if rooms and not corridor_ok:
        warnings.append(
            "No room with id 'corridor' — multi-node RC projection requires a corridor hub."
        )

    return {
        "rooms": [
            {
                "id": r.id,
                "area_m2": r.area_m2,
                "exterior": list(r.exterior),
                "label": r.label,
                "has_window": bool(r.has_window),
            }
            for r in rooms.values()
        ],
        "edges": [{"a": e.a, "b": e.b, "kind": e.kind} for e in edges],
        "area_m2": round(total_area, 3),
        "warnings": warnings,
        "corridor_ok": corridor_ok,
        "ok": bool(rooms),
        "error": None,
    }


def apply_compiled_to_layout(
    layout: ApartmentLayout,
    compiled: dict[str, Any],
) -> ApartmentLayout:
    """Replace rooms/edges on layout from compile output; keep storey meta."""
    if not compiled.get("ok"):
        raise ValueError(compiled.get("error") or "Compile failed")
    rooms: dict[str, RoomSpec] = {}
    for item in compiled.get("rooms") or []:
        rid = str(item.get("id") or "").strip().lower()
        if not rid:
            continue
        exterior = tuple(
            o
            for o in ORIENTATIONS
            if o in {str(x).strip().lower() for x in (item.get("exterior") or [])}
        )
        rooms[rid] = RoomSpec(
            id=rid,
            area_m2=float(item.get("area_m2") or 0),
            exterior=exterior,
            label=str(item.get("label") or rid),
            has_window=bool(item.get("has_window"))
            if "has_window" in item
            else bool(exterior),
        )
    edges: list[EdgeSpec] = []
    for item in compiled.get("edges") or []:
        a = str(item.get("a") or "").strip().lower()
        b = str(item.get("b") or "").strip().lower()
        kind = str(item.get("kind") or "door").strip().lower()
        if a not in rooms or b not in rooms or a == b:
            continue
        edges.append(EdgeSpec(a=a, b=b, kind=kind))
    layout.rooms = rooms
    layout.edges = edges
    area = compiled.get("area_m2")
    if area is not None:
        try:
            layout.area_m2 = float(area)
        except (TypeError, ValueError):
            pass
    layout._rebuild_matrices()
    return layout


def apply_plan_to_layout(layout: ApartmentLayout, plan: dict[str, Any]) -> dict[str, Any]:
    """Compile plan and apply to layout. Returns compile result."""
    compiled = compile_plan(plan)
    if compiled.get("ok"):
        apply_compiled_to_layout(layout, compiled)
    return compiled


def duplicate_plan(plan: dict[str, Any], *, name: str | None = None) -> dict[str, Any]:
    clone = copy.deepcopy(_normalize_plan(plan))
    clone["id"] = _new_plan_id()
    base = str(name or f"{plan.get('name', 'Plan')} (copy)").strip()
    clone["name"] = base or "Copy"
    clone["updated_at"] = _now_iso()
    return clone


def validate_plan_update(
    existing: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Merge client geometry into existing plan; mode is immutable."""
    merged = _normalize_plan({**existing, **patch, "id": existing["id"], "mode": existing["mode"]})
    if str(patch.get("mode") or existing["mode"]).strip().lower() != existing["mode"]:
        raise ValueError("Plan mode cannot be changed after creation")
    # Allow rename / scale / north / geometry
    if "name" in patch:
        merged["name"] = str(patch["name"] or "").strip() or existing.get("name") or "Untitled"
    if "north_deg" in patch:
        try:
            merged["north_deg"] = float(patch["north_deg"]) % 360.0
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid north_deg") from exc
    if "meters_per_unit" in patch:
        try:
            merged["meters_per_unit"] = max(1e-4, float(patch["meters_per_unit"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid meters_per_unit") from exc
    if "envelope" in patch and isinstance(patch["envelope"], dict):
        merged["envelope"] = _normalize_rect(patch["envelope"], fallback=existing.get("envelope"))
    if "shapes" in patch:
        merged["shapes"] = [
            s for s in (_normalize_shape(x) for x in (patch.get("shapes") or [])) if s
        ]
    if "walls" in patch:
        merged["walls"] = [
            w for w in (_normalize_wall(x) for x in (patch.get("walls") or [])) if w
        ]
    if "faces" in patch:
        merged["faces"] = [
            f for f in (_normalize_face(x) for x in (patch.get("faces") or [])) if f
        ]
    if "openings" in patch:
        merged["openings"] = [
            o for o in (_normalize_opening(x) for x in (patch.get("openings") or [])) if o
        ]
    # Partition: refresh faces from walls when walls provided without faces
    if merged["mode"] == "partition" and "walls" in patch and "faces" not in patch:
        faces = partition_faces_from_walls(merged["envelope"], merged["walls"])
        merged["faces"] = merge_face_room_ids(faces, list(existing.get("faces") or []))
    merged["updated_at"] = _now_iso()
    # Unique room_ids within plan
    ids: list[str] = []
    items = merged["shapes"] if merged["mode"] == "free" else merged["faces"]
    for item in items:
        rid = str(item.get("room_id") or "").strip().lower()
        if not rid:
            continue
        if rid in ids:
            raise ValueError(f"Duplicate room_id: {rid}")
        ids.append(rid)
    return merged


def known_room_options() -> list[dict[str, str]]:
    return [{"id": r, "label": ROOM_LABELS.get(r, r)} for r in ROOMS]
