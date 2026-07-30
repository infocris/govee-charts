"""Sensor category taxonomy and validation."""

from __future__ import annotations

from typing import Any

ZONES = ("interior", "exterior")
HEIGHTS = ("high", "mid", "low")
ROOMS = ("kitchen", "bedroom", "corridor", "living", "other")

ZONE_LABELS = {
    "interior": "Interior",
    "exterior": "Exterior",
}
HEIGHT_LABELS = {
    "high": "High",
    "mid": "Mid",
    "low": "Low",
}
ROOM_LABELS = {
    "kitchen": "Kitchen",
    "bedroom": "Bedroom",
    "corridor": "Corridor",
    "living": "Living room",
    "other": "Other",
}

_ALIASES = {
    "intérieur": "interior",
    "interieur": "interior",
    "extérieur": "exterior",
    "exterieur": "exterior",
    "haute": "high",
    "haut": "high",
    "mid": "mid",
    "middle": "mid",
    "moyen": "mid",
    "milieu": "mid",
    "basse": "low",
    "bas": "low",
    "cuisine": "kitchen",
    "chambre": "bedroom",
    "couloir": "corridor",
    "séjour": "living",
    "sejour": "living",
    "salon": "living",
    "autre": "other",
}


def taxonomy() -> dict[str, Any]:
    return {
        "zones": [{"id": z, "label": ZONE_LABELS[z]} for z in ZONES],
        "heights": [{"id": h, "label": HEIGHT_LABELS[h]} for h in HEIGHTS],
        "rooms": [{"id": r, "label": ROOM_LABELS[r]} for r in ROOMS],
    }


def _norm_choice(value: Any, allowed: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in ("none", "null", "unset", "-"):
        return None
    text = _ALIASES.get(text, text)
    if text not in allowed:
        raise ValueError(f"Invalid value {value!r}; expected one of {allowed}")
    return text


def normalize_patch(
    *,
    zone: Any = ...,
    height: Any = ...,
    room: Any = ...,
) -> dict[str, str | None]:
    """Build a partial update dict. Ellipsis means 'field not provided'."""
    out: dict[str, str | None] = {}
    if zone is not ...:
        out["zone"] = _norm_choice(zone, ZONES)
    if height is not ...:
        out["height"] = _norm_choice(height, HEIGHTS)
    if room is not ...:
        out["room"] = _norm_choice(room, ROOMS)
    return out


def infer_from_label(label: str) -> dict[str, str | None]:
    """Best-effort inference from an existing friendly label."""
    text = (label or "").lower()
    zone: str | None = None
    if any(k in text for k in ("ext", "dehors", "outdoor")):
        zone = "exterior"
    elif any(k in text for k in (" int", "int ", "_int", "indoor")) or text.endswith(
        " int"
    ):
        zone = "interior"
    elif "int" in text and "ext" not in text:
        zone = "interior"

    height: str | None = None
    if "haut" in text or "high" in text:
        height = "high"
    elif any(k in text for k in ("mid", "middle", "moyen", "milieu")):
        height = "mid"
    elif "bas" in text or "low" in text:
        height = "low"

    room: str | None = None
    if "cuisine" in text or "kitchen" in text:
        room = "kitchen"
    elif "chambre" in text or "bedroom" in text:
        room = "bedroom"
    elif "couloir" in text or "corridor" in text or "hall" in text:
        room = "corridor"
    elif any(k in text for k in ("séjour", "sejour", "salon", "living")):
        room = "living"
    elif label.strip():
        room = "other"

    if zone is None and room and room != "other":
        zone = "interior"
    if zone is None and any(
        k in text for k in ("wc", "sdb", "bureau", "entrée", "entree")
    ):
        zone = "interior"

    return {"zone": zone, "height": height, "room": room}
