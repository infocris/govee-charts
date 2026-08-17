"""Apartment connection ids and layout sync helpers."""

from __future__ import annotations

from typing import Any

OUTDOOR = "outdoor"
PASSABLE_KINDS = frozenset({"door", "wall_partial"})


def connection_id_for_rooms(a: str, b: str) -> str:
    """Canonical undirected id for two room nodes (lexicographic)."""
    left = str(a or "").strip().lower()
    right = str(b or "").strip().lower()
    if not left or not right:
        raise ValueError("both rooms required")
    if left == right:
        raise ValueError("rooms must differ")
    if left > right:
        left, right = right, left
    return f"{left}|{right}"


def outdoor_connection_id(room: str) -> str:
    """Canonical id for a room ↔ outdoor opening."""
    rid = str(room or "").strip().lower()
    if not rid or rid == OUTDOOR:
        raise ValueError("invalid room for outdoor connection")
    return connection_id_for_rooms(rid, OUTDOOR)


def parse_connection_id(connection_id: str) -> tuple[str, str]:
    """Split a connection id into (room_a, room_b) with a < b."""
    text = str(connection_id or "").strip().lower()
    parts = text.split("|")
    if len(parts) != 2 or not parts[0] or not parts[1] or parts[0] == parts[1]:
        raise ValueError(f"invalid connection id: {connection_id!r}")
    a, b = parts[0], parts[1]
    if a > b:
        a, b = b, a
    return a, b


def is_outdoor_connection(connection_id: str) -> bool:
    try:
        a, b = parse_connection_id(connection_id)
    except ValueError:
        return False
    return OUTDOOR in (a, b)


def indoor_room_of_outdoor(connection_id: str) -> str | None:
    try:
        a, b = parse_connection_id(connection_id)
    except ValueError:
        return None
    if a == OUTDOOR:
        return b
    if b == OUTDOOR:
        return a
    return None


def layout_connection_specs(
    rooms: list[dict[str, Any]] | dict[str, Any],
    edges: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """
    Build the expected connection catalog from an apartment layout.

    Includes every passable edge (door / wall_partial), outdoor openings for
    rooms with an exterior façade, and an outdoor opening for the hub room
    (entrance door).
    """
    room_meta: dict[str, dict[str, Any]] = {}
    if isinstance(rooms, dict):
        for rid, room in rooms.items():
            key = str(rid).strip().lower()
            if not key:
                continue
            if isinstance(room, dict):
                room_meta[key] = room
            else:
                room_meta[key] = {
                    "id": key,
                    "exterior": getattr(room, "exterior", ()) or (),
                }
    else:
        for r in rooms:
            rid = str(r.get("id") or "").strip().lower()
            if rid:
                room_meta[rid] = r
    room_set = set(room_meta)
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    degree: dict[str, int] = {rid: 0 for rid in room_set}
    for edge in edges or []:
        kind = str(edge.get("kind") or "door").strip().lower()
        if kind not in PASSABLE_KINDS:
            continue
        a = str(edge.get("a") or "").strip().lower()
        b = str(edge.get("b") or "").strip().lower()
        if a not in room_set or b not in room_set or a == b:
            continue
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
        cid = connection_id_for_rooms(a, b)
        if cid in seen:
            continue
        seen.add(cid)
        left, right = parse_connection_id(cid)
        out.append(
            {
                "connection_id": cid,
                "room_a": left,
                "room_b": right,
                "kind": kind,
            }
        )

    hub_id = max(degree, key=degree.get) if degree else None
    outdoor_rooms = set()
    for rid, room in room_meta.items():
        exterior = room.get("exterior") if isinstance(room, dict) else None
        if exterior is None and not isinstance(room, dict):
            exterior = getattr(room, "exterior", None)
        if exterior:
            outdoor_rooms.add(rid)
    if hub_id:
        outdoor_rooms.add(hub_id)

    for rid in sorted(outdoor_rooms):
        cid = outdoor_connection_id(rid)
        if cid in seen:
            continue
        seen.add(cid)
        left, right = parse_connection_id(cid)
        out.append(
            {
                "connection_id": cid,
                "room_a": left,
                "room_b": right,
                "kind": "outdoor",
            }
        )

    return out


def migrate_sensor_to_connection(
    *,
    room: str | None,
    kind: str | None,
    passable_edges: list[dict[str, str]],
    hub_id: str | None,
) -> str | None:
    """
    Best-effort map legacy door_sensors.room/kind onto a connection id.

    - window → room|outdoor
    - door on hub → hub|outdoor (entrance)
    - door on leaf with a unique passable edge → that edge
    - door with exactly one passable edge involving the room → that edge
    """
    rid = str(room or "").strip().lower()
    ck = str(kind or "").strip().lower() or "door"
    if not rid:
        return None
    if ck == "window":
        return outdoor_connection_id(rid)
    if ck not in ("door", "other", ""):
        # Unknown kinds stay unassigned.
        if ck == "outdoor":
            return outdoor_connection_id(rid)
        return None

    involving = [
        e
        for e in passable_edges
        if rid in (e.get("room_a"), e.get("room_b"))
        and e.get("kind") in PASSABLE_KINDS
    ]
    if hub_id and rid == hub_id:
        return outdoor_connection_id(rid)
    if len(involving) == 1:
        return involving[0]["connection_id"]
    # Prefer the hub↔leaf door when several edges touch the room.
    if hub_id:
        for e in involving:
            ends = {e.get("room_a"), e.get("room_b")}
            if hub_id in ends and e.get("kind") == "door":
                return e["connection_id"]
    return None


def effective_opening_from_sensors(
    sensors: list[dict[str, Any]],
) -> tuple[str | None, float | None]:
    """OR of contact states: any open → open; all closed → closed."""
    states: list[str] = []
    latest_ts: float | None = None
    for s in sensors:
        st = str(s.get("state") or "").strip().lower()
        if st not in ("open", "closed"):
            continue
        states.append(st)
        try:
            ts = float(s.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if latest_ts is None or ts > latest_ts:
            latest_ts = ts
    if not states:
        return None, None
    if any(st == "open" for st in states):
        return "open", latest_ts
    if all(st == "closed" for st in states):
        return "closed", latest_ts
    return None, latest_ts
