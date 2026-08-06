"""Disposable inbox via myagentinbox.com (no signup; 24h TTL).

Used to receive Govee Home CSV/ZIP export emails for Coverage import.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://myagentinbox.com"
PROVIDER = "myagentinbox"
STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "mail_inbox.json"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_CSV_EXTS = (".csv", ".zip")
_CODE_RE = re.compile(
    r"(?i)(?:(?:verification|verify|code|otp|pin|验证码)\s*[:：#]?\s*)?"
    r"(?<![A-Za-z0-9])(\d{4,8})(?![A-Za-z0-9])"
)
# Govee wraps OTPs in quotes inside HTML: ..."4028"...
_QUOTED_CODE_RE = re.compile(r'["“”\'«»]\s*(\d{4,8})\s*["“”\'«»]')
_VERIFY_HINT_RE = re.compile(
    r"(?i)(code|verify|verification|otp|pin|vérif|saisir|验证)"
)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head"):
            self._skip += 1
            return
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "td"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1
            return
        if tag in ("p", "div", "tr", "li", "h1", "h2", "h3"):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        joined = re.sub(r"[ \t\f\v]+", " ", joined)
        joined = re.sub(r"\n{2,}", "\n", joined)
        return joined.strip()


def html_to_text(html: str) -> str:
    """Strip HTML email markup to readable plain text."""
    raw = (html or "").strip()
    if not raw:
        return ""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw)
    return parser.text()


def message_plain_text(*, text: str = "", html: str = "", preview: str = "") -> str:
    """Best available plain body for display + code extraction."""
    plain = (text or "").strip()
    if plain:
        return plain
    from_html = html_to_text(html)
    if from_html:
        return from_html
    return (preview or "").strip()


def extract_verification_codes(text: str) -> list[str]:
    """Best-effort OTP / verification codes from plain email text."""
    raw = (text or "").strip()
    if not raw:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def _add(code: str) -> None:
        if code and code not in seen:
            seen.add(code)
            found.append(code)

    # Quoted OTPs (Govee FR: …code… "4028").
    for match in _QUOTED_CODE_RE.finditer(raw):
        code = match.group(1)
        window = raw[max(0, match.start() - 180) : match.end() + 40]
        if _VERIFY_HINT_RE.search(window) or len(code) in (4, 5, 6):
            _add(code)

    for match in _CODE_RE.finditer(raw):
        code = match.group(1)
        around = raw[max(0, match.start() - 160) : match.end() + 24]
        labeled = bool(_VERIFY_HINT_RE.search(around))
        if len(code) == 4 and code.startswith(("19", "20")) and not labeled:
            continue
        if not labeled and len(code) not in (4, 5, 6, 7, 8):
            continue
        if not labeled and len(code) == 4 and not _QUOTED_CODE_RE.search(
            raw[max(0, match.start() - 2) : match.end() + 2]
        ):
            # Bare unlabeled 4-digit only if quoted nearby already handled above.
            continue
        _add(code)

    return found


def is_importable_filename(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in _CSV_EXTS)


class MailInboxError(RuntimeError):
    """Upstream disposable-inbox failure."""


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "error" in payload and payload["error"]:
        err = payload["error"]
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("code") or err)
        else:
            msg = str(err)
        raise MailInboxError(msg)
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _enc(address: str) -> str:
    return quote(address.strip(), safe="@")


def load_state(path: Path | None = None) -> dict[str, Any] | None:
    target = path or STATE_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("Could not read mail inbox state: %s", exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    address = str(data.get("address") or "").strip()
    if not address or "@" not in address:
        return None
    return {
        "address": address,
        "created_at": data.get("created_at"),
        "expires_in": data.get("expires_in"),
        "provider": str(data.get("provider") or PROVIDER),
    }


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = path or STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "address": str(state["address"]).strip(),
        "created_at": state.get("created_at"),
        "expires_in": state.get("expires_in"),
        "provider": str(state.get("provider") or PROVIDER),
    }
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def clear_state(path: Path | None = None) -> None:
    target = path or STATE_PATH
    try:
        target.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not clear mail inbox state: %s", exc)


async def create_inbox(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Create a new disposable inbox (24h TTL)."""
    owns = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        res = await http.post(f"{BASE_URL}/api/inboxes")
        if res.status_code == 429:
            raise MailInboxError("Rate limited creating inbox — try again in a minute")
        if res.status_code >= 400:
            raise MailInboxError(f"Create inbox failed: HTTP {res.status_code}")
        data = _unwrap(res.json())
        address = str((data or {}).get("address") or "").strip()
        if not address:
            raise MailInboxError("Create inbox returned no address")
        return {
            "address": address,
            "created_at": (data or {}).get("created_at"),
            "expires_in": (data or {}).get("expires_in") or "24h",
            "provider": PROVIDER,
        }
    finally:
        if owns:
            await http.aclose()


async def get_inbox(
    address: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Confirm an inbox still exists."""
    addr = address.strip()
    if not addr or "@" not in addr:
        raise MailInboxError("Invalid inbox address")
    owns = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        res = await http.get(f"{BASE_URL}/api/inboxes/{_enc(addr)}")
        if res.status_code == 404:
            raise MailInboxError("Inbox not found or expired")
        if res.status_code == 429:
            raise MailInboxError("Rate limited reading inbox — try again shortly")
        if res.status_code >= 400:
            raise MailInboxError(f"Get inbox failed: HTTP {res.status_code}")
        data = _unwrap(res.json())
        return {
            "address": str((data or {}).get("address") or addr),
            "created_at": (data or {}).get("created_at"),
            "provider": PROVIDER,
        }
    finally:
        if owns:
            await http.aclose()


async def list_messages(
    address: str, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    addr = address.strip()
    owns = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        res = await http.get(f"{BASE_URL}/api/inboxes/{_enc(addr)}/messages")
        if res.status_code == 404:
            raise MailInboxError("Inbox not found or expired")
        if res.status_code == 429:
            raise MailInboxError("Rate limited listing messages — try again shortly")
        if res.status_code >= 400:
            raise MailInboxError(f"List messages failed: HTTP {res.status_code}")
        data = _unwrap(res.json())
        if not isinstance(data, list):
            return []
        out: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": str(row.get("id") or ""),
                    "from": str(row.get("from") or ""),
                    "subject": str(row.get("subject") or ""),
                    "preview": str(row.get("preview") or ""),
                    "received_at": row.get("received_at"),
                    "has_attachments": bool(row.get("has_attachments")),
                }
            )
        return [m for m in out if m["id"]]
    finally:
        if owns:
            await http.aclose()


async def get_message(
    address: str, message_id: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    addr = address.strip()
    mid = message_id.strip()
    owns = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        res = await http.get(f"{BASE_URL}/api/inboxes/{_enc(addr)}/messages/{quote(mid)}")
        if res.status_code == 404:
            raise MailInboxError("Message not found or expired")
        if res.status_code == 429:
            raise MailInboxError("Rate limited reading message — try again shortly")
        if res.status_code >= 400:
            raise MailInboxError(f"Get message failed: HTTP {res.status_code}")
        data = _unwrap(res.json()) or {}
        attachments = []
        for att in data.get("attachments") or []:
            if not isinstance(att, dict):
                continue
            filename = str(att.get("filename") or "").strip()
            if not filename:
                continue
            attachments.append(
                {
                    "filename": filename,
                    "content_type": str(att.get("content_type") or ""),
                    "size": int(att.get("size") or 0),
                }
            )
        return {
            "id": str(data.get("id") or mid),
            "from": str(data.get("from") or ""),
            "subject": str(data.get("subject") or ""),
            "text": str(data.get("text") or ""),
            "html": str(data.get("html") or ""),
            "received_at": data.get("received_at"),
            "attachments": attachments,
        }
    finally:
        if owns:
            await http.aclose()


async def download_attachment(
    address: str,
    message_id: str,
    filename: str,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    addr = address.strip()
    mid = message_id.strip()
    name = filename.strip()
    owns = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        url = (
            f"{BASE_URL}/api/inboxes/{_enc(addr)}/messages/{quote(mid)}"
            f"/attachments/{quote(name)}"
        )
        res = await http.get(url)
        if res.status_code == 404:
            raise MailInboxError(f"Attachment not found: {name}")
        if res.status_code == 429:
            raise MailInboxError("Rate limited downloading attachment")
        if res.status_code >= 400:
            raise MailInboxError(f"Download failed: HTTP {res.status_code}")
        data = res.content or b""
        if not data:
            raise MailInboxError(f"Empty attachment: {name}")
        return data
    finally:
        if owns:
            await http.aclose()


async def fetch_csv_attachments(
    address: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """List inbox messages, surface verification codes, download CSV/ZIP attachments."""
    addr = address.strip()
    owns = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        await get_inbox(addr, client=http)
        summaries = await list_messages(addr, client=http)
        messages_out: list[dict[str, Any]] = []
        attachment_count = 0
        codes_all: list[str] = []
        codes_seen: set[str] = set()
        for summary in summaries:
            mid = summary["id"]
            detail = await get_message(addr, mid, client=http)
            text = message_plain_text(
                text=str(detail.get("text") or ""),
                html=str(detail.get("html") or ""),
                preview=str(summary.get("preview") or ""),
            )
            preview = str(summary.get("preview") or "").strip()
            codes = extract_verification_codes(text)
            for code in codes:
                if code not in codes_seen:
                    codes_seen.add(code)
                    codes_all.append(code)
            files: list[dict[str, Any]] = []
            for att in detail.get("attachments") or []:
                filename = str(att.get("filename") or "")
                if not is_importable_filename(filename):
                    continue
                raw = await download_attachment(addr, mid, filename, client=http)
                files.append(
                    {
                        "filename": filename,
                        "content_type": att.get("content_type")
                        or "application/octet-stream",
                        "size": len(raw),
                        "content_base64": base64.b64encode(raw).decode("ascii"),
                    }
                )
                attachment_count += 1
            messages_out.append(
                {
                    "id": mid,
                    "from": detail.get("from") or summary.get("from") or "",
                    "subject": detail.get("subject") or summary.get("subject") or "",
                    "text": text,
                    "preview": preview or (text[:200] if text else ""),
                    "verification_codes": codes,
                    "received_at": detail.get("received_at")
                    or summary.get("received_at"),
                    "attachments": files,
                }
            )
        return {
            "address": addr,
            "provider": PROVIDER,
            "messages": messages_out,
            "attachment_count": attachment_count,
            "verification_codes": codes_all,
        }
    finally:
        if owns:
            await http.aclose()
