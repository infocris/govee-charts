#!/usr/bin/env python3
"""Export Cursor agent transcripts for this workspace into docs/chat-history/."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = Path.home() / ".cursor/projects/home-christophe-govee-charts/agent-transcripts"
OUT = ROOT / "docs" / "chat-history"

MAP_CHAT_MARKERS = (
    "You are advising on apartment climate for the Govee Charts Map view",
)


def extract_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def clean_user_query(text: str) -> str:
    m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", text, re.S)
    if m:
        return m.group(1).strip()
    text = re.sub(r"<timestamp>.*?</timestamp>\s*", "", text, flags=re.S)
    text = re.sub(r"</?user_query>", "", text)
    return text.strip()


def clean_assistant(text: str) -> str:
    if len(text) > 20000:
        return text[:20000] + "\n\n…[truncated]…"
    return text


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()

    index: list[dict] = []
    if not TRANSCRIPTS.is_dir():
        raise SystemExit(f"transcripts not found: {TRANSCRIPTS}")

    for d in sorted(TRANSCRIPTS.iterdir(), key=lambda p: p.stat().st_mtime):
        if not d.is_dir():
            continue
        files = list(d.glob("*.jsonl"))
        if not files:
            continue
        f = files[0]
        turns: list[tuple[str, str]] = []
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = ev.get("role")
                msg = ev.get("message") or {}
                content = extract_text(msg.get("content") if isinstance(msg, dict) else None)
                if role in ("user", "assistant") and content.strip():
                    turns.append((role, content))
        if not turns:
            continue
        joined = "\n".join(c for _, c in turns)
        if any(m in joined for m in MAP_CHAT_MARKERS):
            continue
        n_user = sum(1 for r, _ in turns if r == "user")
        if f.stat().st_size < 3000 and n_user <= 1:
            first = clean_user_query(turns[0][1])
            if len(first) < 40:
                continue

        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        md_path = OUT / f"{mtime.strftime('%Y-%m-%d')}_{d.name[:8]}.md"
        lines = [
            f"# Chat {d.name}",
            "",
            f"- **Date:** {mtime.isoformat(timespec='seconds')}",
            f"- **Source:** Cursor agent transcript `{d.name}`",
            f"- **Turns:** {len(turns)} ({n_user} user)",
            "",
            "---",
            "",
        ]
        for role, content in turns:
            if role == "user":
                lines += ["## User", "", clean_user_query(content), ""]
            else:
                body = clean_assistant(content)
                if body.strip():
                    lines += ["## Assistant", "", body, ""]
        md_path.write_text("\n".join(lines), encoding="utf-8")
        preview = " ".join(clean_user_query(turns[0][1]).split())[:110]
        index.append(
            {
                "date": mtime.strftime("%Y-%m-%d"),
                "file": md_path.name,
                "preview": preview.replace("|", "\\|"),
            }
        )

    idx = [
        "# Cursor agent chat history (project development)",
        "",
        "Extracted from local Cursor **agent transcripts** for the `govee-charts` workspace.",
        "These conversations drove most of the product work.",
        "",
        "Map-view **Ask Cursor** Q&A sessions live in `data/map_chat.db` (not here).",
        "",
        "Re-export: `venv/bin/python scripts/export_agent_chat_history.py`",
        "",
        "| Date | File | Preview |",
        "|---|---|---|",
    ]
    for item in index:
        idx.append(f"| {item['date']} | [{item['file']}]({item['file']}) | {item['preview']} |")
    idx.append("")
    (OUT / "README.md").write_text("\n".join(idx), encoding="utf-8")
    print(f"Wrote {len(index)} chats → {OUT}")


if __name__ == "__main__":
    main()
