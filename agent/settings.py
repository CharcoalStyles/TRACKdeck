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


def is_valid_timezone(name: str) -> bool:
    return name in available_timezones()


def is_valid_clock_time(value: str) -> bool:
    try:
        hour, minute = value.split(":")
        return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    except (ValueError, AttributeError):
        return False


MONTHLY_REVIEW_TIMINGS = ("last_evening", "first_morning")


def is_valid_monthly_review_timing(value: str) -> bool:
    return value in MONTHLY_REVIEW_TIMINGS


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
    dashboard source of truth after that" pattern as
    gotify_url below — otherwise upgrading this app would silently drop
    web search (previously a plain tool, now the third-party
    searxng-mcp-server run over MCP) until someone notices and re-adds it
    by hand. Run via `uvx` (bundled with `uv`, which this project already
    depends on) rather than added to this project's own dependencies —
    it's a fairly heavy transitive dependency chain (MarkItDown's
    format-detection stack), fully isolated in uvx's own cache instead of
    polluting this app's venv. Exposes search_web/search_images/
    search_videos/search_news/fetch_url — see
    https://github.com/IceWreck/SearxNG-MCP-Server.

    `--with "fastmcp<4"` pins searxng-mcp-server's own transitive fastmcp
    dependency: it only declares `fastmcp>=2.12.4` (no upper bound), so a
    bare `uvx searxng-mcp-server` resolves whatever fastmcp is newest —
    which as of fastmcp 4.0 has moved fastmcp.tools.tool.Tool to a
    different path, so searxng-mcp-server's own import of it crashes on
    startup ("Could not load tools from MCP server 'searxng'"). Bump/drop
    this pin once searxng-mcp-server's own metadata catches up."""
    if not os.environ.get("SEARXNG_URL"):
        return "{}"
    return json.dumps({
        "searxng": {
            "enabled": True,
            "transport": "stdio",
            "command": "uvx",
            "args": ["--with", "fastmcp<4", "searxng-mcp-server"],
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
    # Fallback location for weather tools when the user doesn't name one
    # (agent/tools/weather.py). No env var — collected via the Settings
    # page, not .env, so there's one source of truth for a value that's
    # meant to be edited from the frontend.
    default_location: str = "Canberra"

    # IANA timezone name. Used for "what time is it" grounding
    # (agent/tools/general.py, utils/datetime.py), calendar day boundaries,
    # and the scheduled jobs (agent/scheduler.py). Must be a
    # valid zoneinfo key — validated on write in main.py's /settings
    # handler. No env var, same reasoning as default_location above.
    timezone: str = "Australia/Canberra"

    # "HH:MM" 24-hour local time the evening message fires (jobs/evening.py).
    # Changing this at runtime requires rescheduling the APScheduler job —
    # handled in main.py's /settings handler, not here. No env var, same
    # reasoning as default_location above.
    evening_time: str = "20:45"

    # "HH:MM" 24-hour local time the Sunday weekly review fires (jobs/reviews.py).
    weekly_review_time: str = "18:00"

    # When the monthly review fires: "last_evening" = the evening of the last
    # day of the month (covers that month), "first_morning" = the morning of
    # the 1st (covers the month just ended). Each has its own configurable time.
    monthly_review_timing: str = "last_evening"
    monthly_review_evening_time: str = "20:30"
    monthly_review_morning_time: str = "08:00"

    # Also write the evening message into Reviews/Daily/ as a daily
    # commentary file (trial: switch it off if it adds nothing).
    daily_commentary: bool = True

    # Include the today+tomorrow forecast in the morning message.
    weather_enabled: bool = True

    # Make the morning podcast (jobs/podcast.py): runs PODCAST_LEAD_MINUTES
    # before the morning message so that message can link to it. No env var,
    # same reasoning as default_location above.
    podcast_enabled: bool = True

    # "HH:MM" 24-hour local time the bedtime reminder push fires (see
    # jobs/bedtime.py) — a distinct nudge from the evening message, timed close to
    # it but not the same trigger. Same rescheduling/validation pattern as
    # evening_time. No env var, same reasoning as default_location above.
    bedtime: str = "21:20"

    # How often (minutes) jobs/calendar_sync.py polls the CalDAV server for
    # manually added/changed/removed calendar events — CalDAV has no push
    # mechanism, so this is the only way it notices. Same
    # rescheduling/validation pattern as evening_time/bedtime. No env var,
    # same reasoning as default_location above.
    calendar_sync_interval_minutes: int = 30

    # "HH:MM" 24-hour local time the morning message goes out
    # (jobs/morning.py). Seeded from wake_time on first load after the
    # three-way split (see apply_persisted), so upgrading is a no-op. Same
    # rescheduling/validation pattern as evening_time. No env var, same
    # reasoning as default_location above.
    morning_time: str = "07:00"

    # "HH:MM" 24-hour local time the day's check-in window opens
    # (jobs/checkin.py, jobs/day_start.py) — paired with `latest_checkin_time`
    # as the end of the window. Seeded from wake_time like morning_time.
    # Reschedules the day_start job.
    checkin_start_time: str = "07:00"

    # "HH:MM" 24-hour local time you get up. Only used as the default start
    # of a generated day schedule (agent/tools/planning.py); it no longer
    # drives the morning message or the check-ins.
    wake_time: str = "07:00"

    # "HH:MM" 24-hour local time check-in prompts must stop firing by (see
    # jobs/checkin.py) — the other end of the waking-hours window,
    # deliberately independent from `bedtime` (the wind-down nudge) so the
    # two can be tuned separately. Default matches bedtime's own default so
    # upgrading is a no-op until explicitly changed. No rescheduling needed
    # (read fresh at schedule-time, not baked into a registered cron
    # trigger) — same validation pattern as evening_time/bedtime/morning_time.
    # No env var, same reasoning as default_location above.
    latest_checkin_time: str = "21:20"

    # Seconds between the ESP32-S3's deep-sleep wake cycles (see
    # main.py's POST /device/sync, jobs/device_sync.py) — returned in
    # every sync payload so the polling cadence can be retuned from the
    # dashboard without reflashing firmware. No env var, same reasoning
    # as default_location above.
    device_poll_interval_seconds: int = 300

    # Vault note id to clone from when creating a new day's task-planning
    # note (utils.vault.get_or_create_planning_note, agent/tools/planning.py)
    # — point this at your own "Tasks & Time Estimates" template note.
    # Blank means new planning notes start with just empty
    # Tasks/Generated Schedule/End of Day Reflection headings. No env var,
    # same reasoning as default_location above.
    planning_template_note_id: str = ""

    # Which alert sound (utils/alert_sounds_store.py, id from GET
    # /alert-sounds) to pin on the auto-created reminders
    # generate_schedule_blocks schedules at every sprint/break boundary —
    # see agent/tools/planning.py. Blank means those reminders go out with
    # no pinned sound, same as an ordinary ad-hoc reminder (the device
    # falls back to picking one at random). No env var, same reasoning as
    # default_location above.
    chime_alert_sound_id: str = ""

    # Fallback token budget for the message history sent to the LLM every
    # turn (agent/graph.py's call_llm, via trim_messages) — the oldest
    # messages are dropped once the thread's history exceeds the budget.
    # Exists because a fixed-id thread (e.g. "day_planning:<date>") reuses
    # the same thread_id forever and is never swept, so its history
    # otherwise grows until it exceeds whatever context length the active
    # model actually has. Used when LMSTUDIO_MANAGEMENT_URL isn't set or LM
    # Studio's live loaded_context_length can't be fetched
    # (utils/lmstudio_client.py's get_history_budget_tokens); the live number
    # is trusted first since this is otherwise a
    # guess this app has no way to verify. 6000 is a conservative default
    # for a small local model. No env var, same reasoning as
    # default_location above.
    max_history_tokens: int = 6000

    # Recipient for the morning/evening/weekly/monthly messages sent by email
    # as well as Gotify (utils/mailer.py; SMTP_* env vars hold the server).
    # Blank = no email. Seeded from EMAIL_TO on first run.
    email_to: str = os.environ.get("EMAIL_TO", "")

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

    # The tool model: which model get_chat_llm() (utils/llm_client.py) sends
    # chat-completion requests to on LM Studio's OpenAI-compatible endpoint —
    # the Settings page's Models card (utils/lmstudio_client.py's
    # live catalog, sourced from LMSTUDIO_MANAGEMENT_URL) writes here when
    # you pick one. Env var seeds it, dashboard owns it after that. Also what
    # utils/lmstudio_client.py's get_loaded_context_length() looks up
    # against LM Studio's live loaded-models list. Live-editable, no
    # restart: agent/graph.py's call_llm re-binds it fresh every turn.
    lmstudio_chat_model: str = os.environ.get("LMSTUDIO_CHAT_MODEL", "")

    # LM Studio model that writes anything the user reads as prose (scheduled
    # messages, reviews, day-planning summaries; routing in agent/writer.py).
    # Empty = no split, get_writer_llm() falls back to lmstudio_chat_model.
    # Seeded from LMSTUDIO_WRITER_MODEL. Live-editable, no restart.
    lmstudio_writer_model: str = os.environ.get("LMSTUDIO_WRITER_MODEL", "")


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
    trigger, so a persisted evening_time/bedtime/morning_time takes effect
    from the very first job registration, not just on the next edit.

    sqlite3 only stores strings, so each field is parsed back to its real
    type here — explicit per-field, not a generic loop, to match this
    module's existing style."""
    if "default_location" in values:
        settings.default_location = values["default_location"]
    if "timezone" in values:
        settings.timezone = values["timezone"]
    if "evening_time" in values:
        settings.evening_time = values["evening_time"]
    if "weekly_review_time" in values:
        settings.weekly_review_time = values["weekly_review_time"]
    for name in ("monthly_review_timing", "monthly_review_evening_time", "monthly_review_morning_time"):
        if name in values:
            setattr(settings, name, values[name])
    if "daily_commentary" in values:
        settings.daily_commentary = values["daily_commentary"] == "1"
    if "podcast_enabled" in values:
        settings.podcast_enabled = values["podcast_enabled"] == "1"
    if "weather_enabled" in values:
        settings.weather_enabled = values["weather_enabled"] == "1"
    if "bedtime" in values:
        settings.bedtime = values["bedtime"]
    if "calendar_sync_interval_minutes" in values:
        settings.calendar_sync_interval_minutes = int(values["calendar_sync_interval_minutes"])
    if "wake_time" in values:
        settings.wake_time = values["wake_time"]
    # morning_time / checkin_start_time were split out of wake_time; until
    # they are saved explicitly they inherit it.
    settings.morning_time = values.get("morning_time", settings.wake_time)
    settings.checkin_start_time = values.get("checkin_start_time", settings.wake_time)
    if "latest_checkin_time" in values:
        settings.latest_checkin_time = values["latest_checkin_time"]
    if "device_poll_interval_seconds" in values:
        settings.device_poll_interval_seconds = int(values["device_poll_interval_seconds"])
    if "max_history_tokens" in values:
        settings.max_history_tokens = int(values["max_history_tokens"])
    if "planning_template_note_id" in values:
        settings.planning_template_note_id = values["planning_template_note_id"]
    if "chime_alert_sound_id" in values:
        settings.chime_alert_sound_id = values["chime_alert_sound_id"]
    if "email_to" in values:
        settings.email_to = values["email_to"]
    if "public_base_url" in values:
        settings.public_base_url = values["public_base_url"]
    if "lmstudio_chat_model" in values:
        settings.lmstudio_chat_model = values["lmstudio_chat_model"]
    if "lmstudio_writer_model" in values:
        settings.lmstudio_writer_model = values["lmstudio_writer_model"]
    if "gotify_url" in values:
        settings.gotify_url = values["gotify_url"]
    if "gotify_token" in values:
        settings.gotify_token = values["gotify_token"]
    if "mcp_servers" in values:
        settings.mcp_servers = values["mcp_servers"]
