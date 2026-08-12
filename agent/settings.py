"""
agent/settings.py
------------------
Standing, app-level toggles — different from the per-request config used
for things like one_shot (which varies call to call). These are settings
you flip occasionally, meant to be managed from the dashboard rather than
passed on every request.

Held in memory (this module's `Settings` singleton), each field starting
from an env var default or hardcoded default at startup, and changeable
live via GET/POST /settings in main.py. Persisted to settings.db
(utils/settings_store.py) so edits survive a restart — main.py's
lifespan loads settings.db into this singleton via apply_persisted()
before anything reads a setting, and POST /settings write-throughs every
change.
"""
from __future__ import annotations

import json
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


def is_valid_sync_interval_minutes(value: int) -> bool:
    # Upper bound is a sanity check, not a hard technical limit — a
    # multi-day interval would defeat the point of "poll for manual
    # calendar edits" (jobs/calendar_sync.py).
    return 1 <= value <= 1440


def is_valid_poll_interval_seconds(value: int) -> bool:
    # Sanity bounds, not hard technical limits: below 30s would hammer
    # the device's wifi radio (and battery) for no benefit; above a day
    # defeats the point of "poll for what's coming up."
    return 30 <= value <= 86400


def is_valid_recall_max_distance(value: float) -> bool:
    # Cosine distance range for the "conversations" Chroma collection is
    # [0, 2] (0 = identical, 2 = opposite); 0 itself would mean "only an
    # exact duplicate", not a useful lower bound, so exclude it.
    return 0.0 < value <= 2.0


def is_valid_recall_recency_days(value: int) -> bool:
    # Upper bound is a sanity check, not a hard technical limit.
    return 1 <= value <= 3650


def is_valid_max_history_tokens(value: int) -> bool:
    # Sanity bounds, not hard technical limits — the right value depends on
    # whatever context length the user's model was loaded with in LM Studio,
    # which this app has no way to know.
    return 500 <= value <= 200_000


def parse_mcp_servers(value: str) -> dict:
    """Parses/validates the mcp_servers JSON setting into
    {server_name: {enabled, transport, ...}}. Raises ValueError with a
    human-readable message on anything malformed, so main.py's /settings
    handler can surface it as a 422 rather than silently persisting
    something agent/tools/all_tools.py's get_mcp_tools() can't use.

    Only 'stdio' (a local subprocess) and 'streamable_http' (a URL) are
    supported — the two transports actually worth supporting for a
    single-user local setup; langchain-mcp-adapters' other options (sse,
    websocket) aren't validated here."""
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"mcp_servers must be valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("mcp_servers must be a JSON object of {server_name: config}")
    for name, config in data.items():
        if not isinstance(config, dict):
            raise ValueError(f"mcp_servers['{name}'] must be an object")
        transport = config.get("transport")
        if transport == "stdio":
            if not config.get("command"):
                raise ValueError(f"mcp_servers['{name}']: stdio transport requires 'command'")
        elif transport == "streamable_http":
            if not config.get("url"):
                raise ValueError(f"mcp_servers['{name}']: streamable_http transport requires 'url'")
        else:
            raise ValueError(f"mcp_servers['{name}']: transport must be 'stdio' or 'streamable_http'")
    return data


def _default_mcp_servers() -> str:
    """Seeded once from SEARXNG_URL at first run, same "env var default,
    dashboard source of truth after that" pattern as digest_email_to/
    gotify_url below — otherwise upgrading this app would silently drop
    web search (previously a plain tool, now the third-party
    searxng-mcp-server run over MCP) until someone notices and re-adds it
    by hand. Run via `uvx` (bundled with `uv`, which this project already
    depends on) rather than added to this project's own dependencies —
    it's a fairly heavy transitive dependency chain (MarkItDown's
    format-detection stack), fully isolated in uvx's own cache instead of
    polluting this app's venv. Exposes search_web/search_images/
    search_videos/search_news/fetch_url — see
    https://github.com/IceWreck/SearxNG-MCP-Server."""
    if not os.environ.get("SEARXNG_URL"):
        return "{}"
    return json.dumps({
        "searxng": {
            "enabled": True,
            "transport": "stdio",
            "command": "uvx",
            "args": ["searxng-mcp-server"],
            # SEARXNG_URL isn't in the MCP stdio client's default-inherited
            # env subset (HOME/LOGNAME/PATH/SHELL/TERM/USER) — passing it
            # here merges it in (mcp.client.stdio.stdio_client unions
            # server.env over those safe defaults, doesn't replace them).
            # UV_CACHE_DIR is the same story: the dockerfile sets it so uv
            # has a writable cache under the container's non-root UID (which
            # has no HOME), but that env var isn't in the safe-inherited
            # subset either, so uvx here would still fall back to the
            # unwritable default cache and die instantly ("Connection
            # closed") without also passing it through explicitly.
            "env": {
                "SEARXNG_URL": os.environ.get("SEARXNG_URL", ""),
                "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", ""),
            },
        }
    })


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

    # "HH:MM" 24-hour local time the bedtime reminder push fires (see
    # jobs/bedtime.py) — a distinct nudge from the digest, timed close to
    # it but not the same trigger. Same rescheduling/validation pattern as
    # digest_time. No env var, same reasoning as default_location above.
    bedtime: str = "21:20"

    # How often (minutes) jobs/calendar_sync.py polls the CalDAV server for
    # manually added/changed/removed calendar events — CalDAV has no push
    # mechanism, so this is the only way it notices. Same
    # rescheduling/validation pattern as digest_time/bedtime. No env var,
    # same reasoning as default_location above.
    calendar_sync_interval_minutes: int = 30

    # "HH:MM" 24-hour local time check-in prompts may start firing (see
    # jobs/checkin.py, jobs/day_start.py) — paired with `latest_checkin_time`
    # as the end of the waking-hours window. Same rescheduling/validation
    # pattern as digest_time/bedtime. No env var, same reasoning as
    # default_location above.
    wake_time: str = "07:00"

    # "HH:MM" 24-hour local time check-in prompts must stop firing by (see
    # jobs/checkin.py) — the other end of the waking-hours window,
    # deliberately independent from `bedtime` (the wind-down nudge) so the
    # two can be tuned separately. Default matches bedtime's own default so
    # upgrading is a no-op until explicitly changed. No rescheduling needed
    # (read fresh at schedule-time, not baked into a registered cron
    # trigger) — same validation pattern as digest_time/bedtime/wake_time.
    # No env var, same reasoning as default_location above.
    latest_checkin_time: str = "21:20"

    # Seconds between the ESP32-S3's deep-sleep wake cycles (see
    # main.py's POST /device/sync, jobs/device_sync.py) — returned in
    # every sync payload so the polling cadence can be retuned from the
    # dashboard without reflashing firmware. No env var, same reasoning
    # as default_location above.
    device_poll_interval_seconds: int = 300

    # Cosine distance cutoff for agent/graph.py's cross-thread conversation
    # recall (agent/memory.py's search_conversations) — a match farther
    # than this from the current query is dropped rather than injected
    # into the system prompt as "RELEVANT PAST CONTEXT". 0.8 is a rough
    # starting point, not a measured value — tune it from real distances
    # via the thread-debug dashboard page (which logs every turn's
    # recalled matches, see utils/recall_log_store.py) rather than
    # guessing blind. No env var, same reasoning as default_location above.
    recall_max_distance: float = 0.8

    # How many days back agent/graph.py's cross-thread conversation recall
    # is allowed to reach — a summary older than this is excluded from
    # search_conversations' query regardless of similarity. No env var,
    # same reasoning as default_location above.
    recall_recency_days: int = 30

    # Fallback token budget for the message history sent to the LLM every
    # turn (agent/graph.py's call_llm, via trim_messages) — the oldest
    # messages are dropped once the thread's history exceeds the budget.
    # Exists because "onboarding"/"profile_chat"/"project_<slug>" threads
    # reuse the same thread_id forever and are never swept, so their
    # history otherwise grows until it exceeds whatever context length the
    # model was loaded with in LM Studio. Only used when
    # LMSTUDIO_MANAGEMENT_URL isn't set or LM Studio's live
    # loaded_context_length can't be fetched (utils/lmstudio_client.py's
    # get_history_budget_tokens prefers the live value whenever it's
    # available) — otherwise this is a guess this app has no way to
    # verify, so the live number is trusted first. 6000 is a conservative
    # default for a small local model. No env var, same reasoning as
    # default_location above.
    max_history_tokens: int = 6000

    # Recipient address for the daily digest email (jobs/digest.py,
    # utils/mailer.py). Seeded from DIGEST_EMAIL_TO at startup so an
    # existing deployment keeps working unchanged, but editable live from
    # here afterward — same "one source of truth once configured" pattern
    # as the fields above.
    digest_email_to: str = os.environ.get("DIGEST_EMAIL_TO", "")

    # Base URL used to build check-in magic-link URLs (jobs/checkin.py's
    # _checkin_click_url) for Gotify's tap-to-open extras. Seeded from
    # PUBLIC_BASE_URL; blank is a valid "no click-through link" state, same
    # as today.
    public_base_url: str = os.environ.get("PUBLIC_BASE_URL", "")

    # Self-hosted Gotify server URL for push notifications (utils/notify.py).
    # Seeded from GOTIFY_URL; blank is a valid "not configured yet" state.
    gotify_url: str = os.environ.get("GOTIFY_URL", "")

    # Gotify app token (utils/notify.py). Seeded from GOTIFY_TOKEN. Unlike
    # every other field here, this is a real credential — GET /settings
    # never echoes it back (main.py's _current_settings() reports only
    # whether one is set), and the Settings page treats it as
    # write-only/blank-to-keep.
    gotify_token: str = os.environ.get("GOTIFY_TOKEN", "")

    # JSON-encoded {server_name: {enabled, transport, ...}} — MCP (Model
    # Context Protocol) servers whose tools get merged into the agent's
    # tool list alongside the hand-rolled ones in agent/tools/ (see
    # agent/tools/all_tools.py's get_mcp_tools(), agent/graph.py's
    # build_graph()). No env var for the setting itself — dashboard-only,
    # same reasoning as default_location above — but the *value* is
    # seeded once from SEARXNG_URL if set, see _default_mcp_servers().
    # Unlike every other field here, this one only takes effect on the
    # next app restart: the tool list is fetched once when the graph is
    # built at startup (main.py's lifespan), not re-fetched per request.
    mcp_servers: str = _default_mcp_servers()

    def zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def mcp_server_configs(self) -> dict:
        """Enabled servers from mcp_servers, with the 'enabled' key
        stripped — exactly the {name: connection} shape
        MultiServerMCPClient's constructor expects."""
        servers = parse_mcp_servers(self.mcp_servers)
        return {
            name: {k: v for k, v in config.items() if k != "enabled"}
            for name, config in servers.items()
            if config.get("enabled", True)
        }


settings = Settings()


def apply_persisted(values: dict[str, str]) -> None:
    """Overlay settings.db (utils/settings_store.py) onto the class
    defaults/env fallbacks above. Called once at startup (main.py's
    lifespan), before any field is read to build a live APScheduler
    trigger, so a persisted digest_time/bedtime/wake_time takes effect
    from the very first job registration, not just on the next edit.

    sqlite3 only stores strings, so each field is parsed back to its real
    type here — explicit per-field, not a generic loop, to match this
    module's existing style."""
    if "learning_mode" in values:
        settings.learning_mode = values["learning_mode"] == "true"
    if "default_location" in values:
        settings.default_location = values["default_location"]
    if "timezone" in values:
        settings.timezone = values["timezone"]
    if "digest_time" in values:
        settings.digest_time = values["digest_time"]
    if "bedtime" in values:
        settings.bedtime = values["bedtime"]
    if "calendar_sync_interval_minutes" in values:
        settings.calendar_sync_interval_minutes = int(values["calendar_sync_interval_minutes"])
    if "wake_time" in values:
        settings.wake_time = values["wake_time"]
    if "latest_checkin_time" in values:
        settings.latest_checkin_time = values["latest_checkin_time"]
    if "device_poll_interval_seconds" in values:
        settings.device_poll_interval_seconds = int(values["device_poll_interval_seconds"])
    if "recall_max_distance" in values:
        settings.recall_max_distance = float(values["recall_max_distance"])
    if "recall_recency_days" in values:
        settings.recall_recency_days = int(values["recall_recency_days"])
    if "max_history_tokens" in values:
        settings.max_history_tokens = int(values["max_history_tokens"])
    if "digest_email_to" in values:
        settings.digest_email_to = values["digest_email_to"]
    if "public_base_url" in values:
        settings.public_base_url = values["public_base_url"]
    if "gotify_url" in values:
        settings.gotify_url = values["gotify_url"]
    if "gotify_token" in values:
        settings.gotify_token = values["gotify_token"]
    if "mcp_servers" in values:
        settings.mcp_servers = values["mcp_servers"]
