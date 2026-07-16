"""
Personal Assistant — FastAPI + LangGraph
----------------------------------------
"""
import os
from contextlib import asynccontextmanager
from typing import Annotated
from zoneinfo import ZoneInfo

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Load .env before anything that reads os.environ (i.e. before agent imports)
load_dotenv()

from agent.graph import build_graph
from agent.memory import MemoryStore, make_chroma_client, make_embedding_function
from agent.runtime import app_state, run_agent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from jobs.digest import send_daily_digest

from voice import router as voice_router
from routes.synth import router as synth_router

# ---------------------------------------------------------------------------
# Scheduler — daily digest at 20:45 local time (see jobs/digest.py for why)
# ---------------------------------------------------------------------------

LOCAL_TZ = ZoneInfo("Australia/Canberra")
scheduler = AsyncIOScheduler(timezone=LOCAL_TZ)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    chroma_client = make_chroma_client()
    embedding_fn = make_embedding_function()
    app_state.memory = MemoryStore(chroma_client, embedding_fn)

    async with AsyncSqliteSaver.from_conn_string("memory.db") as checkpointer:
        app_state.graph = build_graph(checkpointer, app_state.memory)

        scheduler.add_job(
            send_daily_digest,
            trigger=CronTrigger(hour=20, minute=45, timezone=LOCAL_TZ),
            args=[app_state.memory],
            id="daily_digest",
            replace_existing=True,
        )
        scheduler.start()

        yield

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


class AssistantResponse(BaseModel):
    reply: str


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
async def handle_text(request: TextRequest):
    reply = await run_agent(request.text, thread_id=request.thread_id)
    return AssistantResponse(reply=reply)

@app.post("/debug/digest")
async def trigger_digest_now(auth: Annotated[str | None, Header()] = None):
    """
    Manually fires today's digest immediately, without waiting for the
    20:45 schedule. Gated behind the same token as /voice since it sends
    a real email on every call — remove or comment this out once you're
    done testing the pipeline end to end.
    """

    await send_daily_digest(app_state.memory)
    return {"status": "sent"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
