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
from zoneinfo import ZoneInfo, available_timezones


def _bool_env(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def is_valid_timezone(name: str) -> bool:
    return name in available_timezones()


def is_valid_digest_time(value: str) -> bool:
    try:
        hour, minute = value.split(":")
        return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    except (ValueError, AttributeError):
        return False


class Settings:
    # When on, the agent proactively notices and records durable facts
    # about you into a canonical "About Me" note as they come up in
    # conversation — see agent/graph.py's LEARNING_ADDENDUM.
    learning_mode: bool = _bool_env("LEARNING_MODE_DEFAULT", "true")

    # Fallback location for weather tools when the user doesn't name one
    # (agent/tools/weather.py). No env var — collected via the onboarding
    # "Basics" form / Settings page, not .env, so there's one source of
    # truth for a value that's meant to be edited from the frontend.
    default_location: str = "Canberra"

    # IANA timezone name. Used for "what time is it" grounding
    # (agent/tools/general.py, utils/datetime.py), calendar day boundaries,
    # and the daily digest schedule (jobs/digest.py, main.py). Must be a
    # valid zoneinfo key — validated on write in main.py's /settings
    # handler. No env var, same reasoning as default_location above.
    timezone: str = "Australia/Canberra"

    # "HH:MM" 24-hour local time the daily digest email fires. Changing
    # this at runtime requires rescheduling the APScheduler job — handled
    # in main.py's /settings handler, not here. No env var, same reasoning
    # as default_location above.
    digest_time: str = "20:45"

    def zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()
