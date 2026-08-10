import os
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

import auth
from voice import UPLOAD_DIR
from utils.transcription import transcribe_audio

router = APIRouter()


class TranscribeResponse(BaseModel):
    transcription: str


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    _: Annotated[None, Depends(auth.require_session_or_token)],
    file: UploadFile = File(...),
):
    """
    Transcription-only endpoint for the dashboard's chat inputs: no agent
    turn, no thread/checkin routing — just speech-to-text, so the frontend
    can feed the result into the same /text call a typed message would use.
    """
    timestamp = int(time.time())
    audio_path = os.path.join(UPLOAD_DIR, f"dictation_{timestamp}.webm")

    try:
        with open(audio_path, "wb") as f:
            f.write(await file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed writing audio: {str(e)}")

    try:
        transcription = transcribe_audio(audio_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

    return {"transcription": transcription}
