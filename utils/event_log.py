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

import contextvars
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.settings import settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """26-char sortable id: 48-bit millisecond timestamp + 80 random bits."""
    n = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(n >> shift) & 31] for shift in range(125, -1, -5))


@dataclass
class Interaction:
    """What the current run_agent turn has produced so far. Held in a
    contextvar so tools can say what they created without knowing about the
    log; the object is mutable, so copies of the context made for worker
    threads all see the same lists."""
    id: str
    artifacts: list[dict] = field(default_factory=list)
    reply_route: str | None = None


_current: contextvars.ContextVar[Interaction | None] = contextvars.ContextVar("interaction", default=None)


def begin_interaction() -> Interaction:
    ix = Interaction(id=new_ulid())
    _current.set(ix)
    return ix


def end_interaction() -> None:
    _current.set(None)


def current_interaction_id() -> str | None:
    ix = _current.get()
    return ix.id if ix else None


def note_reply_route(route: str) -> None:
    """Which path wrote the final reply: template, tool_model, writer or fallback."""
    ix = _current.get()
    if ix:
        ix.reply_route = route


def note_artifact(artifact_type: str, artifact_id: str, op: str, *, log: bool = True, **fields: Any) -> None:
    """Record that this turn created/changed/deleted something (type is
    "calendar_event", "reminder" or "capture"). It joins the interaction's
    `artifacts` list and, with log=True, becomes its own "artifact" event so
    a later edit can find its origin with origin_of()."""
    ix = _current.get()
    entry = {"type": artifact_type, "id": artifact_id, "op": op, **fields}
    if ix:
        ix.artifacts.append(entry)
    if log:
        log_event("artifact", origin_interaction_id=ix.id if ix else None, **entry)


def log_dir() -> Path:
    return Path(os.environ.get("EVENT_LOG_DIR", "data/logs"))


def log_event(kind: str, **fields: Any) -> None:
    """Append one event: {"ts": local ISO time, "kind": kind, **fields}.
    kind is "interaction", "capture", "artifact", "edit" or "convert";
    "source" in fields says which channel produced it (voice, text, device,
    dashboard, job)."""
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


def origin_of(artifact_type: str, artifact_id: str) -> str | None:
    """The interaction that created this calendar event / reminder / capture,
    or None (made outside the assistant, or before logging)."""
    d = log_dir()
    if not d.exists():
        return None
    for path in sorted(d.glob("events-*.jsonl"), reverse=True):
        for ev in reversed(read_events(path.stem.removeprefix("events-"))):
            is_artifact = ev.get("kind") == "artifact" and ev.get("type") == artifact_type
            is_capture = ev.get("kind") == "capture" and artifact_type == "capture"
            same_id = ev.get("id") == artifact_id or (is_capture and ev.get("capture_id") == artifact_id)
            if (is_artifact and ev.get("op") == "create" or is_capture) and same_id:
                return ev.get("origin_interaction_id")
    return None
