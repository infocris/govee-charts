"""Parse Govee Home app CSV / ZIP history exports."""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
import zipfile
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# (unix_ts floored to minute, temperature_c, humidity)
Sample = tuple[float, float, float]

# Govee FR sometimes uses NBSP / narrow NBSP between header words.
_SPACE_RE = re.compile(r"[\s\u00a0\u202f]+")
# Fallback when delimiter sniff fails: "YYYY-mm-dd HH:MM:SS  temp  humidity"
_ROW_RE = re.compile(
    r"^(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)"
    r"\s+(-?\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)\s*$"
)


def _minute_floor(ts: float) -> float:
    return float(int(ts // 60) * 60)


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _parse_timestamp(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    # Epoch seconds / ms
    try:
        val = float(text)
        if val > 1e12:
            val /= 1000.0
        if 1e9 < val < 1e11:
            return _minute_floor(val)
    except ValueError:
        pass

    cleaned = text.replace("T", " ").replace("Z", "").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    ):
        try:
            dt = datetime.strptime(cleaned[:19] if len(cleaned) >= 19 else cleaned, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_local_tz())
            return _minute_floor(dt.timestamp())
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_local_tz())
        return _minute_floor(dt.timestamp())
    except ValueError:
        return None


def _fold(text: str) -> str:
    """Lowercase ASCII fold (Température → temperature)."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _norm_header(name: str) -> str:
    folded = _fold(_SPACE_RE.sub(" ", (name or "").strip()))
    return "".join(ch if ch.isalnum() else "_" for ch in folded)


def _pick_columns(headers: list[str]) -> tuple[int, int, int, bool]:
    """
    Return (ts_idx, temp_idx, hum_idx, temp_is_fahrenheit).
    Raises ValueError if required columns are missing.
    """
    norms = [_norm_header(h) for h in headers]

    ts_idx: int | None = None
    for i, n in enumerate(norms):
        if (
            "timestamp" in n
            or "horodatage" in n
            or n in ("time", "date", "datetime", "temps")
        ):
            ts_idx = i
            break
        if "date" in n and "time" in n:
            ts_idx = i
            break
    if ts_idx is None:
        ts_idx = 0

    temp_c_idx: int | None = None
    temp_f_idx: int | None = None
    for i, n in enumerate(norms):
        if "temp" not in n:
            continue
        if "fahrenheit" in n or n.endswith("_f") or n.endswith("temp_f"):
            temp_f_idx = i
        elif "celsius" in n or n.endswith("_c") or "centigrade" in n:
            temp_c_idx = i
        elif temp_c_idx is None:
            temp_c_idx = i

    hum_idx: int | None = None
    for i, n in enumerate(norms):
        # humidity / humidite / relative_humidity / humidite_relative
        if "humid" in n or n in ("rh", "hr"):
            hum_idx = i
            break

    if temp_c_idx is None and temp_f_idx is None:
        raise ValueError("No temperature column found in CSV header")
    if hum_idx is None:
        raise ValueError("No humidity column found in CSV header")

    if temp_c_idx is not None:
        return ts_idx, temp_c_idx, hum_idx, False
    assert temp_f_idx is not None
    return ts_idx, temp_f_idx, hum_idx, True


def _detect_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _split_header_line(line: str) -> list[str]:
    """Split a header that may use comma, semicolon, tab, or multi-spaces."""
    if "\t" in line:
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) >= 3:
            return parts
    for sep in (",", ";"):
        if sep in line:
            parts = [p.strip() for p in line.split(sep) if p.strip()]
            if len(parts) >= 3:
                return parts
    # Multi-space / NBSP separated (Govee FR paste / some exports)
    parts = [p.strip() for p in _SPACE_RE.split(line) if p.strip()]
    if len(parts) >= 3:
        joined = " ".join(parts)
        m = re.search(
            r"^(?P<ts>.+?)\s+(?P<temp>Temp\S*)\s+(?P<hum>(?:Humid|Relative)\S*)\s*$",
            joined,
            flags=re.IGNORECASE,
        )
        if m:
            return [m.group("ts"), m.group("temp"), m.group("hum")]
    return parts


def _read_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, data rows) with robust delimiter handling."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], []

    sample = "\n".join(lines[:40])
    dialect = _detect_dialect(sample)
    reader = csv.reader(io.StringIO("\n".join(lines)), dialect)
    rows = [list(r) for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return [], []

    headers = [(h or "").strip() for h in rows[0]]
    body = rows[1:]

    # If sniff collapsed everything into one column, re-split.
    if len(headers) < 3:
        headers = _split_header_line(lines[0])
        body = []
        for ln in lines[1:]:
            m = _ROW_RE.match(ln)
            if m:
                body.append([m.group(1), m.group(2), m.group(3)])
                continue
            if "\t" in ln:
                parts = [p.strip() for p in ln.split("\t") if p.strip()]
            elif "," in ln:
                parts = [p.strip() for p in ln.split(",") if p.strip()]
            elif ";" in ln:
                parts = [p.strip() for p in ln.split(";") if p.strip()]
            else:
                m2 = _ROW_RE.match(ln)
                parts = list(m2.groups()) if m2 else []
            if parts:
                body.append(parts)

    return headers, body


def parse_govee_csv(text: str) -> tuple[list[Sample], int]:
    """
    Parse Govee Home CSV text (EN or FR headers).

    Returns (samples, bad_row_count). Duplicate minutes keep the last value.
    """
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    # Normalize exotic spaces used in Govee FR exports.
    text = text.replace("\u00a0", " ").replace("\u202f", " ").strip()
    if not text:
        return [], 0

    headers, body = _read_rows(text)
    if not headers or all(not (h or "").strip() for h in headers):
        raise ValueError("CSV has no header row")

    ts_idx, temp_idx, hum_idx, fahrenheit = _pick_columns(headers)
    by_minute: dict[int, Sample] = {}
    bad = 0
    for row in body:
        if not row or all(not (c or "").strip() for c in row):
            continue
        local_ts, local_temp, local_hum = ts_idx, temp_idx, hum_idx
        local_f = fahrenheit
        if max(local_ts, local_temp, local_hum) >= len(row):
            joined = " ".join(str(c) for c in row)
            m = _ROW_RE.match(joined.strip())
            if not m:
                bad += 1
                continue
            row = [m.group(1), m.group(2), m.group(3)]
            local_ts, local_temp, local_hum = 0, 1, 2
            local_f = False
        ts = _parse_timestamp(row[local_ts])
        try:
            temp = float(str(row[local_temp]).strip().replace(",", "."))
            hum = float(str(row[local_hum]).strip().replace(",", "."))
        except (TypeError, ValueError):
            bad += 1
            continue
        if ts is None:
            bad += 1
            continue
        if local_f:
            temp = (temp - 32.0) / 1.8
        if not (-40.0 <= temp <= 85.0) or not (0.0 <= hum <= 100.0):
            bad += 1
            continue
        minute = int(ts // 60)
        by_minute[minute] = (float(minute * 60), round(temp, 2), round(hum, 2))

    samples = [by_minute[m] for m in sorted(by_minute)]
    return samples, bad


def parse_upload(
    filename: str, data: bytes
) -> tuple[list[Sample], int, list[str], list[dict[str, Any]]]:
    """
    Parse a .csv or .zip upload.

    Returns (samples, bad_rows, member_filenames, per_file_stats).
    All CSV members in a ZIP are merged (last value wins on duplicate minutes).
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit")
    name = (filename or "upload.csv").lower()
    if name.endswith(".zip") or data[:2] == b"PK":
        return _parse_zip(data)
    text = data.decode("utf-8-sig", errors="replace")
    samples, bad = parse_govee_csv(text)
    label = filename or "upload.csv"
    return samples, bad, [label], [_file_stat(label, samples, bad)]


def _file_stat(name: str, samples: list[Sample], bad_rows: int) -> dict[str, Any]:
    summary = summarize_samples(samples)
    return {
        "name": name,
        "parsed": summary["parsed"],
        "bad_rows": int(bad_rows),
        "range": summary["range"],
        "temp": summary["temp"],
        "humidity": summary["humidity"],
    }


def _parse_zip(
    data: bytes,
) -> tuple[list[Sample], int, list[str], list[dict[str, Any]]]:
    files: list[str] = []
    file_stats: list[dict[str, Any]] = []
    by_minute: dict[int, Sample] = {}
    bad_total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = sorted(
            (
                info
                for info in zf.infolist()
                if not info.is_dir()
                and info.filename.lower().endswith(".csv")
                and "__macosx/" not in info.filename.lower().replace("\\", "/")
                and not info.filename.split("/")[-1].startswith("._")
            ),
            key=lambda i: i.filename.lower(),
        )
        for info in members:
            if info.file_size > MAX_UPLOAD_BYTES:
                raise ValueError(f"CSV member too large: {info.filename}")
            raw = zf.read(info)
            text = raw.decode("utf-8-sig", errors="replace")
            try:
                samples, bad = parse_govee_csv(text)
            except ValueError as exc:
                logger.warning("Skip ZIP member %s: %s", info.filename, exc)
                bad_total += 1
                file_stats.append(
                    {
                        "name": info.filename,
                        "parsed": 0,
                        "bad_rows": 1,
                        "error": str(exc),
                        "range": {"start": None, "end": None},
                        "temp": {"min": None, "max": None},
                        "humidity": {"min": None, "max": None},
                    }
                )
                continue
            files.append(info.filename)
            bad_total += bad
            file_stats.append(_file_stat(info.filename, samples, bad))
            for ts, temp, hum in samples:
                by_minute[int(ts // 60)] = (ts, temp, hum)
    if not files:
        raise ValueError("ZIP contains no parseable CSV files")
    samples = [by_minute[m] for m in sorted(by_minute)]
    return samples, bad_total, files, file_stats


def summarize_samples(samples: list[Sample]) -> dict[str, Any]:
    if not samples:
        return {
            "parsed": 0,
            "range": {"start": None, "end": None},
            "temp": {"min": None, "max": None},
            "humidity": {"min": None, "max": None},
        }
    temps = [t for _, t, _ in samples]
    hums = [h for _, _, h in samples]
    starts = [ts for ts, _, _ in samples]
    return {
        "parsed": len(samples),
        "range": {"start": min(starts), "end": max(starts) + 60.0},
        "temp": {"min": min(temps), "max": max(temps)},
        "humidity": {"min": min(hums), "max": max(hums)},
    }
