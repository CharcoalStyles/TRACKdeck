"""
voice.py
--------
Voice ingestion endpoint for the ESP32.

Default behavior (production): the device uploads audio and disconnects
immediately — it doesn't wait around for a reply, to avoid keeping wifi
(and the mic-button flow) alive any longer than needed. Transcription,
agent execution, and logging all happen in a background task *after* the
202 response has already been sent.

There is currently no feedback path back to the device on success or
failure in this mode:
  - Silence (no speech detected) is discarded quietly — not every button
    press should page anyone.
  - Real failures (transcription errors, agent/tool errors) are reported
    via Gotify — see utils/notify.py.
  - Successes are logged via agent.runtime.run_agent's existing
    save_conversation_summary call, and surfaced later in the end-of-day
    digest email (jobs/digest.py) rather than in the moment.

Two optional form fields, both testing conveniences — the ESP32 should
never set either in production:

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
"""
import asyncio
import os
import time
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    File,
)
from faster_whisper import WhisperModel

from agent.runtime import run_agent
from utils.notify import notify_error

API_TOKEN = os.environ["API_TOKEN"]
UPLOAD_DIR = "./received_notes"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter()

# Initialize the model strictly on CPU
# Options: "tiny", "base", "small", "medium", "large-v3"
whisper_model = WhisperModel("small", device="cpu", compute_type="int8")


async def _transcribe_and_run(audio_path: str, one_shot: bool) -> tuple[str, str]:
    """
    Transcribe the given audio file and run it through the agent.
    Returns (transcription, reply) — reply is "" if no speech was
    detected (not an error, just nothing to do). Raises on real failure;
    callers decide how to report that (Gotify for the fire-and-forget
    path, an HTTP error for the synchronous testing path).
    """
    segments, _ = whisper_model.transcribe(audio_path, beam_size=5)
    transcription = " ".join(segment.text for segment in segments).strip()

    if not transcription:
        return "", ""

    print(f"Transcribed '{audio_path}': {transcription}")
    reply = await run_agent(transcription, one_shot=one_shot)
    return transcription, reply


async def _process_voice_note(audio_path: str, one_shot: bool) -> None:
    """
    Background task (production path): fire-and-forget, reports failures
    via Gotify since there's no HTTP response left to report them in.
    """
    try:
        transcription, _ = await _transcribe_and_run(audio_path, one_shot)
        if not transcription:
            print(f"No speech detected in {audio_path} — discarding.")

    except Exception as e:
        print(f"⚠️ Voice pipeline failed for {audio_path}: {e}")
        await asyncio.to_thread(
            notify_error, f"Voice pipeline failed processing {audio_path}", e
        )


@router.post("/voice")
async def receive_note(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    one_shot: Annotated[bool, Form()] = False,
    sync: Annotated[bool, Form()] = False,
    auth: Annotated[str | None, Header()] = None,
):
    # 1. Enforce token security
    if auth != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized request source")

    # 2. Stream and write the raw audio chunk data from the ESP32
    timestamp = int(time.time())
    audio_path = os.path.join(UPLOAD_DIR, f"note_{timestamp}.wav")

    try:
        with open(audio_path, "wb") as f:
            f.write(await file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed writing audio: {str(e)}")

    # 3a. Testing path — wait for the full pipeline, return the result.
    if sync:
        try:
            transcription, reply = await _transcribe_and_run(audio_path, one_shot)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Voice pipeline failed: {str(e)}")

        if not transcription:
            return {"transcription": "", "reply": "(no speech detected)"}
        return {"transcription": transcription, "reply": reply}

    # 3b. Production path — hand off to the background task and respond
    #     immediately. The device doesn't wait for transcription, the
    #     agent, or anything else.
    background_tasks.add_task(_process_voice_note, audio_path, one_shot)
    return Response(status_code=202)
