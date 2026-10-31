"""
routes/podcast.py
------------------
The morning podcast on the dashboard: list episodes, stream an MP3, read a
script, and start a run on demand. Paths are /podcasts/... (the dashboard page
itself is /podcast, which the SPA catch-all serves).
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth
from agent.settings import settings
from jobs import podcast

router = APIRouter()


class EpisodeInfo(BaseModel):
    date: str
    has_script: bool


class PodcastList(BaseModel):
    episodes: list[EpisodeInfo]  # newest first
    running: bool
    has_samples: bool = False
    error: str | None = None


class ScriptResponse(BaseModel):
    date: str
    script: str


class RunResponse(BaseModel):
    status: str


def _parse_day(date_str: str) -> date:
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such episode")


@router.get("/podcasts", response_model=PodcastList)
async def list_podcasts(_: Annotated[None, Depends(auth.require_session_or_token)]):
    days = sorted((p.stem for p in podcast.podcast_dir().glob("????-??-??.mp3")), reverse=True)
    return {
        "episodes": [{"date": d, "has_script": podcast.script_path(date.fromisoformat(d)).exists()} for d in days],
        "running": podcast.STATE["running"],
        "has_samples": podcast.samples_path().exists(),
        "error": podcast.STATE["error"],
    }


@router.post("/podcasts/run", response_model=RunResponse)
async def run_podcast_now(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """Starts today's episode in the background (it takes minutes) and
    returns at once; poll GET /podcasts for `running`."""
    if podcast.STATE["running"]:
        raise HTTPException(status_code=409, detail="A podcast is already being made")

    async def _run():
        try:
            await podcast.run_podcast(refresh=True)
        except Exception:
            pass  # recorded in STATE and notified

    asyncio.create_task(_run())
    return {"status": "started"}


@router.get("/podcasts/voice-samples.mp3")
async def get_voice_samples(_: Annotated[None, Depends(auth.require_session_or_token)]):
    if not podcast.samples_path().exists():
        raise HTTPException(status_code=404, detail="No voice samples")
    return FileResponse(podcast.samples_path(), media_type="audio/mpeg")


@router.get("/podcasts/{date_str}.mp3")
async def get_podcast_audio(date_str: str, _: Annotated[None, Depends(auth.require_session_or_token)]):
    path = podcast.mp3_path(_parse_day(date_str))
    if not path.exists():
        raise HTTPException(status_code=404, detail="No such episode")
    return FileResponse(path, media_type="audio/mpeg")


@router.get("/podcasts/{date_str}/script", response_model=ScriptResponse)
async def get_podcast_script(date_str: str, _: Annotated[None, Depends(auth.require_session_or_token)]):
    path = podcast.script_path(_parse_day(date_str))
    if not path.exists():
        raise HTTPException(status_code=404, detail="No script for that day")
    return {"date": date_str, "script": path.read_text(encoding="utf-8")}
