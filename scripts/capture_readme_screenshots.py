#!/usr/bin/env python3
"""Capture English UI screenshots for the GitHub README."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
PROFILE = Path("/tmp/govee-chrome-en-shots")
PORT = 9229

SHOTS = [
    ("overview", "http://127.0.0.1:8080/overview", 1440, 1700),
    ("compare", "http://127.0.0.1:8080/compare", 1440, 2400),
    ("facades", "http://127.0.0.1:8080/facades", 1440, 2000),
    ("map", "http://127.0.0.1:8080/map", 1440, 2400),
    ("coverage", "http://127.0.0.1:8080/coverage", 1440, 1700),
    ("system", "http://127.0.0.1:8080/system", 1440, 1700),
]


def http_get(url: str):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def main() -> int:
    chrome = (
        subprocess.check_output(["bash", "-lc", "command -v chromium-browser || command -v chromium"])
        .decode()
        .strip()
    )
    if not chrome:
        print("chromium not found", file=sys.stderr)
        return 1

    if PROFILE.exists():
        subprocess.run(["rm", "-rf", str(PROFILE)], check=False)
    PROFILE.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)

    log_path = Path("/tmp/govee-chrome-shots.log")
    log_fh = open(log_path, "w")
    proc = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            "--lang=en-US",
            "--accept-lang=en-US,en",
            f"--user-data-dir={PROFILE}",
            "--window-size=1440,1200",
            "about:blank",
        ],
        stdout=log_fh,
        stderr=log_fh,
    )
    try:
        for _ in range(40):
            try:
                ver = http_get(f"http://127.0.0.1:{PORT}/json/version")
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("Chrome DevTools did not start")

        ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=30)
        msg_id = 0

        def send(method, params=None, timeout=60):
            nonlocal msg_id
            msg_id += 1
            mid = msg_id
            payload = {"id": mid, "method": method}
            if params is not None:
                payload["params"] = params
            ws.send(json.dumps(payload))
            deadline = time.time() + timeout
            while time.time() < deadline:
                data = json.loads(ws.recv())
                if data.get("id") == mid:
                    return data
            raise TimeoutError(method)

        created = send("Target.createTarget", {"url": "about:blank"})
        target_id = created["result"]["targetId"]
        attached = send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = attached["result"]["sessionId"]

        def send_session(method, params=None, timeout=90):
            nonlocal msg_id
            msg_id += 1
            mid = msg_id
            payload = {"id": mid, "method": method, "sessionId": session_id}
            if params is not None:
                payload["params"] = params
            ws.send(json.dumps(payload))
            deadline = time.time() + timeout
            while time.time() < deadline:
                data = json.loads(ws.recv())
                if data.get("id") == mid:
                    return data
            raise TimeoutError(method)

        send_session("Page.enable")
        send_session("Runtime.enable")
        send_session("Page.navigate", {"url": "http://127.0.0.1:8080/overview"})
        time.sleep(4)
        send_session(
            "Runtime.evaluate",
            {
                "expression": "localStorage.setItem('govee-charts.locale','en'); location.reload();"
            },
        )
        time.sleep(5)

        for name, url, w, h in SHOTS:
            print(f"capturing {name}…", flush=True)
            send_session(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": w,
                    "height": h,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            send_session("Page.navigate", {"url": url})
            time.sleep(6)
            send_session(
                "Runtime.evaluate",
                {
                    "expression": (
                        "localStorage.setItem('govee-charts.locale','en');"
                        "if (window.I18n) I18n.setLocale('en');"
                        "document.documentElement.lang='en';"
                    )
                },
            )
            time.sleep(4)
            res = send_session(
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True},
            )
            b64 = res.get("result", {}).get("data")
            if not b64:
                print("FAIL", name, res, file=sys.stderr)
                continue
            path = OUT / f"{name}.png"
            path.write_bytes(base64.b64decode(b64))
            print(f"OK {name} {path.stat().st_size}", flush=True)

        ws.close()
        print("done", flush=True)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_fh.close()
        subprocess.run(["rm", "-rf", str(PROFILE)], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
