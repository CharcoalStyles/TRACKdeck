"""
utils/event_log.py
--------------------
Append-only JSON-lines record of what happened and where it came from:
interactions (what was said, which tools ran, the reply, and the channel),
edits and conversions of captures. One file per month, logs/events-YYYY-MM.jsonl
under EVENT_LOG_DIR (default data/logs). It is for review and scoring, so
logging must never break the thing being logged: failures are swallowed
after a warning.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.settings import settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def log_dir() -> Path:
    return Path(os.environ.get("EVENT_LOG_DIR", "data/logs"))


def log_event(kind: str, **fields: Any) -> None:
    """Append one event: {"ts": local ISO time, "kind": kind, **fields}.
    kind is "interaction", "edit" or "convert"; "source" in fields says which
    channel produced it (voice, text, device, dashboard, job)."""
    try:
        now = datetime.now(settings.zoneinfo())
        record = {"ts": now.isoformat(timespec="seconds"), "kind": kind, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        path = log_dir() / f"events-{now:%Y-%m}.jsonl"
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        logger.warning("Event log write failed (%s): %s", kind, e)


def read_events(month: str) -> list[dict]:
    """Events for one month ("YYYY-MM"), oldest first."""
    path = log_dir() / f"events-{month}.jsonl"
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out
