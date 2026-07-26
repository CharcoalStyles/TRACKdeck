"""
Personal Assistant — FastAPI + LangGraph
----------------------------------------
"""
import os
import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

import uvicorn
from apscheduler.triggers.date import DateTrigger
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, model_validator
from starlette.middleware.sessions import SessionMiddleware

# Load .env before anything that reads os.environ (i.e. before agent imports)
load_dotenv()

from utils.logging import configure_logging

# Configured before any other app module is imported, so every logger
# created at import time (module-level `logging.getLogger(__name__)`
# calls) already has the right level/handler via the root logger.
configure_logging()

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
from agent.runtime import app_state, create_new_thread, get_thread_messages, list_threads, run_agent
from agent.scheduler import (
    bedtime_trigger,
    calendar_sync_trigger,
    digest_trigger,
    scheduler,
    wake_trigger,
)
from agent.settings import is_valid_digest_time, is_valid_sync_interval_minutes, is_valid_timezone, settings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from jobs import checkin as checkin_jobs
from jobs.bedtime import send_bedtime_reminder
from jobs.calendar_sync import sync_calendar_reminders
from jobs.day_start import start_of_day_setup
from jobs.digest import send_daily_digest
from jobs.reminders import fire_reminder

from agent.vault_watcher import reconcile_vault, watch_vault
from utils import checkins_store, reminders_store, vault

from voice import router as voice_router
from routes.synth import router as synth_router

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    chroma_client = make_chroma_client()
    embedding_fn = make_embedding_function()
    app_state.memory = MemoryStore(chroma_client, embedding_fn)

    vault.ensure_vault_dirs()

    async with AsyncSqliteSaver.from_conn_string("memory.db") as checkpointer:
        app_state.graph = build_graph(checkpointer, app_state.memory)

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
        # event added/changed/removed manually (in Nextcloud, not through
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
    session_cookie="adhi_session",
    max_age=int(os.environ.get("SESSION_MAX_AGE_DAYS", "30")) * 24 * 60 * 60,
    same_site="lax",
    https_only=os.environ.get("SESSION_COOKIE_SECURE", "false").strip().lower() in ("1", "true", "yes", "on"),
)
app.include_router(voice_router)  # /voice
app.include_router(synth_router)  # /synthesize


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

    @model_validator(mode="after")
    def _check_mode_one_shot_compatible(self):
        # ONE_SHOT_ADDENDUM ("never end on a clarifying question") and
        # ONBOARDING_ADDENDUM ("ask one thing at a time") directly conflict
        # in the system prompt if both are active for the same request.
        if self.mode == "onboarding" and self.one_shot:
            raise ValueError("one_shot cannot be combined with mode='onboarding'")
        return self


class AssistantResponse(BaseModel):
    reply: str
    thread_id: str
    keyword: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_frontend(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/static/login.html", status_code=302)
    static_file_path = os.path.join("static", "index.html")
    if os.path.exists(static_file_path):
        with open(static_file_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(content="<h1>static/index.html not found</h1>", status_code=404)


# Mount the rest of the static folder for any assets/css/js if you add them later
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
    return {"status": "ok"}


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@app.get("/device/token")
async def get_device_token(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """
    Lets an already-session-authenticated dashboard obtain the raw
    API_TOKEN, so static/voice.html's browser mic test (which calls the
    device-token-only POST /voice directly, see auth.py) still has a
    credential to attach. Only reachable to a caller who already cleared
    the session-or-token gate — not to any anonymous visitor, unlike the
    old always-on api.js token-injection this replaces.
    """
    return {"token": os.environ["API_TOKEN"]}


@app.post("/text", response_model=AssistantResponse)
async def handle_text(
    request: TextRequest, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    result = await run_agent(
        request.text,
        thread_id=request.thread_id,
        one_shot=request.one_shot,
        mode=request.mode,
    )
    return AssistantResponse(reply=result.reply, thread_id=result.thread_id, keyword=result.keyword)


@app.get("/threads")
async def get_threads(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Sidebar thread list, most recently active first. Threads are
    threads regardless of whether they started from a voice command or
    typed here — same keyword addressing, same nightly sweep."""
    return [
        {"thread_id": t.thread_id, "keyword": t.keyword, "last_activity": t.last_activity}
        for t in list_threads()
    ]


@app.post("/threads/new")
async def new_thread(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Explicitly mint a new thread before any message is sent, so a
    fresh 'New Chat' shows up in the sidebar immediately."""
    info = create_new_thread()
    return {"thread_id": info.thread_id, "keyword": info.keyword}


@app.get("/threads/{thread_id}/messages")
async def thread_messages(
    thread_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    return {"messages": await get_thread_messages(thread_id)}


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
        if self.default_location is not None and not self.default_location.strip():
            raise ValueError("default_location cannot be blank")
        return self


def _current_settings() -> dict:
    return {
        "learning_mode": settings.learning_mode,
        "default_location": settings.default_location,
        "timezone": settings.timezone,
        "digest_time": settings.digest_time,
        "bedtime": settings.bedtime,
        "calendar_sync_interval_minutes": settings.calendar_sync_interval_minutes,
        "wake_time": settings.wake_time,
    }


@app.get("/settings")
async def get_settings(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Current standing app-level toggles (as opposed to per-request
    options like one_shot)."""
    return _current_settings()


@app.post("/settings")
async def update_settings(
    update: SettingsUpdate, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    """Update standing app-level toggles. Only fields present in the
    request body are changed. Takes effect immediately — settings are
    read fresh on every agent turn, no restart needed.

    timezone/digest_time/bedtime/calendar_sync_interval_minutes/wake_time
    also live-reschedule their APScheduler jobs, since they're registered
    as fixed triggers rather than being read fresh like the other settings.
    """
    if update.learning_mode is not None:
        settings.learning_mode = update.learning_mode
    if update.default_location is not None:
        settings.default_location = update.default_location.strip()

    reschedule_digest = update.timezone is not None or update.digest_time is not None
    reschedule_bedtime = update.timezone is not None or update.bedtime is not None
    reschedule_calendar_sync = update.calendar_sync_interval_minutes is not None
    reschedule_day_start = update.timezone is not None or update.wake_time is not None
    if update.timezone is not None:
        settings.timezone = update.timezone
    if update.digest_time is not None:
        settings.digest_time = update.digest_time
    if update.bedtime is not None:
        settings.bedtime = update.bedtime
    if update.calendar_sync_interval_minutes is not None:
        settings.calendar_sync_interval_minutes = update.calendar_sync_interval_minutes
    if update.wake_time is not None:
        settings.wake_time = update.wake_time
    if reschedule_digest:
        scheduler.reschedule_job("daily_digest", trigger=digest_trigger())
    if reschedule_bedtime:
        scheduler.reschedule_job("bedtime_reminder", trigger=bedtime_trigger())
    if reschedule_calendar_sync:
        scheduler.reschedule_job("calendar_reminder_sync", trigger=calendar_sync_trigger())
    if reschedule_day_start:
        scheduler.reschedule_job("day_start", trigger=wake_trigger())

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


@app.get("/device/sync")
async def device_sync(_: Annotated[None, Depends(auth.require_device_token)]):
    """
    Polled by the (not-yet-built) ESP32-S3 check-in device on every wake —
    scheduled RTC wake alarm or an incidental wake for a normal voice
    command. The device is deep-sleep the rest of the time, so this is its
    only chance to learn what's pending and when to wake next; the server
    stays authoritative on scheduling (jobs/checkin.py), the device just
    executes. Check-in-only for now — see jobs/checkin.py's module
    docstring for the state machine behind this list.
    """
    now = int(time.time())
    upcoming = await asyncio.to_thread(checkins_store.list_next_24h, now)
    return {
        "checkins": [
            {
                "id": c["id"],
                "category": c["category"],
                "prompt_text": c["prompt_text"],
                "scheduled_at": c["scheduled_at"],
                "fired_at": c["fired_at"],
            }
            for c in upcoming
        ],
        "next_wake_at": await checkin_jobs.next_wake_at(),
    }


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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
