"""
agent/settings.py
------------------
Standing, app-level toggles — different from the per-request config used
for things like one_shot (which varies call to call). These are settings
you flip occasionally, meant to be managed from the dashboard rather than
passed on every request.

Held in memory only, not persisted to disk — each one starts from an env
var default at startup, and can be changed live via GET/POST /settings
in main.py.
"""
from __future__ import annotations

import os


def _bool_env(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # When on, the agent proactively notices and records durable facts
    # about you into a canonical "About Me" note as they come up in
    # conversation — see agent/graph.py's LEARNING_ADDENDUM.
    learning_mode: bool = _bool_env("LEARNING_MODE_DEFAULT", "true")


settings = Settings()
