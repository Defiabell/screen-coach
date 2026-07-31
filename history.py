"""Append-only JSONL history of analyses."""
from __future__ import annotations

import json
from pathlib import Path

import config


def append_entry(path: Path, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_recent(path: Path, limit: int = config.RECENT_LIMIT) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # skip corrupt line
    out.reverse()  # most recent first
    return out[:limit]
