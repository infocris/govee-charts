"""Apartment thermal network layout and multi-node RC simulation."""

from __future__ import annotations

import heapq
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OVERRIDES_PATH = ROOT / "data" / "apartment_overrides.json"

# Storey geometry (T3): ~2.5 m ceiling, interior door frames ~2.0 m.
# The ~0.5 m transom above the lintel is a weakly mixed ceiling pocket.
DEFAULT_CEILING_M = 2.5
DEFAULT_DOOR_HEIGHT_M = 2.0
# Typical window sill (not surveyed). Window heads align with door frames.
DEFAULT_WINDOW_SILL_M = 0.9
# K_door is calibrated for a 2.0 m leaf in a 2.5 m storey.
_DOOR_K_REF_OPENING_FRAC = DEFAULT_DOOR_HEIGHT_M / DEFAULT_CEILING_M

# Relative conductances (W/K scale factors); absolute scale set by K_SCALE.
K_BY_EDGE = {
    "door": 25.0,
    "wall_partial": 8.0,
    "wall": 5.0,
}
# Exterior façade conductance per m² of floor (proxy for glazed + opaque).
K_EXT_PER_M2 = 1.8
# Air + structure effective capacity ≈ factor * ρ * cp * V_air (J/K).
C_AIR = 1.2 * 1000.0  # J/(m³·K)
C_STRUCTURE_FACTOR = 20.0
K_SCALE = 1.0

ORIENTATIONS = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
ORIENTATION_LABELS = {
    "n": "North",
    "ne": "Northeast",
    "e": "East",
    "se": "Southeast",
    "s": "South",
    "sw": "Southwest",
    "w": "West",
    "nw": "Northwest",
}
# Meteorological: direction the wind comes FROM (°).
ORIENTATION_DEG = {
    "n": 0.0,
    "ne": 45.0,
    "e": 90.0,
    "se": 135.0,
    "s": 180.0,
    "sw": 225.0,
    "w": 270.0,
    "nw": 315.0,
}
# Below this effective wind (m/s), natural draft is weak.
WIND_MIN_MS = 1.5

# Infer air coupling between rooms from |ΔT_max| when no door contact exists.
# Close daily maxima ⇒ rooms likely share air (door open / large opening).
TEMP_COUPLE_OPEN_C = 0.8
TEMP_COUPLE_CLOSED_C = 2.0


def height_bands_cm(
    ceiling_m: float = DEFAULT_CEILING_M,
    door_height_m: float = DEFAULT_DOOR_HEIGHT_M,
) -> dict[str, int]:
    """Map high/mid/low categories onto the door / transom geometry.

    high — midpoint of the transom (above the lintel)
    mid  — midpoint of the door opening
    low  — near the floor (~15 % of the door leaf)
    """
    ceil_cm = max(50.0, float(ceiling_m) * 100.0)
    door_cm = min(ceil_cm - 5.0, max(50.0, float(door_height_m) * 100.0))
    return {
        "high": int(round((door_cm + ceil_cm) / 2.0)),
        "mid": int(round(door_cm / 2.0)),
        "low": int(round(max(20.0, door_cm * 0.15))),
    }


def infer_temp_coupling(
    temp_max_a: float | None,
    temp_max_b: float | None,
    *,
    open_c: float = TEMP_COUPLE_OPEN_C,
    closed_c: float = TEMP_COUPLE_CLOSED_C,
) -> dict[str, Any]:
    """
    Classify inter-room communication from how close their max temperatures are.

    Returns opening in {open, closed, unknown}, plus delta_c when computable.
    """
    if temp_max_a is None or temp_max_b is None:
        return {
            "opening": "unknown",
            "delta_c": None,
            "source": "temp_coupling",
        }
    delta = abs(float(temp_max_a) - float(temp_max_b))
    if delta <= float(open_c):
        opening = "open"
    elif delta >= float(closed_c):
        opening = "closed"
    else:
        opening = "unknown"
    return {
        "opening": opening,
        "delta_c": round(delta, 2),
        "source": "temp_coupling",
        "open_threshold_c": float(open_c),
        "closed_threshold_c": float(closed_c),
    }


def _room_live_temp(room: dict[str, Any]) -> float | None:
    for key in ("temp_c", "temp_max", "temp_min"):
        val = room.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return None


def _facade_sep_deg(a: list[str] | tuple[str, ...], b: list[str] | tuple[str, ...]) -> float:
    best = 0.0
    for ra in a or ():
        da = ORIENTATION_DEG.get(str(ra).strip().lower())
        if da is None:
            continue
        for rb in b or ():
            db = ORIENTATION_DEG.get(str(rb).strip().lower())
            if db is None:
                continue
            best = max(best, abs(_angle_diff_deg(da, db)))
    return best


def suggest_cooling_airflow(
    rooms: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    outdoor_temp_c: float | None = None,
    wind_speed_ms: float | None = None,
    wind_direction_deg: float | None = None,
) -> dict[str, Any]:
    """
    Suggest a through-flow path to cool the apartment (inlet → rooms → outlet).

    Prefers opposing façades, windward inlet / leeward outlet when wind is known,
    otherwise hottest façade as chimney outlet and coolest as inlet. Edges marked
    closed are still allowed on the path but listed as doors to open.
    """
    by_id = {str(r.get("id")): r for r in rooms if r.get("id")}
    indoor_temps = [
        t for t in (_room_live_temp(r) for r in by_id.values()) if t is not None
    ]
    indoor_avg = (
        round(sum(indoor_temps) / len(indoor_temps), 2) if indoor_temps else None
    )
    outdoor = None
    if outdoor_temp_c is not None:
        try:
            outdoor = float(outdoor_temp_c)
        except (TypeError, ValueError):
            outdoor = None

    if outdoor is not None and indoor_avg is not None and outdoor >= indoor_avg - 0.3:
        return {
            "mode": "hold",
            "outdoor_temp_c": round(outdoor, 2),
            "indoor_temp_c": indoor_avg,
            "delta_c": round(outdoor - indoor_avg, 2),
            "inlet": None,
            "outlet": None,
            "path": [],
            "flows": [],
            "actions": [
                "Outdoor air is not cooler than indoors — keep windows closed "
                "or use mechanical cooling; through-draft would warm the flat."
            ],
        }

    facade_rooms = [
        r
        for r in by_id.values()
        if list(r.get("exterior") or [])
    ]
    if len(facade_rooms) < 1:
        return {
            "mode": "unknown",
            "outdoor_temp_c": outdoor,
            "indoor_temp_c": indoor_avg,
            "delta_c": (
                round(outdoor - indoor_avg, 2)
                if outdoor is not None and indoor_avg is not None
                else None
            ),
            "inlet": None,
            "outlet": None,
            "path": [],
            "flows": [],
            "actions": ["No exterior façades configured — cannot suggest draft."],
        }

    # Graph of passable / openable links (not solid walls).
    adj: dict[str, list[tuple[str, dict[str, Any]]]] = {rid: [] for rid in by_id}
    for edge in edges:
        kind = str(edge.get("kind") or "door")
        if kind == "wall":
            continue
        a = str(edge.get("a") or "")
        b = str(edge.get("b") or "")
        if a not in adj or b not in adj:
            continue
        adj[a].append((b, edge))
        adj[b].append((a, edge))

    def path_cost(edge: dict[str, Any]) -> float:
        opening = str(edge.get("opening") or "unknown")
        kind = str(edge.get("kind") or "door")
        if opening == "open":
            base = 1.0
        elif kind == "wall_partial":
            base = 1.2
        elif opening == "unknown":
            base = 1.6
        elif opening == "closed":
            base = 3.5
        else:
            base = 2.0
        return base

    def shortest_path(src: str, dst: str) -> tuple[list[str], list[dict[str, Any]]]:
        if src == dst:
            return [src], []
        pq: list[tuple[float, str]] = [(0.0, src)]
        dist = {src: 0.0}
        prev: dict[str, tuple[str, dict[str, Any]]] = {}
        while pq:
            cost, node = heapq.heappop(pq)
            if node == dst:
                break
            if cost > dist.get(node, 1e18):
                continue
            for nxt, edge in adj.get(node, []):
                nc = cost + path_cost(edge)
                if nc < dist.get(nxt, 1e18):
                    dist[nxt] = nc
                    prev[nxt] = (node, edge)
                    heapq.heappush(pq, (nc, nxt))
        if dst not in prev and src != dst:
            return [], []
        nodes = [dst]
        used: list[dict[str, Any]] = []
        cur = dst
        while cur != src:
            parent, edge = prev[cur]
            used.append(edge)
            nodes.append(parent)
            cur = parent
        nodes.reverse()
        used.reverse()
        return nodes, used

    def inlet_score(room: dict[str, Any]) -> float:
        orients = tuple(room.get("exterior") or ())
        wind_on = wind_on_facade_ms(orients, wind_speed_ms, wind_direction_deg)
        t = _room_live_temp(room)
        score = 0.0
        # Prefer already-open windows, then windward, then cooler room.
        if str(room.get("window_state") or "") == "open":
            score += 4.0
        elif room.get("window_state") is None:
            score += 1.0
        score += min(wind_on, 6.0)
        if t is not None and indoor_avg is not None:
            score += max(0.0, indoor_avg - t)  # cooler indoor side
        if outdoor is not None and t is not None:
            score += max(0.0, t - outdoor) * 0.15
        return score

    def outlet_score(room: dict[str, Any], inlet_id: str) -> float:
        orients = tuple(room.get("exterior") or ())
        inlet = by_id.get(inlet_id) or {}
        sep = _facade_sep_deg(orients, tuple(inlet.get("exterior") or ()))
        wind_on = wind_on_facade_ms(orients, wind_speed_ms, wind_direction_deg)
        # Leeward preference: low wind-on when wind known.
        leeward = 0.0
        if wind_speed_ms is not None and float(wind_speed_ms) >= WIND_MIN_MS:
            leeward = max(0.0, float(wind_speed_ms) - wind_on)
        t = _room_live_temp(room)
        score = 0.0
        if str(room.get("window_state") or "") == "open":
            score += 3.0
        score += min(sep / 45.0, 4.0)  # opposing façades
        score += min(leeward, 5.0)
        if t is not None:
            score += t * 0.35  # hotter chimney
        return score

    ranked_inlets = sorted(facade_rooms, key=inlet_score, reverse=True)
    best: dict[str, Any] | None = None
    for inlet in ranked_inlets[:4]:
        inlet_id = str(inlet["id"])
        outlets = [
            r for r in facade_rooms if str(r["id"]) != inlet_id
        ] or facade_rooms
        outlets = sorted(
            outlets, key=lambda r: outlet_score(r, inlet_id), reverse=True
        )
        for outlet in outlets[:4]:
            outlet_id = str(outlet["id"])
            if outlet_id == inlet_id:
                continue
            nodes, used = shortest_path(inlet_id, outlet_id)
            if not nodes:
                continue
            open_penalty = sum(
                2.0
                for e in used
                if str(e.get("opening") or "") == "closed"
            )
            quality = (
                inlet_score(inlet)
                + outlet_score(outlet, inlet_id)
                - 0.4 * sum(path_cost(e) for e in used)
                - open_penalty
            )
            if best is None or quality > best["quality"]:
                best = {
                    "quality": quality,
                    "inlet": inlet,
                    "outlet": outlet,
                    "path": nodes,
                    "edges": used,
                }

    if best is None:
        # Single façade: still suggest inlet/exhaust on that room.
        room = ranked_inlets[0]
        rid = str(room["id"])
        label = room.get("label") or rid
        win = str(room.get("window_state") or "")
        actions = []
        if win != "open":
            actions.append(f"Open {label} window for night purge when outdoor is cooler.")
        else:
            actions.append(f"Keep {label} window open; add a fan toward the corridor.")
        return {
            "mode": "cooling",
            "outdoor_temp_c": outdoor,
            "indoor_temp_c": indoor_avg,
            "delta_c": (
                round(outdoor - indoor_avg, 2)
                if outdoor is not None and indoor_avg is not None
                else None
            ),
            "inlet": {"room": rid, "label": label, "role": "inlet"},
            "outlet": {"room": rid, "label": label, "role": "outlet"},
            "path": [rid],
            "flows": [
                {
                    "from": f"ext:{rid}",
                    "to": rid,
                    "kind": "exterior",
                    "role": "inlet",
                    "strength": 1.0,
                },
                {
                    "from": rid,
                    "to": f"ext:{rid}",
                    "kind": "exterior",
                    "role": "outlet",
                    "strength": 0.6,
                },
            ],
            "actions": actions,
        }

    inlet = best["inlet"]
    outlet = best["outlet"]
    path: list[str] = best["path"]
    used_edges: list[dict[str, Any]] = best["edges"]
    inlet_id = str(inlet["id"])
    outlet_id = str(outlet["id"])
    inlet_label = inlet.get("label") or inlet_id
    outlet_label = outlet.get("label") or outlet_id

    flows: list[dict[str, Any]] = [
        {
            "from": f"ext:{inlet_id}",
            "to": inlet_id,
            "kind": "exterior",
            "role": "inlet",
            "strength": 1.0,
        }
    ]
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        edge = used_edges[i] if i < len(used_edges) else {}
        opening = str(edge.get("opening") or "unknown")
        strength = 1.0 if opening == "open" else 0.7 if opening != "closed" else 0.45
        flows.append(
            {
                "from": a,
                "to": b,
                "kind": str(edge.get("kind") or "door"),
                "role": "path",
                "strength": strength,
                "opening": opening,
                "needs_open": opening == "closed",
            }
        )
    flows.append(
        {
            "from": outlet_id,
            "to": f"ext:{outlet_id}",
            "kind": "exterior",
            "role": "outlet",
            "strength": 1.0,
        }
    )

    actions: list[str] = []
    if str(inlet.get("window_state") or "") != "open":
        actions.append(f"Open {inlet_label} window (cool air inlet).")
    else:
        actions.append(f"Keep {inlet_label} window open (inlet).")
    if str(outlet.get("window_state") or "") != "open":
        actions.append(f"Open {outlet_label} window (warm air outlet).")
    else:
        actions.append(f"Keep {outlet_label} window open (outlet).")
    for edge in used_edges:
        if str(edge.get("opening") or "") != "closed":
            continue
        a = str(edge.get("a") or "")
        b = str(edge.get("b") or "")
        la = (by_id.get(a) or {}).get("label") or a
        lb = (by_id.get(b) or {}).get("label") or b
        actions.append(f"Open door between {la} and {lb} to complete the draft.")
    # Discourage trapping heat in rooms off the path with open windows only.
    for room in facade_rooms:
        rid = str(room["id"])
        if rid in (inlet_id, outlet_id):
            continue
        if str(room.get("window_state") or "") == "open":
            label = room.get("label") or rid
            actions.append(
                f"Optional: close {label} window if it short-circuits the "
                f"{inlet_label} → {outlet_label} path."
            )

    mode = "cooling"
    if outdoor is None:
        mode = "cooling_est"
    return {
        "mode": mode,
        "outdoor_temp_c": outdoor,
        "indoor_temp_c": indoor_avg,
        "delta_c": (
            round(outdoor - indoor_avg, 2)
            if outdoor is not None and indoor_avg is not None
            else None
        ),
        "inlet": {
            "room": inlet_id,
            "label": inlet_label,
            "role": "inlet",
            "exterior": list(inlet.get("exterior") or []),
            "window_state": inlet.get("window_state"),
        },
        "outlet": {
            "room": outlet_id,
            "label": outlet_label,
            "role": "outlet",
            "exterior": list(outlet.get("exterior") or []),
            "window_state": outlet.get("window_state"),
        },
        "path": path,
        "flows": flows,
        "actions": actions,
        "wind_compass": (
            (compass_from_deg(wind_direction_deg) or "").upper() or None
            if wind_direction_deg is not None
            else None
        ),
        "wind_speed_ms": (
            round(float(wind_speed_ms), 2) if wind_speed_ms is not None else None
        ),
    }


def _angle_diff_deg(a: float, b: float) -> float:
    """Smallest signed difference a−b in (−180, 180]."""
    return (float(a) - float(b) + 180.0) % 360.0 - 180.0


def compass_from_deg(deg: float | None) -> str | None:
    """Nearest 8-point compass label for a meteorological wind direction."""
    if deg is None:
        return None
    idx = int((float(deg) % 360.0 + 22.5) // 45.0) % 8
    return ORIENTATIONS[idx]


def wind_on_facade_ms(
    orientations: tuple[str, ...] | list[str],
    wind_speed_ms: float | None,
    wind_direction_deg: float | None,
) -> float:
    """
    Windward component (m/s) hitting the given façade orientation(s).

    Wind from the same compass sector as the façade presses on it
    (cos of angle between wind-from and façade normal ≥ 0).
    """
    if (
        wind_speed_ms is None
        or wind_direction_deg is None
        or not orientations
        or wind_speed_ms <= 0
    ):
        return 0.0
    best = 0.0
    for o in orientations:
        face = ORIENTATION_DEG.get(str(o).strip().lower())
        if face is None:
            continue
        # Positive cos → wind hits this façade
        cos_w = math.cos(math.radians(_angle_diff_deg(wind_direction_deg, face)))
        best = max(best, float(wind_speed_ms) * max(0.0, cos_w))
    return best


def cross_vent_ms(
    orientations: tuple[str, ...] | list[str],
    wind_speed_ms: float | None,
    wind_direction_deg: float | None,
) -> float:
    """
    Cross-ventilation potential (m/s) along roughly opposing façades.

    Uses apartment exterior orientations: wind aligned with a pair ~180° apart
    drives inlet on one side and outlet on the other.
    """
    if wind_speed_ms is None or wind_direction_deg is None or wind_speed_ms <= 0:
        return 0.0
    faces = sorted(
        {
            ORIENTATION_DEG[key]
            for raw in orientations
            for key in [str(raw).strip().lower()]
            if key in ORIENTATION_DEG
        }
    )
    if len(faces) < 2:
        # Single façade: only windward component matters
        return wind_on_facade_ms(tuple(orientations), wind_speed_ms, wind_direction_deg)

    best = 0.0
    for i, a in enumerate(faces):
        for b in faces[i + 1 :]:
            sep = abs(_angle_diff_deg(a, b))
            if sep < 120.0:  # need roughly opposing openings
                continue
            # Wind along either façade normal drives cross-flow
            align = max(
                abs(math.cos(math.radians(_angle_diff_deg(wind_direction_deg, a)))),
                abs(math.cos(math.radians(_angle_diff_deg(wind_direction_deg, b)))),
            )
            best = max(best, float(wind_speed_ms) * align)
    return best


def ventilation_mode(
    *,
    window_kind: str | None,
    orientations: tuple[str, ...] | list[str],
    all_exterior: tuple[str, ...] | list[str] | None = None,
    wind_speed_ms: float | None,
    wind_direction_deg: float | None,
) -> dict[str, Any]:
    """
    Natural vs mechanical ventilation hint for a façade / room.

    - natural: windows useful for cooling (open) and wind drives draft
    - mechanical: need air change but wind weak / wrong way, or windows closed
    - none: no window advice (near thermal balance)
    """
    wind_on = wind_on_facade_ms(orientations, wind_speed_ms, wind_direction_deg)
    pool = list(all_exterior) if all_exterior is not None else list(orientations)
    cross = cross_vent_ms(pool, wind_speed_ms, wind_direction_deg)
    effective = max(wind_on, cross)
    compass = compass_from_deg(wind_direction_deg)

    base = {
        "wind_on_facade_ms": round(wind_on, 2),
        "cross_vent_ms": round(cross, 2),
        "effective_ms": round(effective, 2),
        "wind_speed_ms": (
            round(float(wind_speed_ms), 2) if wind_speed_ms is not None else None
        ),
        "wind_direction_deg": (
            round(float(wind_direction_deg), 1)
            if wind_direction_deg is not None
            else None
        ),
        "wind_compass": compass.upper() if compass else None,
    }

    if window_kind in ("close", "humid"):
        return {
            **base,
            "mode": "mechanical",
            "reason": "windows_closed",
        }
    if window_kind != "open":
        return {**base, "mode": None, "reason": "no_window_advice"}

    if wind_speed_ms is None or wind_direction_deg is None:
        return {**base, "mode": "mechanical", "reason": "wind_unknown"}
    if float(wind_speed_ms) < WIND_MIN_MS:
        return {**base, "mode": "mechanical", "reason": "wind_calm"}
    if effective < WIND_MIN_MS:
        return {**base, "mode": "mechanical", "reason": "wind_parallel"}
    return {**base, "mode": "natural", "reason": "wind_favorable"}

@dataclass(frozen=True)
class RoomSpec:
    id: str
    area_m2: float
    exterior: tuple[str, ...] = ()
    label: str = ""

    @property
    def volume_m3(self) -> float:
        return self.area_m2  # multiplied by ceiling later

    @property
    def faces_exterior(self) -> bool:
        return bool(self.exterior)


@dataclass(frozen=True)
class EdgeSpec:
    a: str
    b: str
    kind: str = "door"


@dataclass
class ApartmentLayout:
    enabled: bool = False
    ceiling_m: float = DEFAULT_CEILING_M
    door_height_m: float = DEFAULT_DOOR_HEIGHT_M
    area_m2: float = 35.0
    floor: int = 3
    floors_total: int = 7
    timezone: str = "Europe/Paris"
    rooms: dict[str, RoomSpec] = field(default_factory=dict)
    edges: list[EdgeSpec] = field(default_factory=list)
    # Precomputed
    capacity: dict[str, float] = field(default_factory=dict)
    k_pair: dict[tuple[str, str], float] = field(default_factory=dict)
    k_ext: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ApartmentLayout:
        raw = raw or {}
        enabled = bool(raw.get("enabled", False))
        ceiling_m = float(raw.get("ceiling_m") or DEFAULT_CEILING_M)
        if ceiling_m < 1.5:
            ceiling_m = 1.5
        door_height_m = float(raw.get("door_height_m") or DEFAULT_DOOR_HEIGHT_M)
        if door_height_m < 0.8:
            door_height_m = 0.8
        if door_height_m >= ceiling_m:
            door_height_m = ceiling_m * _DOOR_K_REF_OPENING_FRAC
        area_m2 = float(raw.get("area_m2") or 35.0)
        floor = int(raw.get("floor") or 3)
        floors_total = int(raw.get("floors_total") or 7)
        timezone_name = str(raw.get("timezone") or "Europe/Paris").strip() or "Europe/Paris"

        rooms: dict[str, RoomSpec] = {}
        for item in raw.get("rooms") or []:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id") or "").strip().lower()
            if not rid:
                continue
            try:
                area = float(item.get("area_m2") or 0)
            except (TypeError, ValueError):
                continue
            if area <= 0:
                continue
            ext_raw = item.get("exterior") or []
            if isinstance(ext_raw, str):
                ext_raw = [ext_raw]
            exterior = tuple(
                str(o).strip().lower()
                for o in ext_raw
                if str(o).strip().lower() in ORIENTATIONS
            )
            rooms[rid] = RoomSpec(
                id=rid,
                area_m2=area,
                exterior=exterior,
                label=str(item.get("label") or rid),
            )

        edges: list[EdgeSpec] = []
        for item in raw.get("edges") or []:
            if not isinstance(item, dict):
                continue
            a = str(item.get("a") or "").strip().lower()
            b = str(item.get("b") or "").strip().lower()
            kind = str(item.get("kind") or "door").strip().lower()
            if a not in rooms or b not in rooms or a == b:
                continue
            if kind not in K_BY_EDGE:
                kind = "door"
            edges.append(EdgeSpec(a=a, b=b, kind=kind))

        layout = cls(
            enabled=enabled,
            ceiling_m=ceiling_m,
            door_height_m=door_height_m,
            area_m2=area_m2,
            floor=floor,
            floors_total=floors_total,
            timezone=timezone_name,
            rooms=rooms,
            edges=edges,
        )
        layout._rebuild_matrices()
        return layout

    def _rebuild_matrices(self) -> None:
        self.capacity = {}
        self.k_pair = {}
        self.k_ext = {}
        for rid, room in self.rooms.items():
            vol = room.area_m2 * self.ceiling_m
            self.capacity[rid] = C_AIR * vol * C_STRUCTURE_FACTOR
            if room.faces_exterior:
                self.k_ext[rid] = K_EXT_PER_M2 * room.area_m2 * K_SCALE
            else:
                self.k_ext[rid] = 0.0
        door_scale = min(1.0, max(0.25, self.door_height_m / self.ceiling_m)) / (
            _DOOR_K_REF_OPENING_FRAC or 1.0
        )
        for edge in self.edges:
            k = K_BY_EDGE.get(edge.kind, K_BY_EDGE["door"]) * K_SCALE
            if edge.kind == "door":
                # Open-door mixing cannot vent the transom above the lintel.
                k *= door_scale
            key = (edge.a, edge.b) if edge.a < edge.b else (edge.b, edge.a)
            self.k_pair[key] = self.k_pair.get(key, 0.0) + k

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "ceiling_m": self.ceiling_m,
            "door_height_m": self.door_height_m,
            "window_sill_m": DEFAULT_WINDOW_SILL_M,
            "height_bands_cm": height_bands_cm(
                self.ceiling_m, self.door_height_m
            ),
            "area_m2": self.area_m2,
            "floor": self.floor,
            "floors_total": self.floors_total,
            "timezone": self.timezone,
            "orientations": [
                {"id": o, "label": ORIENTATION_LABELS[o]} for o in ORIENTATIONS
            ],
            "rooms": [
                {
                    "id": r.id,
                    "area_m2": r.area_m2,
                    "exterior": list(r.exterior),
                    "label": r.label or r.id,
                    "faces_exterior": r.faces_exterior,
                    "k_ext": round(self.k_ext.get(r.id, 0.0), 2),
                }
                for r in self.rooms.values()
            ],
            "edges": [
                {"a": e.a, "b": e.b, "kind": e.kind} for e in self.edges
            ],
        }

    def set_exterior(self, room_id: str, exterior: list[str] | tuple[str, ...]) -> dict[str, Any]:
        """Update façade orientations for a room. Returns updated room summary."""
        rid = room_id.strip().lower()
        room = self.rooms.get(rid)
        if room is None:
            raise KeyError(f"Unknown room: {rid}")
        cleaned = tuple(
            o
            for o in (str(x).strip().lower() for x in exterior)
            if o in ORIENTATIONS
        )
        # Stable compass order
        cleaned = tuple(o for o in ORIENTATIONS if o in cleaned)
        self.rooms[rid] = RoomSpec(
            id=room.id,
            area_m2=room.area_m2,
            exterior=cleaned,
            label=room.label,
        )
        self._rebuild_matrices()
        r = self.rooms[rid]
        return {
            "id": r.id,
            "area_m2": r.area_m2,
            "exterior": list(r.exterior),
            "label": r.label or r.id,
            "faces_exterior": r.faces_exterior,
            "k_ext": round(self.k_ext.get(r.id, 0.0), 2),
        }

    def apply_overrides(self, overrides: dict[str, Any] | None) -> int:
        """Apply persisted exterior overrides. Returns number of rooms updated."""
        if not overrides:
            return 0
        rooms = overrides.get("rooms") or {}
        if not isinstance(rooms, dict):
            return 0
        n = 0
        for rid, patch in rooms.items():
            if not isinstance(patch, dict):
                continue
            if "exterior" not in patch:
                continue
            if rid not in self.rooms:
                continue
            ext = patch.get("exterior") or []
            if isinstance(ext, str):
                ext = [ext]
            self.set_exterior(str(rid), list(ext))
            n += 1
        return n

    def can_network_project(self, room_ids_with_sensors: set[str]) -> bool:
        """Need layout on, corridor node, and at least two mapped interior rooms."""
        if not self.enabled or not self.rooms:
            return False
        if "corridor" not in self.rooms:
            return False
        mapped = {r for r in room_ids_with_sensors if r in self.rooms}
        return len(mapped) >= 2

    def neighbors(self, room_id: str) -> list[str]:
        out: list[str] = []
        for (a, b), _ in self.k_pair.items():
            if a == room_id:
                out.append(b)
            elif b == room_id:
                out.append(a)
        return out


def solar_bias_c(
    orientations: tuple[str, ...],
    ts: float,
    tz_name: str,
    *,
    shortwave_radiation: float | None = None,
    cloud_cover: float | None = None,
) -> float:
    """
    Façade solar gain bias (°C) from orientation, hour, and weather.

    Prefer Open-Meteo shortwave_radiation (W/m²), which already embeds clouds.
    If missing, fall back to a clear-sky hour curve attenuated by cloud_cover %.
    """
    if not orientations:
        return 0.0
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    local = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz)
    hour = local.hour + local.minute / 60.0

    # Orientation weight peaking when the sun faces that façade (0–1).
    def orient_weight(o: str) -> float:
        if o == "sw":
            phase = math.sin(math.pi * max(0.0, min(1.0, (hour - 12.0) / 8.0)))
            return max(0.0, phase)
        if o == "ne":
            phase = math.sin(math.pi * max(0.0, min(1.0, (hour - 5.0) / 6.0)))
            return max(0.0, phase)
        if o in ("s", "se"):
            phase = math.sin(math.pi * max(0.0, min(1.0, (hour - 9.0) / 8.0)))
            return max(0.0, phase)
        if o == "w":
            phase = math.sin(math.pi * max(0.0, min(1.0, (hour - 13.0) / 7.0)))
            return max(0.0, phase)
        if o == "e":
            phase = math.sin(math.pi * max(0.0, min(1.0, (hour - 6.0) / 6.0)))
            return max(0.0, phase)
        if o in ("n", "nw"):
            if hour < 6.0 or hour > 21.0:
                return 0.0
            return 0.25 * max(
                0.0, math.sin(math.pi * (hour - 6.0) / 15.0)
            )
        return 0.0

    # Peak clear-sky gain by orientation (°C at G_ref).
    peak = {
        "sw": 4.0,
        "ne": 1.5,
        "s": 3.0,
        "se": 2.8,
        "w": 3.2,
        "e": 2.2,
        "n": 0.6,
        "nw": 0.8,
    }

    g_ref = 800.0  # W/m² reference clear midday
    if shortwave_radiation is not None and shortwave_radiation >= 0:
        insolation = max(0.0, min(1.35, float(shortwave_radiation) / g_ref))
    else:
        # Clear-sky day envelope × cloud attenuation
        if hour < 6.0 or hour > 21.0:
            day = 0.0
        else:
            day = max(0.0, math.sin(math.pi * (hour - 6.0) / 15.0))
        cloud = 0.0 if cloud_cover is None else max(0.0, min(100.0, float(cloud_cover)))
        # Overcast still lets some diffuse light through
        cloud_factor = 1.0 - 0.75 * (cloud / 100.0)
        insolation = day * cloud_factor

    bias = 0.0
    for o in orientations:
        w = orient_weight(o)
        if w <= 0:
            continue
        bias = max(bias, peak.get(o, 1.5) * w * insolation)
    return bias


def _pair_k(layout: ApartmentLayout, a: str, b: str) -> float:
    key = (a, b) if a < b else (b, a)
    return layout.k_pair.get(key, 0.0)


def init_temperatures(
    layout: ApartmentLayout,
    measured: dict[str, float],
) -> dict[str, float]:
    """Fill passive nodes from neighbors / measured mean."""
    temps = dict(measured)
    mean = sum(measured.values()) / len(measured) if measured else 20.0
    # Prefer corridor as hub guess
    if "corridor" in measured:
        hub = measured["corridor"]
    else:
        hub = mean

    pending = [rid for rid in layout.rooms if rid not in temps]
    # Iterate to propagate from known rooms
    for _ in range(len(layout.rooms) + 1):
        progress = False
        for rid in list(pending):
            neigh = layout.neighbors(rid)
            known = [temps[n] for n in neigh if n in temps]
            if known:
                temps[rid] = sum(known) / len(known)
                pending.remove(rid)
                progress = True
            elif rid == "corridor":
                temps[rid] = hub
                pending.remove(rid)
                progress = True
        if not progress:
            break
    for rid in pending:
        temps[rid] = hub
    return temps


def network_step(
    layout: ApartmentLayout,
    temps: dict[str, float],
    *,
    t_ext: float,
    ts: float,
    dt_s: float,
    shortwave_radiation: float | None = None,
    cloud_cover: float | None = None,
) -> dict[str, float]:
    """One explicit Euler step of the multi-node RC network."""
    if dt_s <= 0:
        return dict(temps)
    # Sub-step for stability (doors are stiff vs hourly dt)
    n_sub = max(1, int(math.ceil(dt_s / 300.0)))
    h = dt_s / n_sub
    state = dict(temps)
    room_ids = list(layout.rooms.keys())

    for _ in range(n_sub):
        deriv: dict[str, float] = {rid: 0.0 for rid in room_ids}
        for rid in room_ids:
            t_i = state[rid]
            c_i = layout.capacity[rid]
            if c_i <= 0:
                continue
            power = 0.0
            for other in room_ids:
                if other == rid:
                    continue
                k = _pair_k(layout, rid, other)
                if k <= 0:
                    continue
                power += k * (state[other] - t_i)
            k_ext = layout.k_ext.get(rid, 0.0)
            if k_ext > 0:
                room = layout.rooms[rid]
                t_eff = t_ext + solar_bias_c(
                    room.exterior,
                    ts,
                    layout.timezone,
                    shortwave_radiation=shortwave_radiation,
                    cloud_cover=cloud_cover,
                )
                power += k_ext * (t_eff - t_i)
            deriv[rid] = power / c_i
        for rid in room_ids:
            state[rid] = state[rid] + h * deriv[rid]
    return state


def simulate_network(
    layout: ApartmentLayout,
    measured: dict[str, float],
    outdoor_future: list[dict[str, Any]],
    *,
    ts0: float,
) -> dict[str, list[float]]:
    """
    Simulate all rooms over future outdoor points.
    Returns room_id → list of temperatures aligned with outdoor_future.
    """
    state = init_temperatures(layout, measured)
    series: dict[str, list[float]] = {rid: [] for rid in layout.rooms}
    prev_ts = ts0
    for p in outdoor_future:
        ts = float(p["ts"])
        t_ext = float(p["temperature_c"])
        dt = max(0.0, ts - prev_ts)
        sw = p.get("shortwave_radiation")
        cloud = p.get("cloud_cover")
        state = network_step(
            layout,
            state,
            t_ext=t_ext,
            ts=ts,
            dt_s=dt,
            shortwave_radiation=float(sw) if sw is not None else None,
            cloud_cover=float(cloud) if cloud is not None else None,
        )
        for rid in layout.rooms:
            series[rid].append(state[rid])
        prev_ts = ts
    return series


def load_overrides(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_OVERRIDES_PATH
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.warning("Apartment overrides unreadable: %s", exc)
    return {"rooms": {}}


def save_overrides(layout: ApartmentLayout, path: Path | None = None) -> None:
    """Persist current exterior orientations for all rooms."""
    path = path or DEFAULT_OVERRIDES_PATH
    payload = {
        "rooms": {
            rid: {"exterior": list(room.exterior)}
            for rid, room in layout.rooms.items()
        }
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        logger.warning("Apartment overrides write failed: %s", exc)
        raise


def default_apartment_dict() -> dict[str, Any]:
    """Canonical layout for the user's T3 (config.example defaults)."""
    return {
        "enabled": False,
        "ceiling_m": DEFAULT_CEILING_M,
        "door_height_m": DEFAULT_DOOR_HEIGHT_M,
        "area_m2": 35.0,
        "floor": 3,
        "floors_total": 7,
        "timezone": "Europe/Paris",
        "rooms": [
            {"id": "bedroom", "area_m2": 10.9, "exterior": ["ne"], "label": "Bedroom"},
            {"id": "living", "area_m2": 10.8, "exterior": ["sw"], "label": "Living room"},
            {"id": "kitchen", "area_m2": 5.6, "exterior": ["sw"], "label": "Kitchen"},
            {"id": "corridor", "area_m2": 4.0, "exterior": [], "label": "Corridor"},
            {"id": "bathroom", "area_m2": 2.5, "exterior": [], "label": "Bathroom"},
            {"id": "wc", "area_m2": 1.2, "exterior": [], "label": "WC"},
        ],
        "edges": [
            {"a": "corridor", "b": "bedroom", "kind": "door"},
            {"a": "corridor", "b": "living", "kind": "door"},
            {"a": "corridor", "b": "kitchen", "kind": "door"},
            {"a": "corridor", "b": "bathroom", "kind": "door"},
            {"a": "corridor", "b": "wc", "kind": "door"},
            {"a": "kitchen", "b": "living", "kind": "wall_partial"},
            {"a": "kitchen", "b": "wc", "kind": "wall"},
            {"a": "living", "b": "wc", "kind": "wall"},
            {"a": "bedroom", "b": "bathroom", "kind": "wall"},
        ],
    }
