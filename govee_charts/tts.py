"""edge-tts helpers for alert speech (browser-tts skill policy)."""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_VOICES = {
    "fr": "fr-FR-DeniseNeural",
    "en": "en-US-JennyNeural",
}
MAX_CHARS = 1800
# Special voice id: synthesize + play on the Home TTS edge server (speakers).
HOME_TTS_VOICE_ID = "home-tts"

_voices_cache: list[dict[str, str]] | None = None


def default_voice_for_lang(lang: str) -> str:
    key = (lang or "fr").strip().lower().split("-")[0] or "fr"
    return DEFAULT_VOICES.get(key, DEFAULT_VOICES["en"])


def _clean_text(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("empty text")
    if len(cleaned) > MAX_CHARS:
        cleaned = cleaned[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return cleaned


async def speak_via_home(
    base_url: str,
    text: str,
    *,
    lang: str = "fr",
    app: str = "govee-charts",
    channel: str = "alerts",
    return_audio: bool = False,
) -> dict[str, Any]:
    """POST to Home TTS edge `/speak` (broadcast sinks).

    Home TTS is a sound output — callers do not play MP3. Sinks are selected
    in the Bridge UI Outputs. return_audio is debug-only.
    """
    cleaned = _clean_text(text)
    root = (base_url or "").strip().rstrip("/")
    if not root:
        raise RuntimeError("home-tts URL is not configured")

    lang_key = (lang or "fr").strip().lower().split("-")[0] or "fr"
    payload = {
        "text": cleaned,
        "lang": lang_key,
        "app": (app or "govee-charts").strip() or "govee-charts",
        "channel": (channel or "alerts").strip() or "alerts",
        "return_audio": bool(return_audio),
    }
    url = f"{root}/speak"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
            res = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("home-tts speak failed: %s", exc)
        raise RuntimeError(f"home-tts unreachable: {exc}") from exc

    if res.status_code >= 400:
        detail = (res.text or "").strip()[:300]
        raise RuntimeError(
            f"home-tts HTTP {res.status_code}" + (f": {detail}" if detail else "")
        )

    try:
        data = res.json()
    except Exception as exc:
        raise RuntimeError("home-tts returned invalid JSON") from exc

    if not data.get("ok", True):
        raise RuntimeError(str(data.get("error") or "home-tts speak failed"))

    out: dict[str, Any] = {
        "ok": True,
        "engine": HOME_TTS_VOICE_ID,
        "voice": data.get("voice") or HOME_TTS_VOICE_ID,
        "text": cleaned,
        "played": data.get("played"),
        "play_error": data.get("play_error"),
        "app": data.get("app"),
        "channel": data.get("channel"),
        "speak_id": data.get("speak_id"),
        "destinations": data.get("destinations") or [],
    }
    if data.get("audio_base64"):
        out["mime"] = data.get("mime") or "audio/mpeg"
        out["audio_base64"] = data["audio_base64"]
    return out



async def list_edge_voices(lang: str = "fr") -> list[dict[str, str]]:
    """Cached edge-tts voices filtered by locale prefix."""
    global _voices_cache
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed") from exc

    if _voices_cache is None:
        try:
            raw = await edge_tts.list_voices()
        except Exception:
            logger.exception("edge-tts list_voices failed")
            raise
        out: list[dict[str, str]] = []
        for v in raw:
            short = str(v.get("ShortName") or "").strip()
            locale = str(v.get("Locale") or "").strip()
            if not short or not locale:
                continue
            out.append(
                {
                    "id": short,
                    "locale": locale,
                    "gender": str(v.get("Gender") or ""),
                    "name": str(v.get("FriendlyName") or short),
                }
            )
        out.sort(key=lambda x: (x["locale"], x["name"]))
        _voices_cache = out

    prefix = (lang or "fr").strip().lower() or "fr"
    if prefix == "*":
        return list(_voices_cache)
    return [
        v
        for v in _voices_cache
        if v["locale"].lower().startswith(prefix)
    ]


async def synthesize(text: str, voice: str | None = None) -> dict[str, Any]:
    """Return {mime, audio_base64, voice, text} for edge-tts audio."""
    cleaned = _clean_text(text)

    voice_id = (voice or "").strip() or default_voice_for_lang("fr")
    if voice_id == HOME_TTS_VOICE_ID:
        raise ValueError("home-tts voice must use speak_via_home")
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed") from exc

    known = {v["id"] for v in await list_edge_voices("*")}
    if voice_id not in known:
        # Soft fallback: keep locale prefix if possible.
        lang = voice_id.split("-")[0].lower() if "-" in voice_id else "fr"
        voice_id = default_voice_for_lang(lang)

    communicate = edge_tts.Communicate(cleaned, voice_id)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    data = buf.getvalue()
    if not data:
        raise RuntimeError("empty audio")
    return {
        "ok": True,
        "mime": "audio/mpeg",
        "audio_base64": base64.b64encode(data).decode("ascii"),
        "voice": voice_id,
        "text": cleaned,
    }
