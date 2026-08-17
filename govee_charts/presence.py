"""Home Assistant person / room presence for the apartment map."""

from __future__ import annotations

import logging
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Soft aliases (same idea as categories._ALIASES) for HA room labels.
_ROOM_ALIASES = {
    "cuisine": "kitchen",
    "kitchen": "kitchen",
    "chambre": "bedroom",
    "bedroom": "bedroom",
    "couloir": "corridor",
    "corridor": "corridor",
    "entree": "corridor",
    "entrée": "corridor",
    "sejour": "living",
    "séjour": "living",
    "salon": "living",
    "living": "living",
    "living room": "living",
    "sdb": "bathroom",
    "salle de bain": "bathroom",
    "salle de bains": "bathroom",
    "bathroom": "bathroom",
    "wc": "wc",
    "toilettes": "wc",
    "other": "other",
    "autre": "other",
}

_NON_ROOM_STATES = frozenset(
    {
        "home",
        "not_home",
        "away",
        "unknown",
        "unavailable",
        "none",
        "null",
        "off",
        "on",
    }
)


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().replace("'", " ").split())


@dataclass
class PresencePerson:
    id: str
    label: str
    entity: str
    attribute: str = ""  # empty → auto (state, else attributes.room)


@dataclass
class PresenceConfig:
    enabled: bool = False
    ha_url: str = "http://127.0.0.1:8123"
    ha_token: str = ""
    ha_token_file: str = ""
    poll_seconds: float = 10.0
    # Optional explicit HA label → apartment room id
    rooms: dict[str, str] = field(default_factory=dict)
    people: tuple[PresencePerson, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> PresenceConfig:
        raw = raw or {}
        token = str(raw.get("ha_token") or "")
        token_file = str(raw.get("ha_token_file") or "").strip()
        if not token and token_file:
            path = Path(token_file).expanduser()
            try:
                token = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logger.warning("Presence HA token file unreadable (%s): %s", path, exc)

        rooms_raw = raw.get("rooms") or {}
        rooms: dict[str, str] = {}
        if isinstance(rooms_raw, dict):
            for key, value in rooms_raw.items():
                folded = _fold(str(key))
                rid = str(value or "").strip().lower()
                if folded and rid:
                    rooms[folded] = rid

        people: list[PresencePerson] = []
        # Single-entity shorthand
        entity = str(raw.get("entity") or "").strip()
        if entity:
            people.append(
                PresencePerson(
                    id=str(raw.get("id") or "me").strip() or "me",
                    label=str(raw.get("label") or "Me").strip() or "Me",
                    entity=entity,
                    attribute=str(raw.get("attribute") or "").strip(),
                )
            )
        for item in raw.get("people") or []:
            if not isinstance(item, dict):
                continue
            ent = str(item.get("entity") or "").strip()
            if not ent:
                continue
            people.append(
                PresencePerson(
                    id=str(item.get("id") or ent).strip() or ent,
                    label=str(item.get("label") or item.get("id") or ent).strip()
                    or ent,
                    entity=ent,
                    attribute=str(item.get("attribute") or "").strip(),
                )
            )

        return cls(
            enabled=bool(raw.get("enabled", False)),
            ha_url=str(raw.get("ha_url") or "http://127.0.0.1:8123").strip().rstrip("/")
            or "http://127.0.0.1:8123",
            ha_token=token,
            ha_token_file=token_file,
            poll_seconds=max(5.0, float(raw.get("poll_seconds") or 10.0)),
            rooms=rooms,
            people=tuple(people),
        )

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.ha_token and self.people)


def resolve_room_id(
    raw: str | None,
    *,
    room_map: dict[str, str],
    apartment_rooms: list[dict[str, Any]] | None = None,
) -> str | None:
    """Map an HA room label / id onto an apartment room id."""
    folded = _fold(str(raw or ""))
    if not folded or folded in _NON_ROOM_STATES:
        return None
    if folded in room_map:
        return room_map[folded]
    if folded in _ROOM_ALIASES:
        return _ROOM_ALIASES[folded]
    for room in apartment_rooms or []:
        rid = str(room.get("id") or "").strip().lower()
        label = _fold(str(room.get("label") or ""))
        if rid and (folded == rid or (label and folded == label)):
            return rid
    return None


def room_raw_from_payload(
    payload: dict[str, Any],
    *,
    attribute: str = "",
) -> str | None:
    """Pick the room string from a HA state payload."""
    attrs = payload.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    if attribute:
        value = attrs.get(attribute)
        text = str(value or "").strip()
        return text or None
    state = str(payload.get("state") or "").strip()
    if state and _fold(state) not in _NON_ROOM_STATES:
        return state
    for key in ("room", "current_room", "area"):
        value = attrs.get(key)
        text = str(value or "").strip()
        if text and _fold(text) not in _NON_ROOM_STATES:
            return text
    active = attrs.get("active_rooms")
    if isinstance(active, (list, tuple)) and active:
        text = str(active[0] or "").strip()
        if text:
            return text
    return None


class PresenceService:
    """Cached HA poller for person room presence."""

    def __init__(self, cfg: PresenceConfig) -> None:
        self.cfg = cfg
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.ha_token}",
            "Content-Type": "application/json",
        }

    async def snapshot(
        self,
        *,
        apartment_rooms: list[dict[str, Any]] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        if not self.cfg.ready:
            return {"enabled": False, "people": []}
        now = time.time()
        if (
            not force
            and self._cache is not None
            and now - self._cache_at < self.cfg.poll_seconds
        ):
            return dict(self._cache)

        try:
            import httpx
        except ImportError:
            logger.error("Presence requires httpx — pip install httpx")
            return {"enabled": True, "people": [], "error": "httpx missing"}

        people_out: list[dict[str, Any]] = []
        timeout = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for person in self.cfg.people:
                url = (
                    f"{self.cfg.ha_url}/api/states/"
                    f"{quote(person.entity, safe='')}"
                )
                try:
                    response = await client.get(url, headers=self._headers())
                except Exception as exc:
                    logger.warning(
                        "Presence request failed for %s: %s", person.entity, exc
                    )
                    people_out.append(
                        {
                            "id": person.id,
                            "label": person.label,
                            "entity": person.entity,
                            "room_raw": None,
                            "room_id": None,
                            "available": False,
                            "error": str(exc),
                        }
                    )
                    continue
                if response.status_code == 401:
                    logger.error("Presence HA rejected token (401)")
                    people_out.append(
                        {
                            "id": person.id,
                            "label": person.label,
                            "entity": person.entity,
                            "room_raw": None,
                            "room_id": None,
                            "available": False,
                            "error": "unauthorized",
                        }
                    )
                    continue
                if response.status_code == 404:
                    logger.warning("Presence entity not found: %s", person.entity)
                    people_out.append(
                        {
                            "id": person.id,
                            "label": person.label,
                            "entity": person.entity,
                            "room_raw": None,
                            "room_id": None,
                            "available": False,
                            "error": "not_found",
                        }
                    )
                    continue
                if response.status_code >= 400:
                    logger.warning(
                        "Presence HA error for %s: HTTP %s",
                        person.entity,
                        response.status_code,
                    )
                    people_out.append(
                        {
                            "id": person.id,
                            "label": person.label,
                            "entity": person.entity,
                            "room_raw": None,
                            "room_id": None,
                            "available": False,
                            "error": f"http_{response.status_code}",
                        }
                    )
                    continue
                try:
                    payload = response.json()
                except ValueError:
                    people_out.append(
                        {
                            "id": person.id,
                            "label": person.label,
                            "entity": person.entity,
                            "room_raw": None,
                            "room_id": None,
                            "available": False,
                            "error": "bad_json",
                        }
                    )
                    continue
                room_raw = room_raw_from_payload(
                    payload, attribute=person.attribute
                )
                room_id = resolve_room_id(
                    room_raw,
                    room_map=self.cfg.rooms,
                    apartment_rooms=apartment_rooms,
                )
                attrs = payload.get("attributes") or {}
                since = attrs.get("since") if isinstance(attrs, dict) else None
                people_out.append(
                    {
                        "id": person.id,
                        "label": person.label,
                        "entity": person.entity,
                        "room_raw": room_raw,
                        "room_id": room_id,
                        "confidence": (
                            attrs.get("confidence")
                            if isinstance(attrs, dict)
                            else None
                        ),
                        "since": since,
                        "ha_state": payload.get("state"),
                        "available": room_id is not None,
                        "ts": now,
                    }
                )

        out = {
            "enabled": True,
            "people": people_out,
            "polled_at": now,
        }
        self._cache = out
        self._cache_at = now
        return dict(out)
