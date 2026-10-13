"""Keep glibc heap usage low on small Linux nodes (Raspberry Pi).

Heavy requests run in worker threads (aiosqlite, ``asyncio.to_thread``); glibc
gives each thread its own malloc arena and keeps freed memory around. Limiting
arenas and calling ``malloc_trim`` periodically returns it to the OS. No-op on
macOS / non-glibc platforms.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

M_ARENA_MAX = -8
DEFAULT_ARENA_MAX = 2
DEFAULT_TRIM_INTERVAL_S = 60.0

_trim_thread: threading.Thread | None = None


def _glibc() -> ctypes.CDLL | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        # Only glibc has these symbols (musl does not).
        libc.mallopt
        libc.malloc_trim
    except (OSError, AttributeError):
        return None
    return libc


def limit_malloc_arenas(max_arenas: int = DEFAULT_ARENA_MAX) -> bool:
    """Cap glibc arenas (unless MALLOC_ARENA_MAX is already set). Call early."""
    if os.environ.get("MALLOC_ARENA_MAX"):
        return False
    libc = _glibc()
    if libc is None:
        return False
    return bool(libc.mallopt(M_ARENA_MAX, int(max_arenas)))


def start_malloc_trim(interval_s: float = DEFAULT_TRIM_INTERVAL_S) -> bool:
    """Start a daemon thread calling ``malloc_trim(0)`` every ``interval_s``."""
    global _trim_thread
    libc = _glibc()
    if libc is None or _trim_thread is not None:
        return False
    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(interval_s):
            try:
                libc.malloc_trim(0)
            except Exception:
                logger.debug("malloc_trim failed", exc_info=True)

    _trim_thread = threading.Thread(target=_loop, name="malloc-trim", daemon=True)
    _trim_thread.start()
    return True
