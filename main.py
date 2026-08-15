"""
Personal Assistant — FastAPI + LangGraph
----------------------------------------
"""
import os
import asyncio
import logging
import mimetypes
import time
from contextlib import asynccontextmanager
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.date import DateTrigger
from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ValidationError, model_validator
from starlette.middleware.sessions import SessionMiddleware

# Load .env before anything that reads os.environ (i.e. before agent imports)
load_dotenv()

from utils.logging import configure_logging

# Configured before any other app module is imported, so every logger
# created at import time (module-level `logging.getLogger(__name__)`
# calls) already has the right level/handler via the root logger.
configure_logging()

logger = logging.getLogger(__name__)

# .env.example documents these same strings as the sample values — so an
# unedited value isn't just "unset", it's a real, publicly-known
# credential/key. Refuse to start rather than silently running with any
# of them.
_PLACEHOLDER_API_TOKEN = "YOUR_SUPER_SECRET_SECURE_TOKEN"
_PLACEHOLDER_DASHBOARD_PASSWORD = "CHANGE_ME_DASHBOARD_PASSWORD"
_PLACEHOLDER_SESSION_SECRET_KEY = "CHANGE_ME_SESSION_SECRET_KEY"
if os.environ.get("API_TOKEN") == _PLACEHOLDER_API_TOKEN:
    raise RuntimeError(
        "API_TOKEN is still set to the placeholder value from .env.example. "
        "Set it to a real, private secret before starting the app."
    )
if os.environ.get("DASHBOARD_PASSWORD") == _PLACEHOLDER_DASHBOARD_PASSWORD:
    raise RuntimeError(
        "DASHBOARD_PASSWORD is still set to the placeholder value from .env.example. "
        "Set it to a real, private password before starting the app."
    )
if os.environ.get("SESSION_SECRET_KEY") in (None, _PLACEHOLDER_SESSION_SECRET_KEY):
    raise RuntimeError(
        "SESSION_SECRET_KEY is unset or still the placeholder value from .env.example. "
        "Set it to a real, private random string before starting the app."
    )

import auth
from agent.graph import build_graph
from agent.memory import MemoryStore, make_chroma_client, make_embedding_function
from agent.runtime import (
    app_state,
    clear_thread,
    create_new_thread,
    get_agent_activity,
    get_thread_debug,
    get_thread_messages,
    get_thread_size,
    list_checkpoint_thread_ids,
    list_threads,
    rehydrate_threads_from_checkpoints,
    run_agent,
)
from agent.scheduler import (
    bedtime_trigger,
    calendar_sync_trigger,
    digest_trigger,
    scheduler,
    wake_trigger,
)
from agent.settings import (
    apply_persisted,
    is_valid_digest_time,
    is_valid_poll_interval_seconds,
    is_valid_max_history_tokens,
    is_valid_recall_max_distance,
    is_valid_recall_recency_days,
    is_valid_sync_interval_minutes,
    is_valid_timezone,
    parse_mcp_servers,
    settings,
)
from agent.tools.all_tools import get_mcp_tools
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from jobs import activity_log as activity_log_jobs
from jobs import checkin as checkin_jobs
from jobs.bedtime import send_bedtime_reminder
from jobs.calendar_sync import sync_calendar_reminders
from jobs.day_start import start_of_day_setup
from jobs.device_sync import build_sync_payload
from jobs.digest import send_daily_digest
from jobs.reminders import create_test_reminder, fire_reminder

from agent.tools.general import resolve_location
from agent.vault_watcher import reconcile_vault, watch_vault
from utils import (
    activity_log_store,
    alert_sounds_store,
    checkins_store,
    device_errors_store,
    device_state,
    onboarding_state,
    recall_log_store,
    reminders_store,
    settings_store,
    vault,
)
from utils.caldav_client import ensure_collection_exists
from utils.datetime import parse_local_datetime
from utils.mailer import send_email
from utils.notify import notify_device_error, notify_error, send_gotify

from voice import router as voice_router
from routes.synth import router as synth_router
from routes.transcribe import router as transcribe_router
from routes.calendar_proxy import router as calendar_proxy_router
from routes.alert_sounds import router as alert_sounds_router

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Every store below (settings.db, memory.db, chroma_db, ...) resolves
    # its path as "data/<name>" relative to cwd — local dev and Docker
    # alike (see docker-compose.yml's matching bind-mount targets) — so
    # this has to exist before the very first one connects.
    Path("data").mkdir(exist_ok=True)

    # Load settings.db before anything below reads a setting — in
    # particular before the daily_digest/bedtime_reminder jobs are
    # registered further down, since digest_trigger()/bedtime_trigger()
    # bake settings.digest_time/bedtime in at add_job() time.
    await asyncio.to_thread(settings_store.init_db)
    apply_persisted(await asyncio.to_thread(settings_store.load_all))

    chroma_client = make_chroma_client()
    embedding_fn = make_embedding_function()
    app_state.memory = MemoryStore(chroma_client, embedding_fn)

    vault.ensure_vault_dirs()

    # Best-effort: creates the calendar collection at CALDAV_URL if it
    # doesn't exist yet (fresh Radicale instance, or a first-run against
    # any other compliant CalDAV server), so there's no separate manual
    # "create the calendar" step. Never blocks startup — some servers may
    # not support bare MKCALENDAR, in which case the collection still needs
    # to be created manually as before, but that's opt-in on failure, not
    # fatal.
    caldav_setup = await asyncio.to_thread(ensure_collection_exists)
    if not caldav_setup["success"]:
        logger.warning(
            "Could not auto-create the CalDAV collection at startup (status %s): %s. "
            "If this is a fresh calendar, create it manually via your CalDAV server's "
            "own tools before the agent's calendar tools will work.",
            caldav_setup.get("status_code"),
            caldav_setup.get("error"),
        )

    # Fetched once at startup, not per-request — settings.mcp_servers
    # changes need a restart to take effect (see its docstring in
    # agent/settings.py). Best-effort per server (get_mcp_tools() isolates
    # failures), so one misbehaving MCP server never blocks the app from
    # starting.
    mcp_tools = await get_mcp_tools()
    if mcp_tools:
        logger.info("Loaded %d tool(s) from MCP servers: %s", len(mcp_tools), [t.name for t in mcp_tools])

    async with AsyncSqliteSaver.from_conn_string("data/memory.db") as checkpointer:
        app_state.graph = build_graph(checkpointer, app_state.memory, mcp_tools=mcp_tools)

        # Dashboard sidebar (GET /threads) is sourced from app_state.threads/
        # keywords, which are in-process dicts wiped by every restart even
        # though memory.db itself is untouched — restore same-day threads
        # so the chat page doesn't appear empty after a docker cycle.
        restored = await rehydrate_threads_from_checkpoints()
        if restored:
            logger.info("Rehydrated %d thread(s) from memory.db after restart.", restored)

        scheduler.add_job(
            send_daily_digest,
            trigger=digest_trigger(),
            args=[app_state.memory],
            id="daily_digest",
            replace_existing=True,
        )
        scheduler.add_job(
            send_bedtime_reminder,
            trigger=bedtime_trigger(),
            id="bedtime_reminder",
            replace_existing=True,
        )
        # next_run_time=now: also runs once immediately at startup, so an
        # event added/changed/removed manually (directly in a calendar app, not through
        # the agent) while the app was down gets picked up right away
        # rather than waiting up to settings.calendar_sync_interval_minutes.
        scheduler.add_job(
            sync_calendar_reminders,
            trigger=calendar_sync_trigger(),
            id="calendar_reminder_sync",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc),
        )

        # Re-hydrate ad-hoc reminders (agent/tools/alerts.py's set_reminder/
        # set_timer) across restarts — the DB is the source of truth, the
        # scheduler's in-memory jobs are not. Anything already overdue (the
        # app was down past its fire time) fires now rather than being
        # silently dropped.
        await asyncio.to_thread(reminders_store.init_db)
        await asyncio.to_thread(device_state.init_db)
        await asyncio.to_thread(alert_sounds_store.init_db)
        await asyncio.to_thread(device_errors_store.init_db)
        await asyncio.to_thread(activity_log_store.init_db)
        await asyncio.to_thread(recall_log_store.init_db)
        for reminder in await asyncio.to_thread(reminders_store.list_pending):
            due_local = datetime.fromtimestamp(reminder["due_at"], tz=timezone.utc)
            if due_local <= datetime.now(timezone.utc):
                await fire_reminder(reminder["id"])
            else:
                scheduler.add_job(
                    fire_reminder,
                    trigger=DateTrigger(run_date=due_local),
                    args=[reminder["id"]],
                    id=f"reminder:{reminder['id']}",
                    replace_existing=True,
                )

        scheduler.add_job(
            start_of_day_setup,
            trigger=wake_trigger(),
            id="day_start",
            replace_existing=True,
        )

        # Re-hydrate mental-health check-in jobs (jobs/checkin.py) across
        # restarts, same reasoning as the reminders block above — the DB is
        # the source of truth. Expiry timers first, then not-yet-fired
        # one-shots, then a startup catch-up call in case the app was down
        # through today's wake_time (start_of_day_setup is idempotent).
        await asyncio.to_thread(checkins_store.init_db)
        for fired in await asyncio.to_thread(checkins_store.list_fired_awaiting_response):
            expire_at = datetime.fromtimestamp(fired["fired_at"], tz=timezone.utc) + checkin_jobs.CHECKIN_EXPIRY
            if expire_at <= datetime.now(timezone.utc):
                await checkin_jobs.expire_checkin(fired["id"])
            else:
                scheduler.add_job(
                    checkin_jobs.expire_checkin,
                    trigger=DateTrigger(run_date=expire_at),
                    args=[fired["id"]],
                    id=f"checkin_expire:{fired['id']}",
                    replace_existing=True,
                )
        for pending in await asyncio.to_thread(checkins_store.list_pending_unfired):
            due = datetime.fromtimestamp(pending["scheduled_at"], tz=timezone.utc)
            if due <= datetime.now(timezone.utc):
                await checkin_jobs.fire_checkin(pending["id"])
            else:
                scheduler.add_job(
                    checkin_jobs.fire_checkin,
                    trigger=DateTrigger(run_date=due),
                    args=[pending["id"]],
                    id=f"checkin:{pending['id']}",
                    replace_existing=True,
                )
        await start_of_day_setup()

        scheduler.start()

        # Reconciliation runs as a background task rather than being
        # awaited here, so the app starts serving requests immediately
        # rather than blocking on a full vault sweep (which can involve
        # LLM calls for any leftover Inbox files). The live watcher
        # covers everything from this point forward; reconciliation is
        # the catch-up pass for anything that happened while the app was
        # down.
        reconcile_task = asyncio.create_task(reconcile_vault(app_state.memory))
        watch_task = asyncio.create_task(watch_vault(app_state.memory))

        yield

        watch_task.cancel()
        reconcile_task.cancel()
        for task in (watch_task, reconcile_task):
            try:
                await task
            except asyncio.CancelledError:
                pass

        scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET_KEY"],
    session_cookie="TRACKdeck_session",
    max_age=int(os.environ.get("SESSION_MAX_AGE_DAYS", "30")) * 24 * 60 * 60,
    # "strict" (not "lax") since this is a single-user dashboard with no
    # legitimate cross-site-linking-in use case — the cookie mechanism's
    # strongest built-in CSRF mitigation, at the cost of one click's worth
    # of re-auth flash if you follow a link to the dashboard from another
    # origin while already logged in (the session cookie doesn't ride
    # along on that first cross-site navigation; a same-origin request
    # right after re-attaches it normally).
    same_site="strict",
    https_only=os.environ.get("SESSION_COOKIE_SECURE", "false").strip().lower() in ("1", "true", "yes", "on"),
)


# A handful of SPA client routes happen to share an exact path with an
# existing JSON API route — GET /settings, /reminders, /projects,
# /activity-log all serve data at that path *and* are top-level React
# Router routes. A plain top-level browser navigation to one of these
# (typed in the address bar, a bookmark, a page refresh) needs the SPA
# shell, not the JSON the same path returns to a fetch() call — and
# since both are plain GETs, method alone can't disambiguate them.
# Browsers reliably mark a real navigation via `Accept: text/html`,
# which fetch() doesn't send (it defaults to `*/*`), so branch on that
# instead of renaming either side's routes — this runs as middleware
# (before routing) rather than per-route, since it needs to win against
# routes that would otherwise match first by registration order.
_SPA_PASSTHROUGH_PREFIXES = ("/static", "/assets", "/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def prefer_spa_for_html_navigation(request: Request, call_next):
    if (
        request.method == "GET"
        and "text/html" in request.headers.get("accept", "")
        and not request.url.path.startswith(_SPA_PASSTHROUGH_PREFIXES)
    ):
        return FileResponse("frontend/dist/index.html")
    return await call_next(request)


app.include_router(voice_router)  # /voice
app.include_router(synth_router)  # /synthesize
app.include_router(transcribe_router)  # /transcribe
app.include_router(calendar_proxy_router)  # /calendar — proxies the bundled Radicale UI
app.include_router(alert_sounds_router)  # /alert-sounds, /device/alert-sounds/{id}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TextRequest(BaseModel):
    text: str
    # Optional manual override for testing conversation continuity from the
    # browser UI. The ESP32 never sends this — its calls always go through
    # agent.runtime.resolve_thread_id()'s automatic session logic.
    thread_id: str | None = None
    # For testing the ESP32's eventual behavior: forces the agent to never
    # end on a clarifying question, since real hardware has no way to hear
    # a follow-up.
    one_shot: bool = False
    # "onboarding" | "profile_chat" | None — switches to a different active
    # system-prompt mode. Used by the dashboard's onboarding/profile pages,
    # which also pass a fixed thread_id ("onboarding"/"profile_chat") so
    # those conversations stay continuous across visits.
    mode: str | None = None
    # Explicit per-message opt-in from the project page's "Run as agent"
    # checkbox — reframes `text` as a goal to complete autonomously rather
    # than a conversational reply. See PROJECT_AGENT_ADDENDUM in
    # agent/graph.py and run_agent's agent_run param.
    agent_run: bool = False

    @model_validator(mode="after")
    def _check_mode_one_shot_compatible(self):
        # ONE_SHOT_ADDENDUM ("never end on a clarifying question") and
        # ONBOARDING_ADDENDUM ("ask one thing at a time") directly conflict
        # in the system prompt if both are active for the same request.
        if self.mode == "onboarding" and self.one_shot:
            raise ValueError("one_shot cannot be combined with mode='onboarding'")
        if self.agent_run and self.mode != "project_chat":
            raise ValueError("agent_run can only be combined with mode='project_chat'")
        return self


class AssistantResponse(BaseModel):
    reply: str
    thread_id: str
    keyword: str


class ThreadSummary(BaseModel):
    thread_id: str
    keyword: str
    last_activity: float


class NewThreadResponse(BaseModel):
    thread_id: str
    keyword: str


class ThreadMessage(BaseModel):
    role: str
    content: str


class ThreadMessagesResponse(BaseModel):
    messages: list[ThreadMessage]


class ThreadSizeResponse(BaseModel):
    message_count: int
    estimated_tokens: int
    budget_tokens: int


class NoteSummary(BaseModel):
    id: str
    title: str
    tags: list[str]
    project: str | None
    source: str
    created: str
    updated: str
    excerpt: str


class VaultNotesResponse(BaseModel):
    notes: list[NoteSummary]


class NoteDetail(BaseModel):
    id: str
    title: str
    tags: list[str]
    aliases: list[str]
    project: str | None
    source: str
    created: str
    updated: str
    body: str


class ProjectAttachment(BaseModel):
    filename: str
    url: str


class ProjectAttachmentsResponse(BaseModel):
    attachments: list[ProjectAttachment]


class ProjectsResponse(BaseModel):
    projects: list[str]


class AgentActivityStep(BaseModel):
    type: str
    tool: str | None = None
    args: dict | None = None
    content: str | None = None


class AgentActivityResponse(BaseModel):
    steps: list[AgentActivityStep]
    done: bool


class CheckinRecord(BaseModel):
    id: str
    category: str
    prompt_text: str
    status: str
    scheduled_at: int
    fired_at: int | None
    resolved_at: int | None
    reply: str | None
    personalization_level: str
    helpfulness: str | None


class CheckinsTodayResponse(BaseModel):
    checkins: list[CheckinRecord]


class ActivityLogEntry(BaseModel):
    id: str
    occurred_at: int
    activity_type: str
    subject: str
    duration: str | None
    mood_energy: int | None
    reflection: str | None
    created_at: int


class ActivityLogResponse(BaseModel):
    entries: list[ActivityLogEntry]


class MoodByDay(BaseModel):
    date: str
    avg_mood: float
    count: int


class DurationByType(BaseModel):
    activity_type: str
    total_minutes: float
    entry_count: int


class ActivityLogSummaryResponse(BaseModel):
    mood_by_day: list[MoodByDay]
    duration_by_type: list[DurationByType]


class Reminder(BaseModel):
    id: str
    message: str
    due_at: int
    status: str
    created_at: int
    event_uid: str | None


class RemindersResponse(BaseModel):
    reminders: list[Reminder]


class DeviceError(BaseModel):
    id: str
    error_type: str
    message: str | None
    firmware_version: str | None
    reset_reason: str | None
    wake_reason: str | None
    battery_mv: int | None
    battery_pct: int | None
    rssi_dbm: int | None
    free_internal_heap_bytes: int | None
    alerted: bool
    created_at: int


class DeviceErrorsResponse(BaseModel):
    errors: list[DeviceError]


class DebugThreadEntry(BaseModel):
    thread_id: str
    latest_checkpoint_id: str


class DebugThreadsResponse(BaseModel):
    threads: list[DebugThreadEntry]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# static/ now holds only checkin.html and the two assets it depends on
# (css/theme.css, js/voiceInput.js) — the magic-link check-in page is
# deliberately excluded from the React SPA (see frontend/ and the plan's
# §4/§7: it's reached from a bare Gotify push link, possibly in a bad
# moment, so it stays minimal/dependency-free rather than pulling in
# React/Query/Router). Keeping its exact URL means already-delivered
# push notifications never break.
app.mount("/static", StaticFiles(directory="static"), name="static")


class LoginRequest(BaseModel):
    password: str


@app.post("/login")
async def login(body: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    auth.check_login_rate_limit(client_ip)
    if not auth.verify_password(body.password):
        auth.record_failed_login(client_ip)
        raise HTTPException(status_code=401, detail="Incorrect password")
    request.session["authenticated"] = True
    request.session["last_seen"] = time.time()
    return {"status": "ok"}


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@app.post("/text", response_model=AssistantResponse)
async def handle_text(
    request: TextRequest, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    result = await run_agent(
        request.text,
        thread_id=request.thread_id,
        one_shot=request.one_shot,
        mode=request.mode,
        agent_run=request.agent_run,
    )
    return AssistantResponse(reply=result.reply, thread_id=result.thread_id, keyword=result.keyword)


@app.get("/threads", response_model=list[ThreadSummary])
async def get_threads(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Sidebar thread list, most recently active first. Threads are
    threads regardless of whether they started from a voice command or
    typed here — same keyword addressing, same nightly sweep."""
    return [
        {"thread_id": t.thread_id, "keyword": t.keyword, "last_activity": t.last_activity}
        for t in list_threads()
    ]


@app.post("/threads/new", response_model=NewThreadResponse)
async def new_thread(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Explicitly mint a new thread before any message is sent, so a
    fresh 'New Chat' shows up in the sidebar immediately."""
    info = create_new_thread()
    return {"thread_id": info.thread_id, "keyword": info.keyword}


@app.get("/threads/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def thread_messages(
    thread_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    return {"messages": await get_thread_messages(thread_id)}


@app.get("/threads/{thread_id}/size", response_model=ThreadSizeResponse)
async def thread_size(
    thread_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """Rough context-load readout so the dashboard can warn before a thread's
    history grows past what agent/graph.py's call_llm will trim it to."""
    return await get_thread_size(thread_id)


@app.delete("/threads/{thread_id}/messages")
async def clear_thread_route(
    thread_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """Wipes this thread's checkpoint history so its next turn starts fresh
    — a deliberate reset, as opposed to call_llm's automatic gradual trim."""
    await clear_thread(thread_id)
    return {"status": "cleared"}


@app.get("/checkins/today", response_model=CheckinsTodayResponse)
async def todays_checkins(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Today's check-in activity — answered, skipped, and expired — for
    the dashboard's Check-Ins page. 'Today' is the user's local calendar
    day (settings.timezone), the same bounds jobs/digest.py uses for the
    nightly recap — not the waking-hours window jobs/checkin.py itself
    schedules within, so a check-in resolved right before midnight still
    counts as today rather than being cut off early.
    """
    local_tz = settings.zoneinfo()
    now_local = datetime.now(local_tz)
    start_local = datetime.combine(now_local.date(), dtime.min, tzinfo=local_tz)
    end_local = datetime.combine(now_local.date(), dtime.max, tzinfo=local_tz)
    start_ts = int(start_local.astimezone(timezone.utc).timestamp())
    end_ts = int(end_local.astimezone(timezone.utc).timestamp())
    reflections = await checkin_jobs.reflections_between(app_state.memory, start_ts, end_ts)
    return {"checkins": reflections}


def _activity_log_range(days: int) -> tuple[int, int]:
    local_tz = settings.zoneinfo()
    now_local = datetime.now(local_tz)
    start_local = datetime.combine((now_local - timedelta(days=days)).date(), dtime.min, tzinfo=local_tz)
    end_local = datetime.combine(now_local.date(), dtime.max, tzinfo=local_tz)
    start_ts = int(start_local.astimezone(timezone.utc).timestamp())
    end_ts = int(end_local.astimezone(timezone.utc).timestamp())
    return start_ts, end_ts


@app.get("/activity-log", response_model=ActivityLogResponse)
async def list_activity_log(
    _: Annotated[None, Depends(auth.require_session_or_token)],
    days: int = 30,
    activity_type: str | None = None,
):
    """Raw entries for the dashboard's Activity Log page, most recent
    first, over the trailing `days` local-calendar days (default 30).
    Optional activity_type filter for the page's type dropdown.
    """
    start_ts, end_ts = _activity_log_range(days)
    entries = await asyncio.to_thread(
        activity_log_store.list_between, start_ts, end_ts, activity_type
    )
    return {"entries": entries}


@app.get("/activity-log/summary", response_model=ActivityLogSummaryResponse)
async def activity_log_summary(
    _: Annotated[None, Depends(auth.require_session_or_token)],
    days: int = 30,
):
    """Pre-aggregated data for the dashboard's two charts, over the
    trailing `days` local-calendar days — mood/energy averaged per day,
    and total duration per activity type (entries with an unparseable
    duration, e.g. "All Day", are excluded from the duration aggregate
    but still appear in GET /activity-log's raw list).
    """
    start_ts, end_ts = _activity_log_range(days)
    entries = await asyncio.to_thread(activity_log_store.list_between, start_ts, end_ts)
    return activity_log_jobs.summarize(entries)


@app.get("/vault/notes", response_model=VaultNotesResponse)
async def list_vault_notes_route(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Every processed note in the vault (excludes Inbox — unprocessed
    scratch, not "what's accumulated"), most recently updated first.
    Backs the read-only vault-browse dashboard page; filtering/searching
    happens client-side since a personal vault is small enough not to
    need query-param plumbing for it.
    """
    notes = await asyncio.to_thread(vault.list_notes_summary)
    return {"notes": notes}


@app.get("/projects", response_model=ProjectsResponse)
async def list_projects_route(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Project names, derived from vault-root subfolders (see
    utils.vault.list_project_dirs) — used by the Projects page instead of
    fetching every note and grouping by its project field client-side."""
    project_dirs = await asyncio.to_thread(vault.list_project_dirs)
    return {"projects": [p.name for p in project_dirs]}


@app.get("/vault/notes/{note_id}", response_model=NoteDetail)
async def get_vault_note_route(
    note_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """Full single note (including body) for the vault-browse page's
    detail view."""
    path = await asyncio.to_thread(vault.find_note_by_id, note_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Note not found")
    note = await asyncio.to_thread(vault.parse_note, path)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return {
        "id": note.id,
        "title": note.title,
        "tags": note.tags,
        "aliases": note.aliases,
        "project": vault.note_project(path),
        "source": note.source,
        "created": note.created,
        "updated": note.updated,
        "body": note.body,
    }


def _resolve_project_or_404(project: str) -> Path:
    project_dir = vault.match_project_dir(project)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_dir


@app.get("/vault/projects/{project}/attachments", response_model=ProjectAttachmentsResponse)
async def list_project_attachments_route(
    project: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """Image attachments for one project — backs the Projects page's image
    gallery. Attachments can arrive either via the upload route below or by
    being dropped directly into <project>/attachments/ via Obsidian/Syncthing."""
    project_dir = await asyncio.to_thread(_resolve_project_or_404, project)
    paths = await asyncio.to_thread(vault.list_project_attachments, project_dir)
    return {
        "attachments": [
            {
                "filename": p.name,
                "url": f"/vault/projects/{project_dir.name}/attachments/{p.name}",
            }
            for p in paths
        ]
    }


@app.post("/vault/projects/{project}/attachments", response_model=ProjectAttachment)
async def upload_project_attachment_route(
    project: str,
    file: Annotated[UploadFile, File()],
    _: Annotated[None, Depends(auth.require_session_or_token)],
):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are accepted")
    project_dir = await asyncio.to_thread(_resolve_project_or_404, project)
    data = await file.read()
    saved_path = await asyncio.to_thread(
        vault.save_project_attachment, project_dir, file.filename or "upload", data
    )
    return {
        "filename": saved_path.name,
        "url": f"/vault/projects/{project_dir.name}/attachments/{saved_path.name}",
    }


@app.get("/vault/projects/{project}/attachments/{filename}")
async def get_project_attachment_route(
    project: str, filename: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    project_dir = await asyncio.to_thread(_resolve_project_or_404, project)
    # Reject anything that isn't a bare filename (e.g. "../../etc/passwd")
    # before it ever touches the filesystem.
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Attachment not found")
    attachments_dir = vault.project_attachments_dir(project_dir)
    path = attachments_dir / filename
    if not path.resolve().is_relative_to(attachments_dir.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "graph_ready": app_state.graph is not None,
        "memory_ready": app_state.memory is not None,
        "scheduler_running": scheduler.running,
    }


class SettingsUpdate(BaseModel):
    learning_mode: bool | None = None
    # Fallback location for weather tools when none is named in the request.
    default_location: str | None = None
    # IANA timezone name — must be a valid zoneinfo key.
    timezone: str | None = None
    # "HH:MM" 24-hour local time the daily digest fires. Changing this
    # reschedules the live APScheduler job, no restart needed.
    digest_time: str | None = None
    # "HH:MM" 24-hour local time the bedtime reminder fires. Same
    # rescheduling behavior as digest_time, separate job.
    bedtime: str | None = None
    # Minutes between calendar reminder-sync polls (jobs/calendar_sync.py).
    # Same rescheduling behavior as digest_time/bedtime, separate job.
    calendar_sync_interval_minutes: int | None = None
    # "HH:MM" 24-hour local time check-in prompts may start firing (see
    # jobs/checkin.py, jobs/day_start.py). Same rescheduling behavior as
    # digest_time/bedtime, separate job.
    wake_time: str | None = None
    # "HH:MM" 24-hour local time check-in prompts must stop firing by (see
    # jobs/checkin.py) — independent from bedtime, read fresh at
    # schedule-time so no APScheduler reschedule is needed.
    latest_checkin_time: str | None = None
    # Seconds between the ESP32-S3's deep-sleep wake/poll cycles (see
    # main.py's POST /device/sync). No APScheduler job to reschedule —
    # the device reads this on its next sync and self-schedules its own
    # sleep duration.
    device_poll_interval_seconds: int | None = None
    # Daily digest recipient (utils/mailer.py). Blank is a valid
    # "not configured yet" state, same as the unset env var today.
    digest_email_to: str | None = None
    # Base URL for check-in magic links (jobs/checkin.py). Blank is a
    # valid "no click-through link" state, same as today.
    public_base_url: str | None = None
    # Self-hosted Gotify server URL (utils/notify.py). Blank is a valid
    # "not configured yet" state.
    gotify_url: str | None = None
    # Gotify app token (utils/notify.py). A real credential — GET
    # /settings never echoes it back, only whether one is set
    # (_current_settings' gotify_token_set). Sending it here replaces the
    # stored value; omit it entirely to leave the existing token alone.
    gotify_token: str | None = None
    # JSON-encoded {server_name: {enabled, transport, ...}} for MCP
    # servers (agent/settings.py's mcp_servers). Unlike every other field
    # here, this only takes effect on the next app restart — the tool
    # list is fetched once at startup, not read fresh per request.
    mcp_servers: str | None = None
    # Cosine distance cutoff for cross-thread conversation recall
    # (agent/graph.py, agent/memory.py's search_conversations). No
    # rescheduling — read fresh on every agent turn.
    recall_max_distance: float | None = None
    # How many days back cross-thread conversation recall is allowed to
    # reach. Same "read fresh every turn" behavior as recall_max_distance.
    recall_recency_days: int | None = None
    # Approximate token budget for message history sent to the LLM each
    # turn (agent/graph.py's call_llm, via trim_messages). No rescheduling
    # — read fresh on every agent turn.
    max_history_tokens: int | None = None

    @model_validator(mode="after")
    def _check_values(self):
        if self.timezone is not None and not is_valid_timezone(self.timezone):
            raise ValueError(f"'{self.timezone}' is not a recognized IANA timezone name")
        if self.digest_time is not None and not is_valid_digest_time(self.digest_time):
            raise ValueError(f"'{self.digest_time}' is not a valid HH:MM 24-hour time")
        if self.bedtime is not None and not is_valid_digest_time(self.bedtime):
            raise ValueError(f"'{self.bedtime}' is not a valid HH:MM 24-hour time")
        if self.calendar_sync_interval_minutes is not None and not is_valid_sync_interval_minutes(
            self.calendar_sync_interval_minutes
        ):
            raise ValueError("calendar_sync_interval_minutes must be between 1 and 1440")
        if self.wake_time is not None and not is_valid_digest_time(self.wake_time):
            raise ValueError(f"'{self.wake_time}' is not a valid HH:MM 24-hour time")
        if self.latest_checkin_time is not None and not is_valid_digest_time(self.latest_checkin_time):
            raise ValueError(f"'{self.latest_checkin_time}' is not a valid HH:MM 24-hour time")
        if self.device_poll_interval_seconds is not None and not is_valid_poll_interval_seconds(
            self.device_poll_interval_seconds
        ):
            raise ValueError("device_poll_interval_seconds must be between 30 and 86400")
        if self.default_location is not None and not self.default_location.strip():
            raise ValueError("default_location cannot be blank")
        if self.mcp_servers is not None:
            parse_mcp_servers(self.mcp_servers)  # raises ValueError on anything malformed
        if self.recall_max_distance is not None and not is_valid_recall_max_distance(
            self.recall_max_distance
        ):
            raise ValueError("recall_max_distance must be greater than 0 and at most 2.0")
        if self.recall_recency_days is not None and not is_valid_recall_recency_days(
            self.recall_recency_days
        ):
            raise ValueError("recall_recency_days must be between 1 and 3650")
        if self.max_history_tokens is not None and not is_valid_max_history_tokens(
            self.max_history_tokens
        ):
            raise ValueError("max_history_tokens must be between 500 and 200000")
        return self


class SettingsResponse(BaseModel):
    learning_mode: bool
    default_location: str
    timezone: str
    digest_time: str
    calendar_sync_interval_minutes: int
    wake_time: str
    latest_checkin_time: str
    device_poll_interval_seconds: int
    digest_email_to: str
    public_base_url: str
    gotify_url: str
    # Never the raw token — see _current_settings()'s comment.
    gotify_token_set: bool
    mcp_servers: str
    recall_max_distance: float
    recall_recency_days: int
    max_history_tokens: int
    onboarding_complete: bool
    basics_complete: bool


def _current_settings() -> dict:
    return {
        "learning_mode": settings.learning_mode,
        "default_location": settings.default_location,
        "timezone": settings.timezone,
        "digest_time": settings.digest_time,
        "bedtime": settings.bedtime,
        "calendar_sync_interval_minutes": settings.calendar_sync_interval_minutes,
        "wake_time": settings.wake_time,
        "latest_checkin_time": settings.latest_checkin_time,
        "device_poll_interval_seconds": settings.device_poll_interval_seconds,
        "digest_email_to": settings.digest_email_to,
        "public_base_url": settings.public_base_url,
        "gotify_url": settings.gotify_url,
        # Never echo the raw token back to the browser — just whether one
        # is configured, enough for the Settings page's placeholder text.
        "gotify_token_set": bool(settings.gotify_token),
        "mcp_servers": settings.mcp_servers,
        "recall_max_distance": settings.recall_max_distance,
        "recall_recency_days": settings.recall_recency_days,
        "max_history_tokens": settings.max_history_tokens,
        # Read-only here — deliberately not part of SettingsUpdate below, so
        # it can only be set via agent/tools/general.py's
        # mark_onboarding_complete tool, not a direct POST /settings call.
        "onboarding_complete": onboarding_state.is_onboarding_complete(),
        # Read-only here too — only set by POST /onboarding/basics below.
        "basics_complete": onboarding_state.is_basics_complete(),
    }


@app.get("/settings", response_model=SettingsResponse)
async def get_settings(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Current standing app-level toggles (as opposed to per-request
    options like one_shot)."""
    return _current_settings()


async def _apply_settings_update(update: SettingsUpdate) -> None:
    """Applies a SettingsUpdate to the live settings singleton, reschedules
    any affected APScheduler jobs, and persists changed fields to
    settings.db. Shared by POST /settings and POST /onboarding/basics so
    both go through the same write/reschedule/persist logic."""
    changed: dict[str, str] = {}

    if update.learning_mode is not None:
        settings.learning_mode = update.learning_mode
        changed["learning_mode"] = "true" if update.learning_mode else "false"
    if update.default_location is not None:
        settings.default_location = update.default_location.strip()
        changed["default_location"] = settings.default_location

    reschedule_digest = update.timezone is not None or update.digest_time is not None
    reschedule_bedtime = update.timezone is not None or update.bedtime is not None
    reschedule_calendar_sync = update.calendar_sync_interval_minutes is not None
    reschedule_day_start = update.timezone is not None or update.wake_time is not None
    if update.timezone is not None:
        settings.timezone = update.timezone
        changed["timezone"] = update.timezone
    if update.digest_time is not None:
        settings.digest_time = update.digest_time
        changed["digest_time"] = update.digest_time
    if update.bedtime is not None:
        settings.bedtime = update.bedtime
        changed["bedtime"] = update.bedtime
    if update.calendar_sync_interval_minutes is not None:
        settings.calendar_sync_interval_minutes = update.calendar_sync_interval_minutes
        changed["calendar_sync_interval_minutes"] = str(update.calendar_sync_interval_minutes)
    if update.wake_time is not None:
        settings.wake_time = update.wake_time
        changed["wake_time"] = update.wake_time
    if update.latest_checkin_time is not None:
        settings.latest_checkin_time = update.latest_checkin_time
        changed["latest_checkin_time"] = update.latest_checkin_time
    if update.device_poll_interval_seconds is not None:
        settings.device_poll_interval_seconds = update.device_poll_interval_seconds
        changed["device_poll_interval_seconds"] = str(update.device_poll_interval_seconds)
    if update.digest_email_to is not None:
        settings.digest_email_to = update.digest_email_to.strip()
        changed["digest_email_to"] = settings.digest_email_to
    if update.public_base_url is not None:
        settings.public_base_url = update.public_base_url.strip()
        changed["public_base_url"] = settings.public_base_url
    if update.gotify_url is not None:
        settings.gotify_url = update.gotify_url.strip()
        changed["gotify_url"] = settings.gotify_url
    if update.gotify_token is not None:
        settings.gotify_token = update.gotify_token
        changed["gotify_token"] = update.gotify_token
    if update.mcp_servers is not None:
        settings.mcp_servers = update.mcp_servers
        changed["mcp_servers"] = update.mcp_servers
    if update.recall_max_distance is not None:
        settings.recall_max_distance = update.recall_max_distance
        changed["recall_max_distance"] = str(update.recall_max_distance)
    if update.recall_recency_days is not None:
        settings.recall_recency_days = update.recall_recency_days
        changed["recall_recency_days"] = str(update.recall_recency_days)
    if update.max_history_tokens is not None:
        settings.max_history_tokens = update.max_history_tokens
        changed["max_history_tokens"] = str(update.max_history_tokens)

    if reschedule_digest:
        scheduler.reschedule_job("daily_digest", trigger=digest_trigger())
    if reschedule_bedtime:
        scheduler.reschedule_job("bedtime_reminder", trigger=bedtime_trigger())
    if reschedule_calendar_sync:
        scheduler.reschedule_job("calendar_reminder_sync", trigger=calendar_sync_trigger())
    if reschedule_day_start:
        scheduler.reschedule_job("day_start", trigger=wake_trigger())
    if changed:
        await asyncio.to_thread(settings_store.set_many, changed)


@app.post("/settings", response_model=SettingsResponse)
async def update_settings(
    update: SettingsUpdate, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """Update standing app-level toggles. Only fields present in the
    request body are changed. Takes effect immediately — settings are
    read fresh on every agent turn, no restart needed. Every changed
    field is also write-through persisted to settings.db
    (utils/settings_store.py) so it survives a restart.

    timezone/digest_time/bedtime/calendar_sync_interval_minutes/wake_time
    also live-reschedule their APScheduler jobs, since they're registered
    as fixed triggers rather than being read fresh like the other settings.
    latest_checkin_time needs no reschedule — jobs/checkin.py reads it
    fresh at schedule-time, same as bedtime's use there today.

    mcp_servers is the one exception to "takes effect immediately" — it's
    persisted right away like everything else, but the agent's tool list
    is only built once at startup (main.py's lifespan), so a changed or
    newly-added MCP server needs an app restart before the agent can use
    it.
    """
    await _apply_settings_update(update)
    return _current_settings()


class OnboardingPerson(BaseModel):
    name: str
    relation: str | None = None


class OnboardingBasicsRequest(BaseModel):
    name: str | None = None
    birthday: str | None = None
    location: str | None = None
    occupation: str | None = None
    current_job: str | None = None
    people: list[OnboardingPerson] = []
    preferences: str | None = None
    routine: str | None = None
    interests: str | None = None
    values: str | None = None
    health_goals: str | None = None
    important_dates: str | None = None
    wake_time: str | None = None
    bedtime: str | None = None


class OnboardingBasicsResponse(SettingsResponse):
    location_resolved: bool


# Field groups for the onboarding recap, kept small enough per turn to fit a local
# model's context (a single message with every field, plus the system prompt and ~30
# bound tool schemas, was overflowing LM Studio's loaded context length — see
# _process_onboarding_recap below).
_ONBOARDING_RECAP_GROUPS: list[list[str]] = [
    ["name", "birthday", "occupation", "current_job", "important_dates"],
    ["people"],
    ["preferences", "routine"],
    ["interests", "values", "health_goals"],
]


def _build_onboarding_recap_chunks(request: "OnboardingBasicsRequest") -> list[str]:
    field_lines = {
        "name": f"Name: {request.name}" if request.name else None,
        "birthday": f"Birthday: {request.birthday}" if request.birthday else None,
        "occupation": f"Occupation: {request.occupation}" if request.occupation else None,
        "current_job": f"Current job: {request.current_job}" if request.current_job else None,
        "important_dates": (
            f"Important Dates: {request.important_dates}" if request.important_dates else None
        ),
        "people": (
            "People: " + ", ".join(
                f"{p.name} ({p.relation})" if p.relation else p.name for p in request.people
            )
            if request.people
            else None
        ),
        "preferences": f"Preferences: {request.preferences}" if request.preferences else None,
        "routine": f"Routine: {request.routine}" if request.routine else None,
        "interests": f"Interests: {request.interests}" if request.interests else None,
        "values": f"Values: {request.values}" if request.values else None,
        "health_goals": (
            f"Health & Goals: {request.health_goals}" if request.health_goals else None
        ),
    }

    groups = [
        [field_lines[key] for key in group if field_lines[key]]
        for group in _ONBOARDING_RECAP_GROUPS
    ]
    groups = [g for g in groups if g]

    chunks = []
    for i, lines in enumerate(groups):
        header = (
            "I just filled out the basics form:"
            if len(groups) == 1
            else f"I'm continuing to fill out my basics form (part {i + 1} of {len(groups)}):"
        )
        chunk = header + "\n" + "\n".join(lines)
        if i == len(groups) - 1:
            chunk += (
                "\n\nPlease record this properly (a separate note for each person listed), "
                "and ask me about anything here you'd like more detail on."
            )
        chunks.append(chunk)
    return chunks


async def _process_onboarding_recap(chunks: list[str]) -> None:
    """Runs each recap chunk as its own turn in the "onboarding" thread,
    sequentially (they share one LangGraph-checkpointed thread, so concurrent
    calls would race the checkpoint). Fire-and-forget background task, same
    pattern as voice.py's _process_voice_note — failures/success surface via
    Gotify, never over HTTP, since the request has already returned."""
    failures = 0
    last_error: Exception | None = None
    for chunk in chunks:
        try:
            await run_agent(chunk, thread_id="onboarding", mode="onboarding")
        except Exception as e:
            logger.exception("Onboarding recap chunk failed")
            failures += 1
            last_error = e

    if failures:
        await asyncio.to_thread(
            notify_error,
            f"Onboarding basics: {failures}/{len(chunks)} parts failed to record",
            last_error,
        )
    else:
        await asyncio.to_thread(
            send_gotify, "Onboarding", "All basics form details recorded.", priority=3
        )


@app.post("/onboarding/basics", response_model=OnboardingBasicsResponse)
async def submit_onboarding_basics(
    request: OnboardingBasicsRequest,
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(auth.require_session_or_token)],
):
    """One-time submission from the onboarding basics form (the first step
    of /profile, before the guided chat interview takes over). Every field
    is optional. Location/wake_time/bedtime go through the same settings
    write path as POST /settings (not About Me — that separation is
    deliberate, see agent/tools/general.py's set_home_location). Everything
    else is handed to the agent as a handful of real turns in the
    "onboarding" thread, run in the background after this responds (see
    _process_onboarding_recap) — its own tools (remember_about_me,
    get_or_create_linked_note) do the actual About Me writing, so the
    content gets written up properly (with a dedicated note per person)
    instead of dumped in verbatim, and its replies — likely follow-up
    questions — land in the thread for the chat view to pick up on next
    load."""
    location_resolved = False
    try:
        if request.location:
            resolved = resolve_location(request.location)
            if resolved is not None:
                resolved_name, tz_name = resolved
                await _apply_settings_update(
                    SettingsUpdate(default_location=resolved_name, timezone=tz_name)
                )
                location_resolved = True
        if request.wake_time or request.bedtime:
            await _apply_settings_update(
                SettingsUpdate(wake_time=request.wake_time, bedtime=request.bedtime)
            )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    chunks = _build_onboarding_recap_chunks(request)
    onboarding_state.mark_basics_complete()
    if chunks:
        background_tasks.add_task(_process_onboarding_recap, chunks)

    return {**_current_settings(), "location_resolved": location_resolved}


@app.post("/onboarding/complete", response_model=SettingsResponse)
async def complete_onboarding(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Explicit "Finished" action from the onboarding chat step's UI — the
    manual, user-triggered counterpart to the mark_onboarding_complete
    agent tool (agent/tools/general.py), which sets the same flag when the
    model itself decides the interview has covered enough."""
    onboarding_state.mark_onboarding_complete()
    return _current_settings()


@app.post("/onboarding/reset", response_model=SettingsResponse)
async def reset_onboarding(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Deletes About Me and restarts the onboarding wizard from the basics
    form. Also clears the onboarding/profile_chat conversation threads,
    since their history is all about a profile that no longer exists.
    Scoped to About Me only — notes linked from it (individual people) and
    Settings (location/timezone/schedule) are left untouched."""
    about_me_path = vault.about_me_path()
    if about_me_path.exists():
        about_me_path.unlink()
    await reconcile_vault(app_state.memory)
    await clear_thread("onboarding")
    await clear_thread("profile_chat")
    onboarding_state.clear_basics_complete()
    onboarding_state.clear_onboarding_complete()
    return _current_settings()


@app.post("/debug/digest")
async def trigger_digest_now(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Manually fires today's digest immediately, without waiting for the
    20:45 schedule. Sends a real email on every call — remove or comment
    this out once you're done testing the pipeline end to end.
    """
    await send_daily_digest(app_state.memory)
    return {"status": "sent"}


@app.post("/debug/reminders/fire/{reminder_id}")
async def trigger_reminder_now(
    reminder_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """
    Manually fires a specific pending reminder immediately, without waiting
    for its scheduled time — useful for testing delivery without sitting
    around for the real due time.
    """
    await fire_reminder(reminder_id)
    return {"status": "fired"}


@app.post("/debug/calendar-sync")
async def trigger_calendar_sync_now(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Manually runs a calendar reminder sync pass immediately, without
    waiting for the CALENDAR_SYNC_INTERVAL_MINUTES schedule — useful for
    testing that a manually added/changed/removed calendar event (with a
    native alarm set) picks up correctly.
    """
    await sync_calendar_reminders()
    return {"status": "synced"}


@app.post("/debug/reconcile-vault")
async def trigger_reconcile_now(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Manually forces a full vault reconciliation sweep — useful for
    confirming the notes index actually matches the vault on disk without
    waiting for the live watcher or an app restart.
    """
    await reconcile_vault(app_state.memory)
    return {"status": "reconciled"}


@app.post("/debug/bedtime")
async def trigger_bedtime_reminder_now(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Manually fires the bedtime reminder immediately, without waiting for
    its scheduled time — sends a real Gotify push on every call.
    """
    await send_bedtime_reminder()
    return {"status": "sent"}


@app.post("/debug/checkin")
async def trigger_checkin_now(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Manually creates and immediately fires a test mental-health check-in,
    bypassing the day's 3-5 target and waking-hours window — runs the
    exact same create/schedule/fire path a real check-in takes (real DB
    row, real thread, real Gotify push).
    """
    await checkin_jobs.trigger_test_checkin()
    return {"status": "sent"}


@app.get("/debug/checkin/preview")
async def preview_checkin_personalization(
    category: Literal["low", "medium", "high"],
    level: Literal["select", "light", "moderate"],
    _: Annotated[None, Depends(auth.require_session_or_token)],
):
    """
    Runs one check-in personalization level on demand and returns the raw
    LLM output, for testing prompt quality without creating a real check-in
    or waiting for the live none/select/light rotation to happen to land on
    the level you want to inspect. "moderate" is only reachable here — see
    jobs/checkin.py's PERSONALIZATION_LEVELS for why it's excluded from
    live check-ins.
    """
    return await checkin_jobs.preview_personalization(category, level)


@app.post("/debug/notify")
async def trigger_test_notification(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Sends a one-off test Gotify push — useful for confirming
    GOTIFY_URL/GOTIFY_TOKEN are configured correctly without triggering
    a real job.
    """
    await asyncio.to_thread(
        send_gotify, "Test Notification", "This is a test notification from the dashboard.", 5
    )
    return {"status": "sent"}


@app.post("/debug/email")
async def trigger_test_email(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Sends a one-off test email — useful for confirming the SMTP_* env
    vars are configured correctly without waiting for the daily digest.
    """
    await asyncio.to_thread(send_email, "Test email", "This is a test email from the dashboard.")
    return {"status": "sent"}


@app.post("/debug/reminder")
async def trigger_test_reminder(
    _: Annotated[None, Depends(auth.require_session_or_token)],
    delay_seconds: Annotated[int, Query(ge=1, le=3600)] = 10,
):
    """
    Creates a real pending reminder due `delay_seconds` from now (default
    10s) and schedules it on the shared scheduler — exercises the full
    ad-hoc reminder pipeline (store -> scheduler -> fire_reminder ->
    Gotify) end to end, unlike /debug/reminders/fire/{id} which needs an
    existing reminder id.
    """
    reminder_id = await create_test_reminder(delay_seconds)
    return {"status": "scheduled", "reminder_id": reminder_id}


class ReminderUpdate(BaseModel):
    message: str | None = None
    due_at: str | None = None  # local datetime string, e.g. "2026-08-08T09:00"


@app.get("/reminders", response_model=RemindersResponse)
async def list_reminders_route(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Pending reminders, soonest first — backs the dashboard's To-Dos page."""
    return {"reminders": await asyncio.to_thread(reminders_store.list_pending)}


@app.patch("/reminders/{reminder_id}", response_model=Reminder)
async def update_reminder_route(
    reminder_id: str, update: ReminderUpdate, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """Partial update of a reminder's message/due time. Only fields present
    in the request body are changed. Also reschedules the live APScheduler
    job when due_at changes on a still-pending reminder — the DB row alone
    doesn't control fire time, same as agent/tools/alerts.py's
    _create_reminder."""
    existing = await asyncio.to_thread(reminders_store.get_reminder, reminder_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Reminder not found")

    due_epoch = None
    if update.due_at is not None:
        due_local = parse_local_datetime(update.due_at)
        due_epoch = int(due_local.astimezone(timezone.utc).timestamp())

    updated = await asyncio.to_thread(
        reminders_store.update_reminder, reminder_id, update.message, due_epoch
    )

    if due_epoch is not None and existing["status"] == "pending":
        due_local = datetime.fromtimestamp(due_epoch, tz=timezone.utc).astimezone(settings.zoneinfo())
        scheduler.add_job(
            fire_reminder,
            trigger=DateTrigger(run_date=due_local),
            args=[reminder_id],
            id=f"reminder:{reminder_id}",
            replace_existing=True,
        )
    return updated


@app.delete("/reminders/{reminder_id}")
async def delete_reminder_route(
    reminder_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """Cancels a reminder (mark_status, not a hard delete — same convention
    as agent/tools/alerts.py's cancel_reminder) and unschedules its
    APScheduler job if still pending."""
    existing = await asyncio.to_thread(reminders_store.get_reminder, reminder_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Reminder not found")

    await asyncio.to_thread(reminders_store.mark_status, reminder_id, "cancelled")
    try:
        scheduler.remove_job(f"reminder:{reminder_id}")
    except JobLookupError:
        pass
    return {"status": "cancelled"}


@app.get("/debug/device-sync")
async def preview_device_sync(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Returns the exact payload POST /device/sync would send the ESP32-S3,
    without recording any telemetry — lets the payload shape be checked
    against firmware expectations without needing real hardware.
    """
    return await build_sync_payload()


@app.get("/debug/device-state")
async def get_device_state(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Last telemetry the ESP32-S3 reported on its most recent POST
    /device/sync call — last sync time, battery, wake reason, firmware
    version. Empty dict if the device hasn't synced yet.
    """
    state = await asyncio.to_thread(device_state.get_state)
    return state or {}


@app.get("/debug/threads", response_model=DebugThreadsResponse)
async def debug_list_threads(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Every thread_id that has ever run a turn through the graph, straight
    from memory.db's checkpoint table — unlike GET /threads (which only
    lists currently-addressable threads and is swept nightly), this
    includes threads from before today's sweep or a past restart. Backs
    the thread-debug dashboard page's thread picker.
    """
    return {"threads": await list_checkpoint_thread_ids()}


@app.get("/debug/thread/{thread_id}")
async def debug_thread(
    thread_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """
    Full, unfiltered per-thread trace for the thread-debug dashboard page:
    the opening message, every turn including tool calls and their
    results (GET /threads/{id}/messages filters these out for chat
    rendering — this doesn't), and what agent/graph.py's
    search_conversations recalled/injected on each turn (recall_log.db,
    see utils/recall_log_store.py) — the direct visibility this was built
    for, into the cross-thread recall leak documented in UPCOMING.md.
    Note: there's no reasoning trace here — the model never emits
    reasoning separate from tool calls or its final reply, so that part
    isn't satisfiable without a reasoning-capable model swap.
    """
    return await get_thread_debug(thread_id)


@app.get("/agent-activity/{thread_id}", response_model=AgentActivityResponse)
async def agent_activity(
    thread_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """
    Polled by a project page while a "Run as agent" turn is in flight —
    {"steps": [...], "done": bool}, populated live by run_agent's
    agent_run path (agent/runtime.py's _run_graph_streamed). Returns
    done=True with no steps for any thread that isn't currently running
    one, so polling a thread that already finished (or never started) is
    always a safe no-op rather than an error.
    """
    return get_agent_activity(thread_id)


class DeviceTelemetry(BaseModel):
    battery_mv: int | None = None
    wake_reason: str | None = None
    firmware_version: str | None = None
    rssi_dbm: int | None = None
    # Milliseconds the device was awake this cycle (wifi connect ->
    # response received) — the actual number that validates or refutes
    # the multi-day battery estimate, rather than guessing at it.
    time_awake_ms: int | None = None
    # ESP-IDF's esp_reset_reason() stringified by firmware (e.g.
    # "power_on", "deep_sleep_wake", "brownout", "watchdog", "panic") —
    # the only visibility into a crash/brownout during the beta without
    # a debugger attached.
    reset_reason: str | None = None


@app.post("/device/sync")
async def device_sync(
    telemetry: DeviceTelemetry, _: Annotated[None, Depends(auth.require_device_token)]
):
    """
    Polled by the ESP32-S3 on every wake — scheduled deep-sleep interval
    (settings.device_poll_interval_seconds, returned below) or an
    incidental wake for a normal voice command. The server stays
    authoritative on scheduling (jobs/checkin.py, APScheduler); the
    device is a preview/display layer, not the delivery mechanism —
    Gotify pushes still fire regardless of whether this endpoint is ever
    called. Body is optional telemetry (all fields nullable, since early
    firmware may not send everything yet); response is a full 24h
    snapshot (see jobs/device_sync.py's build_sync_payload) covering
    check-ins, reminders, calendar events, weather, and enough
    timezone/scheduling context to keep the device's own clock and
    polling loop correct.
    """
    await asyncio.to_thread(
        device_state.record_sync,
        telemetry.battery_mv,
        telemetry.wake_reason,
        telemetry.firmware_version,
        telemetry.rssi_dbm,
        telemetry.time_awake_ms,
        telemetry.reset_reason,
        int(time.time()),
    )
    return await build_sync_payload()


class DeviceErrorReport(BaseModel):
    # Short machine-readable tag, e.g. "sync_response_too_large",
    # "wifi_connect_failed", "sd_write_failed" — free text, no enum
    # enforced server-side, so firmware can report any failure it wants
    # through this one generic channel.
    error_type: str
    message: str | None = None
    firmware_version: str | None = None
    reset_reason: str | None = None
    # timer/button/power_on, etc. — same vocabulary as DeviceTelemetry's
    # wake_reason above, helps correlate what kind of cycle hit the error.
    wake_reason: str | None = None
    battery_mv: int | None = None
    battery_pct: int | None = None
    # Signal strength at the time of the error — correlates connectivity
    # failures with a weak link rather than a real network/server problem.
    rssi_dbm: int | None = None
    # heap_caps_get_free_size(MALLOC_CAP_INTERNAL) specifically — not a
    # combined/PSRAM figure. This device leans on PSRAM for anything
    # multi-KB (the sync buffer, WAV chunk buffers, tone buffers)
    # precisely because internal SRAM is scarce (3.5KB main task stack);
    # PSRAM running low is unlikely to ever matter here, internal SRAM
    # running low is the actual crash risk, so that's the number worth
    # capturing.
    free_internal_heap_bytes: int | None = None


@app.post("/device/error")
async def device_error(
    report: DeviceErrorReport, _: Annotated[None, Depends(auth.require_device_token)]
):
    """
    Standalone error-reporting channel for the ESP32-S3 — independent of
    POST /device/sync so it still works when sync itself never succeeds
    (WiFi association failure, a response too large for the device's
    fixed buffer, an SD card write failure, etc.), unlike DeviceTelemetry
    above which only ever rides on a successful sync call. Pushes a
    priority-8 Gotify alert, deduped per error_type via
    notify.notify_device_error so a stuck retry loop doesn't spam Gotify
    every wake.
    """
    detail = " | ".join(filter(None, [
        report.message,
        f"firmware {report.firmware_version}" if report.firmware_version else None,
        f"wake_reason={report.wake_reason}" if report.wake_reason else None,
        f"reset_reason={report.reset_reason}" if report.reset_reason else None,
        f"battery={report.battery_pct}%" if report.battery_pct is not None else None,
        f"battery_mv={report.battery_mv}" if report.battery_mv is not None else None,
        f"rssi={report.rssi_dbm}dBm" if report.rssi_dbm is not None else None,
        f"free_internal_heap={report.free_internal_heap_bytes}B"
        if report.free_internal_heap_bytes is not None else None,
    ])) or "(no further detail provided)"

    sent = await asyncio.to_thread(notify_device_error, report.error_type, detail)
    await asyncio.to_thread(
        device_errors_store.record_error,
        report.error_type,
        report.message,
        report.firmware_version,
        report.reset_reason,
        report.wake_reason,
        report.battery_mv,
        report.battery_pct,
        report.rssi_dbm,
        report.free_internal_heap_bytes,
        sent,
        int(time.time()),
    )
    return {"status": "sent" if sent else "suppressed"}


@app.get("/device/errors", response_model=DeviceErrorsResponse)
async def list_device_errors(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    History of device-reported errors (POST /device/error above), most
    recent first, for the dashboard's Errors page. Includes suppressed
    occurrences too (deduped by notify.notify_device_error's per-
    error_type cooldown), not just ones that actually triggered a Gotify
    alert — so a repeatedly-firing condition is visible even while the
    notification channel itself is being throttled.
    """
    errors = await asyncio.to_thread(device_errors_store.list_recent)
    return {"errors": [{**e, "alerted": bool(e["alerted"])} for e in errors]}


async def _skip_checkin(checkin_id: str) -> dict:
    checkin = await asyncio.to_thread(checkins_store.get_checkin, checkin_id)
    if checkin is None:
        raise HTTPException(status_code=404, detail="Unknown check-in")
    if checkin["status"] != "pending" or checkin["fired_at"] is None:
        raise HTTPException(
            status_code=409,
            detail=f"Check-in is '{checkin['status']}', not awaiting a response",
        )

    await checkin_jobs.resolve_checkin(checkin_id, outcome="skipped")
    return {"status": "skipped"}


@app.post("/device/checkin/{checkin_id}/skip")
async def skip_checkin(
    checkin_id: str, _: Annotated[None, Depends(auth.require_device_token)]
):
    """
    Called by the check-in device before going back to sleep, in lieu of
    answering — deep sleep means the server can't infer "no reply" from
    silence, so this is an explicit signal. Triggers jobs/checkin.py's
    fallback-retry/cooldown rescheduling.
    """
    return await _skip_checkin(checkin_id)


@app.get("/checkin/{checkin_id}/status")
async def checkin_status(checkin_id: str):
    """
    Lets static/checkin.html check on load whether this check-in is still
    awaiting a response, so a refreshed or reopened magic link shows the
    resolved state instead of re-rendering the reply form — same trust
    model as skip_checkin_public/reply_checkin below (gated only by
    possessing the id).
    """
    checkin = await asyncio.to_thread(checkins_store.get_checkin, checkin_id)
    if checkin is None:
        raise HTTPException(status_code=404, detail="Unknown check-in")
    return {
        "status": checkin["status"],
        "awaiting_response": checkin["status"] == "pending" and checkin["fired_at"] is not None,
    }


@app.post("/checkin/{checkin_id}/skip")
async def skip_checkin_public(checkin_id: str):
    """
    Magic-link counterpart to skip_checkin above, for static/checkin.html
    — gated only by possessing this check-in's own id, not API_TOKEN. See
    jobs/checkin.py's answer_checkin docstring for why that's an
    acceptable trust model for this feature: the id is 122 bits of
    randomness, unguessable, and the window it's valid for is naturally
    short (a check-in resolves or expires within CHECKIN_EXPIRY of
    firing).
    """
    return await _skip_checkin(checkin_id)


class CheckinReplyRequest(BaseModel):
    text: str


@app.post("/checkin/{checkin_id}/reply")
async def reply_checkin(checkin_id: str, request: CheckinReplyRequest):
    """
    Magic-link text reply for static/checkin.html — same trust model as
    skip_checkin_public above.
    """
    result = await checkin_jobs.answer_checkin(checkin_id, request.text)
    if result is None:
        raise HTTPException(status_code=409, detail="Check-in is no longer awaiting a reply")
    return {"reply": result.reply}


@app.get("/checkin/{checkin_id}/rate")
async def rate_checkin(checkin_id: str, helpful: Literal["yes", "no"]):
    """
    Magic-link thumbs-up/down from the daily digest email (jobs/digest.py's
    rating block). GET, not POST — a plain-text email link has no JS/form to
    issue a POST. Same trust model as the other magic-link check-in routes
    above (the id itself is the capability token), but scoped to
    status == "answered" rather than "pending" — only a check-in the user
    actually engaged with makes sense to rate. No expiry window: unlike the
    pending-to-fired CHECKIN_EXPIRY clock, a digest email is a standing
    record and a rating given days later is still real data.
    """
    checkin = await asyncio.to_thread(checkins_store.get_checkin, checkin_id)
    if checkin is None:
        raise HTTPException(status_code=404, detail="Unknown check-in")
    if checkin["status"] != "answered":
        raise HTTPException(status_code=409, detail="Only answered check-ins can be rated")
    await asyncio.to_thread(checkins_store.record_helpfulness, checkin_id, helpful == "yes")
    return HTMLResponse("<p>Thanks — got it. You can close this tab.</p>")


# ---------------------------------------------------------------------------
# React SPA (frontend/) — registered last so Starlette's registration-order
# route matching never lets this shadow a real API route above. Vite emits
# hashed assets under dist/assets/, which can't collide with an API path;
# every other unmatched GET (client-side routes like /vault, /settings,
# /projects/foo) falls through to index.html and React Router takes over
# from there. This replaces the old GET "/" / GET "/project/{name}"
# routes' server-side session-gated HTML serving — the SPA's RequireAuth
# guard (frontend/src/components/RequireAuth.tsx) does that client-side
# now, uniformly with every other route instead of just these two.
# ---------------------------------------------------------------------------

app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="spa-assets")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    return FileResponse("frontend/dist/index.html")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
