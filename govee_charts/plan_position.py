"""Wall-anchored isomorphic sensor positions on floor-plan room rectangles."""

from __future__ import annotations

from typing import Any

PLAN_WALLS = frozenset({"n", "s", "e", "w"})


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def normalize_plan_patch(
    *,
    plan_wall: Any = ...,
    plan_u: Any = ...,
    plan_v: Any = ...,
) -> dict[str, Any]:
    """Validate optional plan position fields for placement updates."""
    out: dict[str, Any] = {}
    if plan_wall is not ...:
        if plan_wall is None:
            out["plan_wall"] = None
            out["plan_u"] = None
            out["plan_v"] = None
        else:
            wall = str(plan_wall).strip().lower()
            if wall not in PLAN_WALLS:
                raise ValueError(f"plan_wall must be one of {sorted(PLAN_WALLS)}")
            out["plan_wall"] = wall
    if plan_u is not ...:
        if plan_u is None:
            out["plan_u"] = None
        else:
            out["plan_u"] = round(_clamp01(float(plan_u)), 4)
    if plan_v is not ...:
        if plan_v is None:
            out["plan_v"] = None
        else:
            out["plan_v"] = round(_clamp01(float(plan_v)), 4)
    if "plan_wall" in out and out["plan_wall"] is not None:
        if plan_u is ... or plan_v is ...:
            raise ValueError("plan_u and plan_v are required with plan_wall")
        if out.get("plan_u") is None or out.get("plan_v") is None:
            raise ValueError("plan_u and plan_v are required with plan_wall")
    return out


def encode_plan_position(
    rect: dict[str, Any], *, x: float, y: float
) -> dict[str, float | str]:
    """Nearest wall anchor + isomorphic (u along wall, v into room)."""
    rx = float(rect["x"])
    ry = float(rect["y"])
    rw = max(float(rect["w"]), 1e-6)
    rh = max(float(rect["h"]), 1e-6)
    px = float(x)
    py = float(y)

    d_n = py - ry
    d_s = (ry + rh) - py
    d_w = px - rx
    d_e = (rx + rw) - px
    best = min(
        (d_n, "n"),
        (d_s, "s"),
        (d_w, "w"),
        (d_e, "e"),
        key=lambda item: item[0],
    )
    wall = best[1]
    if wall == "n":
        u = (px - rx) / rw
        v = d_n / rh
    elif wall == "s":
        u = (px - rx) / rw
        v = d_s / rh
    elif wall == "w":
        u = (py - ry) / rh
        v = d_w / rw
    else:
        u = (py - ry) / rh
        v = d_e / rw
    return {
        "plan_wall": wall,
        "plan_u": round(_clamp01(u), 4),
        "plan_v": round(_clamp01(v), 4),
    }


def decode_plan_position(
    rect: dict[str, Any], *, plan_wall: str, plan_u: float, plan_v: float
) -> dict[str, float]:
    """Canvas point from wall anchor + relative coordinates."""
    rx = float(rect["x"])
    ry = float(rect["y"])
    rw = max(float(rect["w"]), 1e-6)
    rh = max(float(rect["h"]), 1e-6)
    wall = str(plan_wall).strip().lower()
    u = _clamp01(plan_u)
    v = _clamp01(plan_v)
    if wall == "n":
        return {"x": rx + u * rw, "y": ry + v * rh}
    if wall == "s":
        return {"x": rx + u * rw, "y": ry + rh - v * rh}
    if wall == "w":
        return {"x": rx + v * rw, "y": ry + u * rh}
    if wall == "e":
        return {"x": rx + rw - v * rw, "y": ry + u * rh}
    raise ValueError(f"Unknown plan_wall {plan_wall!r}")
