"""
Personal Assistant — FastAPI + LangGraph
----------------------------------------
"""
import os
import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, model_validator

# Load .env before anything that reads os.environ (i.e. before agent imports)
load_dotenv()

from utils.logging import configure_logging

# Configured before any other app module is imported, so every logger
# created at import time (module-level `logging.getLogger(__name__)`
# calls) already has the right level/handler via the root logger.
configure_logging()

# The dashboard's static/js/api.js ships this same string as its default
# AUTH_TOKEN, and .env.example documents it as the sample value — so an
# unedited API_TOKEN isn't just "unset", it's a real, publicly-known
# credential for every API_TOKEN-gated route. Refuse to start rather than
# silently running with it.
_PLACEHOLDER_API_TOKEN = "YOUR_SUPER_SECRET_SECURE_TOKEN"
if os.environ.get("API_TOKEN") == _PLACEHOLDER_API_TOKEN:
    raise RuntimeError(
        "API_TOKEN is still set to the placeholder value from .env.example. "
        "Set it to a real, private secret before starting the app."
    )

from agent.graph import build_graph
from agent.memory import MemoryStore, make_chroma_client, make_embedding_function
from agent.runtime import app_state, create_new_thread, get_thread_messages, list_threads, run_agent
from agent.settings import is_valid_digest_time, is_valid_timezone, settings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from jobs.digest import send_daily_digest

from agent.vault_watcher import reconcile_vault, watch_vault
from utils import vault

from voice import router as voice_router
from routes.synth import router as synth_router

# ---------------------------------------------------------------------------
# Scheduler — daily digest, time/timezone from settings (jobs/digest.py has
# the rationale for the ~20:45 default). Rescheduled live by /settings
# below rather than requiring a restart.
# ---------------------------------------------------------------------------

scheduler = AsyncIOScheduler(timezone=settings.zoneinfo())


def _digest_trigger() -> CronTrigger:
    hour, minute = (int(p) for p in settings.digest_time.split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=settings.zoneinfo())


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
            trigger=_digest_trigger(),
            args=[app_state.memory],
            id="daily_digest",
            replace_existing=True,
        )
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
async def serve_frontend():
    static_file_path = os.path.join("static", "index.html")
    if os.path.exists(static_file_path):
        with open(static_file_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(content="<h1>static/index.html not found</h1>", status_code=404)

# Mount the rest of the static folder for any assets/css/js if you add them later
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.post("/text", response_model=AssistantResponse)
async def handle_text(request: TextRequest, auth: Annotated[str | None, Header()] = None):
    if auth != os.environ["API_TOKEN"]:
        raise HTTPException(status_code=401, detail="Unauthorized request source")

    result = await run_agent(
        request.text,
        thread_id=request.thread_id,
        one_shot=request.one_shot,
        mode=request.mode,
    )
    return AssistantResponse(reply=result.reply, thread_id=result.thread_id, keyword=result.keyword)


@app.get("/threads")
async def get_threads():
    """Sidebar thread list, most recently active first. Threads are
    threads regardless of whether they started from a voice command or
    typed here — same keyword addressing, same nightly sweep."""
    return [
        {"thread_id": t.thread_id, "keyword": t.keyword, "last_activity": t.last_activity}
        for t in list_threads()
    ]


@app.post("/threads/new")
async def new_thread(auth: Annotated[str | None, Header()] = None):
    """Explicitly mint a new thread before any message is sent, so a
    fresh 'New Chat' shows up in the sidebar immediately."""
    if auth != os.environ["API_TOKEN"]:
        raise HTTPException(status_code=401, detail="Unauthorized request source")

    info = create_new_thread()
    return {"thread_id": info.thread_id, "keyword": info.keyword}


@app.get("/threads/{thread_id}/messages")
async def thread_messages(thread_id: str):
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

    @model_validator(mode="after")
    def _check_values(self):
        if self.timezone is not None and not is_valid_timezone(self.timezone):
            raise ValueError(f"'{self.timezone}' is not a recognized IANA timezone name")
        if self.digest_time is not None and not is_valid_digest_time(self.digest_time):
            raise ValueError(f"'{self.digest_time}' is not a valid HH:MM 24-hour time")
        if self.default_location is not None and not self.default_location.strip():
            raise ValueError("default_location cannot be blank")
        return self


def _current_settings() -> dict:
    return {
        "learning_mode": settings.learning_mode,
        "default_location": settings.default_location,
        "timezone": settings.timezone,
        "digest_time": settings.digest_time,
    }


@app.get("/settings")
async def get_settings():
    """Current standing app-level toggles (as opposed to per-request
    options like one_shot). Read-only, no auth needed — nothing sensitive
    here, just current state for the dashboard to render."""
    return _current_settings()


@app.post("/settings")
async def update_settings(update: SettingsUpdate, auth: Annotated[str | None, Header()] = None):
    """Update standing app-level toggles. Only fields present in the
    request body are changed. Takes effect immediately — settings are
    read fresh on every agent turn, no restart needed.

    timezone/digest_time also live-reschedule the daily_digest job, since
    it's registered with the scheduler as a fixed CronTrigger rather than
    being read fresh like the other settings.
    """
    if auth != os.environ["API_TOKEN"]:
        raise HTTPException(status_code=401, detail="Unauthorized request source")

    if update.learning_mode is not None:
        settings.learning_mode = update.learning_mode
    if update.default_location is not None:
        settings.default_location = update.default_location.strip()

    reschedule = update.timezone is not None or update.digest_time is not None
    if update.timezone is not None:
        settings.timezone = update.timezone
    if update.digest_time is not None:
        settings.digest_time = update.digest_time
    if reschedule:
        scheduler.reschedule_job("daily_digest", trigger=_digest_trigger())

    return _current_settings()


@app.post("/debug/digest")
async def trigger_digest_now(auth: Annotated[str | None, Header()] = None):
    """
    Manually fires today's digest immediately, without waiting for the
    20:45 schedule. Gated behind the same token as /voice since it sends
    a real email on every call — remove or comment this out once you're
    done testing the pipeline end to end.
    """
    if auth != os.environ["API_TOKEN"]:
        raise HTTPException(status_code=401, detail="Unauthorized request source")

    await send_daily_digest(app_state.memory)
    return {"status": "sent"}


@app.post("/debug/reconcile-vault")
async def trigger_reconcile_now(auth: Annotated[str | None, Header()] = None):
    """
    Manually forces a full vault reconciliation sweep — useful for
    confirming the notes index actually matches the vault on disk without
    waiting for the live watcher or an app restart.
    """
    if auth != os.environ["API_TOKEN"]:
        raise HTTPException(status_code=401, detail="Unauthorized request source")

    await reconcile_vault(app_state.memory)
    return {"status": "reconciled"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
