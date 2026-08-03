"""
routes/alert_sounds.py
------------------------
Upload/manage the WAV alert-sound library the ESP32-S3 picks a random
file from when nudging about a to-do. Any ffmpeg-decodable upload
(mp3/wav/m4a/...) is converted to exactly what the firmware needs —
16kHz/16-bit mono PCM WAV — and catalogued in utils/alert_sounds_store.py.

Delivery to the device is metadata-first: jobs/device_sync.py folds the
full current library (id/hash/size/duration/url) into every
POST /device/sync response, and the device is expected to diff that
against what it already has on its SD card, fetching only new/changed
files via the /device/alert-sounds/{id} route below and deleting
anything no longer listed. That keeps the recurring poll cheap (pure
JSON metadata) and confines the actual audio transfer to the rare wake
where a file was actually added or changed — see
jobs/device_sync.py's docstring and the plan this shipped from for the
full reasoning.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
import time
import uuid
import wave
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

import auth
from utils import alert_sounds_store

logger = logging.getLogger(__name__)

router = APIRouter()

# Sanity guard against an accidentally-huge upload (e.g. a whole song)
# creating an outsized one-off WiFi window on the device — not a storage
# limit, storage isn't a constraint here. Trivially adjustable.
MAX_DURATION_SECONDS = 30.0


def _convert_to_pcm_wav(input_path: str, output_path: str) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", "16000",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            "-hide_banner", "-loglevel", "error",
            output_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Audio conversion failed: {result.stderr.strip() or 'unknown ffmpeg error'}",
        )


def _wav_duration_seconds(path: str) -> float:
    with wave.open(path, "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


def _sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.post("/alert-sounds")
async def upload_alert_sound(
    _: Annotated[None, Depends(auth.require_session_or_token)],
    file: UploadFile = File(...),
):
    _, suffix = os.path.splitext(file.filename or "")
    raw_fd, raw_path = tempfile.mkstemp(suffix=suffix or ".bin")
    # Same directory as the final destination so the os.replace() below is a
    # same-device rename — /tmp is a separate filesystem from the bind-mounted
    # ALERT_SOUNDS_DIR in Docker, which makes cross-device os.replace() fail.
    converted_fd, converted_path = tempfile.mkstemp(
        suffix=".wav", dir=alert_sounds_store.ALERT_SOUNDS_DIR
    )
    os.close(raw_fd)
    os.close(converted_fd)

    try:
        with open(raw_path, "wb") as f:
            f.write(await file.read())

        _convert_to_pcm_wav(raw_path, converted_path)

        duration_seconds = _wav_duration_seconds(converted_path)
        if duration_seconds > MAX_DURATION_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f"Alert sound is {duration_seconds:.1f}s, longer than the "
                f"{MAX_DURATION_SECONDS:.0f}s cap.",
            )

        sound_id = str(uuid.uuid4())
        size_bytes = os.path.getsize(converted_path)
        sha256 = _sha256_of(converted_path)
        display_name = file.filename or "alert-sound.wav"

        os.replace(converted_path, alert_sounds_store.audio_path(sound_id))
        alert_sounds_store.create_sound(
            sound_id, display_name, duration_seconds, size_bytes, sha256, int(time.time())
        )

        return alert_sounds_store.get_sound(sound_id)
    finally:
        for path in (raw_path, converted_path):
            if os.path.exists(path):
                os.remove(path)


@router.get("/alert-sounds")
async def list_alert_sounds(_: Annotated[None, Depends(auth.require_session_or_token)]):
    return {"alert_sounds": alert_sounds_store.list_sounds()}


@router.delete("/alert-sounds/{sound_id}")
async def delete_alert_sound(
    sound_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    sound = alert_sounds_store.get_sound(sound_id)
    if sound is None:
        raise HTTPException(status_code=404, detail="Alert sound not found")

    path = alert_sounds_store.audio_path(sound_id)
    if os.path.exists(path):
        os.remove(path)
    alert_sounds_store.delete_sound(sound_id)
    return {"status": "deleted"}


@router.get("/alert-sounds/{sound_id}/audio")
async def preview_alert_sound(
    sound_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    sound = alert_sounds_store.get_sound(sound_id)
    if sound is None:
        raise HTTPException(status_code=404, detail="Alert sound not found")
    return FileResponse(alert_sounds_store.audio_path(sound_id), media_type="audio/wav")


@router.get("/device/alert-sounds/{sound_id}")
async def fetch_alert_sound(
    sound_id: str, _: Annotated[None, Depends(auth.require_device_token)]
):
    """
    Fetched by the ESP32-S3 exactly once per new/changed file, after it
    diffs the `alert_sounds` manifest in POST /device/sync's response
    against what it already has on its SD card.
    """
    sound = alert_sounds_store.get_sound(sound_id)
    if sound is None:
        raise HTTPException(status_code=404, detail="Alert sound not found")
    return FileResponse(alert_sounds_store.audio_path(sound_id), media_type="audio/wav")
