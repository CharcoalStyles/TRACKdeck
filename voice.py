"""
voice.py
--------
Voice ingestion endpoint for the ESP32.

Default behavior (production): the device uploads audio and disconnects
immediately — it doesn't wait around for a reply, to avoid keeping wifi
(and the mic-button flow) alive any longer than needed. Transcription,
agent execution, and logging all happen in a background task *after* the
202 response has already been sent.

There is no HTTP feedback path back to the device in this mode — but
that's not the only way you find out what happened:
  - Silence (no speech detected) is discarded quietly — not every button
    press should page anyone.
  - Real failures (transcription errors, agent/tool errors) are reported
    via Gotify at high priority — see utils/notify.py.
  - Successes push a low-priority Gotify notification too (see
    agent.runtime.run_agent), tagged with that turn's thread keyword —
    e.g. "Copper Wolf, ..." — and are surfaced again in the end-of-day
    digest email (jobs/digest.py).

Every reply belongs to a thread, addressable later by a two-word keyword
("Copper Wolf, actually make that 3pm") regardless of how long ago the
original request happened — see agent/runtime.py and agent/keywords.py.
Without a keyword prefix, the usual short inactivity window decides
whether a request continues the most recent thread or starts a new one.

Two optional form fields are testing conveniences — the ESP32 should never
set either in production:

  one_shot: forces the agent into one-shot mode (see agent/graph.py's
    ONE_SHOT_ADDENDUM) — no ending on a clarifying question, since real
    hardware has no way to hear a follow-up. Useful to test *before* the
    ESP32 exists, using the browser test page's mic button instead.

  sync: waits for the full pipeline (transcribe + agent) and returns the
    transcription and reply directly as JSON, instead of the normal
    fire-and-forget 202. This exists purely so the webpage can show you
    the result while testing — setting it defeats the entire point of
    the fire-and-forget design (the caller has to hold the connection
    open for as long as the agent takes to respond), so it must stay a
    manual, opt-in testing path, never something real hardware sends.

A third optional field, checkin_id, IS meant for real hardware: it tags a
reply as answering a specific mental-health check-in prompt
(jobs/checkin.py) the device just displayed, so the reply is routed to
that check-in's own thread (agent.runtime.run_agent's explicit thread_id
path) instead of being resolved by keyword/recency, and the check-in gets
marked answered.
"""
import asyncio
import logging
import os
import time
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Response,
    UploadFile,
    File,
)
from faster_whisper import WhisperModel

import auth
from jobs import checkin as checkin_jobs
from agent.runtime import run_agent
from utils.notify import notify_error

logger = logging.getLogger(__name__)

UPLOAD_DIR = "./received_notes"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter()

# Initialize the model strictly on CPU
# Options: "tiny", "base", "small", "medium", "large-v3"
whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")


async def _transcribe_and_run(
    audio_path: str, one_shot: bool, checkin_id: str | None = None
) -> tuple[str, str, str]:
    """
    Transcribe the given audio file and run it through the agent.
    Returns (transcription, reply, keyword) — reply/keyword are "" if no
    speech was detected (not an error, just nothing to do). Raises on
    real failure; callers decide how to report that (Gotify for the
    fire-and-forget path, an HTTP error for the synchronous testing path).

    checkin_id, when set, tags this as an answer to a specific
    jobs/checkin.py mental-health check-in prompt: the reply is routed to
    that check-in's own thread instead of resolved by keyword/recency, and
    the check-in is marked answered.
    """
    segments, _ = whisper_model.transcribe(audio_path, beam_size=5)
    transcription = " ".join(segment.text for segment in segments).strip()

    if not transcription:
        return "", "", ""

    logger.info("Transcribed '%s': %s", audio_path, transcription)

    if checkin_id is not None:
        # Stale/unresolvable checkin_id (e.g. it expired server-side while
        # the device was recording) doesn't drop the user's spoken reply —
        # answer_checkin already logs and returns None, so we just fall
        # through to normal resolution below.
        result = await checkin_jobs.answer_checkin(checkin_id, transcription)
        if result is not None:
            return transcription, result.reply, result.keyword

    result = await run_agent(transcription, one_shot=one_shot)
    return transcription, result.reply, result.keyword


async def _process_voice_note(audio_path: str, one_shot: bool, checkin_id: str | None = None) -> None:
    """
    Background task (production path): fire-and-forget, reports failures
    via Gotify since there's no HTTP response left to report them in.
    """
    try:
        transcription, _, _ = await _transcribe_and_run(audio_path, one_shot, checkin_id)
        if not transcription:
            logger.info("No speech detected in %s — discarding.", audio_path)

    except Exception as e:
        logger.error("Voice pipeline failed for %s: %s", audio_path, e)
        await asyncio.to_thread(
            notify_error, f"Voice pipeline failed processing {audio_path}", e
        )


@router.post("/voice")
async def receive_note(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(auth.require_device_token)] = None,
    file: UploadFile = File(...),
    one_shot: Annotated[bool, Form()] = False,
    sync: Annotated[bool, Form()] = False,
    checkin_id: Annotated[str | None, Form()] = None,
):
    # 1. Stream and write the raw audio chunk data from the ESP32
    timestamp = int(time.time())
    audio_path = os.path.join(UPLOAD_DIR, f"note_{timestamp}.wav")

    try:
        with open(audio_path, "wb") as f:
            f.write(await file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed writing audio: {str(e)}")

    # 2a. Testing path — wait for the full pipeline, return the result.
    if sync:
        try:
            transcription, reply, keyword = await _transcribe_and_run(audio_path, one_shot, checkin_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Voice pipeline failed: {str(e)}")

        if not transcription:
            return {"transcription": "", "reply": "(no speech detected)", "keyword": ""}
        return {"transcription": transcription, "reply": reply, "keyword": keyword}

    # 2b. Production path — hand off to the background task and respond
    #     immediately. The device doesn't wait for transcription, the
    #     agent, or anything else.
    background_tasks.add_task(_process_voice_note, audio_path, one_shot, checkin_id)
    return Response(status_code=202)


@router.post("/checkin/{checkin_id}/voice")
async def receive_checkin_voice(checkin_id: str, file: UploadFile = File(...)):
    """
    Magic-link voice reply for static/checkin.html — gated only by
    possessing this check-in's own id, not API_TOKEN (see
    jobs/checkin.py's answer_checkin docstring for the trust model).
    Unlike /voice, a stale/unresolvable id is a hard 409, never a fallback
    to a live conversation thread — there is no authenticated caller to
    trust here.
    """
    timestamp = int(time.time())
    audio_path = os.path.join(UPLOAD_DIR, f"checkin_{timestamp}.wav")
    try:
        with open(audio_path, "wb") as f:
            f.write(await file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed writing audio: {str(e)}")

    segments, _ = whisper_model.transcribe(audio_path, beam_size=5)
    transcription = " ".join(segment.text for segment in segments).strip()
    if not transcription:
        return {"transcription": "", "reply": ""}

    result = await checkin_jobs.answer_checkin(checkin_id, transcription)
    if result is None:
        raise HTTPException(status_code=409, detail="Check-in is no longer awaiting a reply")
    return {"transcription": transcription, "reply": result.reply}
