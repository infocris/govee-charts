"""Sensor category taxonomy and validation."""

from __future__ import annotations

from typing import Any

ZONES = ("interior", "exterior")
HEIGHTS = ("high", "mid", "low")
ROOMS = (
    "kitchen",
    "bedroom",
    "corridor",
    "living",
    "bathroom",
    "wc",
    "other",
)
CONTACT_KINDS = ("door", "window", "other")

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
    "bathroom": "Bathroom",
    "wc": "WC",
    "other": "Other",
}
CONTACT_KIND_LABELS = {
    "door": "Door",
    "window": "Window",
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
    "entrée": "corridor",
    "entree": "corridor",
    "séjour": "living",
    "sejour": "living",
    "salon": "living",
    "sdb": "bathroom",
    "salle de bain": "bathroom",
    "bathroom": "bathroom",
    "wc": "wc",
    "toilettes": "wc",
    "autre": "other",
    "porte": "door",
    "door": "door",
    "fenêtre": "window",
    "fenetre": "window",
    "window": "window",
}


def taxonomy() -> dict[str, Any]:
    return {
        "zones": [{"id": z, "label": ZONE_LABELS[z]} for z in ZONES],
        "heights": [{"id": h, "label": HEIGHT_LABELS[h]} for h in HEIGHTS],
        "rooms": [{"id": r, "label": ROOM_LABELS[r]} for r in ROOMS],
        "contact_kinds": [
            {"id": k, "label": CONTACT_KIND_LABELS[k]} for k in CONTACT_KINDS
        ],
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


def _norm_height_cm(value: Any) -> float | None:
    """Sensor mounting height above floor in centimetres (0–600), or unset."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text in ("none", "null", "unset", "-"):
            return None
        try:
            cm = float(text.replace(",", "."))
        except ValueError as exc:
            raise ValueError(
                f"Invalid height_cm {value!r}; expected a number in cm"
            ) from exc
    else:
        try:
            cm = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid height_cm {value!r}; expected a number in cm"
            ) from exc
    if cm < 0 or cm > 600:
        raise ValueError(
            f"Invalid height_cm {value!r}; expected 0–600 cm above floor"
        )
    return round(cm, 1)


def normalize_patch(
    *,
    zone: Any = ...,
    height: Any = ...,
    height_cm: Any = ...,
    room: Any = ...,
) -> dict[str, Any]:
    """Build a partial update dict. Ellipsis means 'field not provided'."""
    out: dict[str, Any] = {}
    if zone is not ...:
        out["zone"] = _norm_choice(zone, ZONES)
    if height is not ...:
        out["height"] = _norm_choice(height, HEIGHTS)
    if height_cm is not ...:
        out["height_cm"] = _norm_height_cm(height_cm)
    if room is not ...:
        out["room"] = _norm_choice(room, ROOMS)
    return out


def normalize_door_patch(
    *,
    room: Any = ...,
    kind: Any = ...,
    name: Any = ...,
) -> dict[str, str | None]:
    """Partial update for door/window contact metadata."""
    out: dict[str, str | None] = {}
    if room is not ...:
        out["room"] = _norm_choice(room, ROOMS)
    if kind is not ...:
        out["kind"] = _norm_choice(kind, CONTACT_KINDS)
    if name is not ...:
        text = None if name is None else str(name).strip()
        out["name"] = text or None
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
    elif any(k in text for k in ("sdb", "salle de bain", "bathroom", "bain")):
        room = "bathroom"
    elif text.strip() in ("wc",) or "toilettes" in text or text.endswith(" wc"):
        room = "wc"
    elif any(
        k in text for k in ("couloir", "corridor", "hall", "entrée", "entree")
    ):
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


def infer_contact_from_label(label: str) -> dict[str, str | None]:
    """Infer contact kind + room from a door/window sensor name."""
    text = (label or "").lower()
    kind: str | None = None
    if any(k in text for k in ("fenêtre", "fenetre", "window", "baie")):
        kind = "window"
    elif any(k in text for k in ("porte", "door", "portail")):
        kind = "door"
    elif label.strip():
        kind = "other"

    room: str | None = None
    if "cuisine" in text or "kitchen" in text:
        room = "kitchen"
    elif "chambre" in text or "bedroom" in text:
        room = "bedroom"
    elif any(k in text for k in ("sdb", "salle de bain", "bathroom", "bain")):
        room = "bathroom"
    elif "toilettes" in text or text.strip() in ("wc",) or " wc" in text:
        room = "wc"
    elif any(
        k in text for k in ("couloir", "corridor", "hall", "entrée", "entree")
    ):
        room = "corridor"
    elif any(k in text for k in ("séjour", "sejour", "salon", "living")):
        room = "living"
    elif "arrière" in text or "arriere" in text:
        # e.g. "Fenêtre arrière" → bedroom in this apartment
        room = "bedroom"

    return {"kind": kind, "room": room}
