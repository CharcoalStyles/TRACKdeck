"""
voice.py
--------
Fire-and-forget voice ingestion endpoint for the ESP32.

The device uploads audio and disconnects immediately — it doesn't wait
around for a reply, to avoid keeping wifi (and the mic-button flow) alive
any longer than needed. Transcription, agent execution, and logging all
happen in a background task *after* the 202 response has already been
sent.

There is currently no feedback path back to the device on success or
failure:
  - Silence (no speech detected) is discarded quietly — not every button
    press should page anyone.
  - Real failures (transcription errors, agent/tool errors) are reported
    via Gotify — see utils/notify.py.
  - Successes are logged via agent.runtime.run_agent's existing
    save_conversation_summary call, and surfaced later in the end-of-day
    digest email (jobs/digest.py) rather than in the moment.
"""
import asyncio
import os
import time
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Response, UploadFile, File
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


async def _process_voice_note(audio_path: str) -> None:
    """
    Background task: transcribe, run the agent, and let run_agent's own
    logging handle recording the result. Runs after the HTTP response has
    already gone back to the device, so any failure here is reported via
    Gotify rather than in an HTTP response — there's no one still listening.
    """
    try:
        segments, _ = whisper_model.transcribe(audio_path, beam_size=5)
        transcription = " ".join(segment.text for segment in segments).strip()

        if not transcription:
            print(f"No speech detected in {audio_path} — discarding.")
            return

        print(f"Transcribed '{audio_path}': {transcription}")
        await run_agent(transcription)

    except Exception as e:
        print(f"⚠️ Voice pipeline failed for {audio_path}: {e}")
        await asyncio.to_thread(
            notify_error, f"Voice pipeline failed processing {audio_path}", e
        )


@router.post("/voice", status_code=202)
async def receive_note(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
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

    # 3. Hand off to the background task and respond immediately — the
    #    device doesn't wait for transcription/agent/anything else.
    background_tasks.add_task(_process_voice_note, audio_path)

    return Response(status_code=202)
