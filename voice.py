import os
import time
from typing import Annotated
from fastapi import APIRouter, Header, HTTPException, UploadFile, File
from faster_whisper import WhisperModel

API_TOKEN = os.environ["API_TOKEN"]
UPLOAD_DIR = "./received_notes"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter()

# Initialize the model strictly on CPU
# Options: "tiny", "base", "small", "medium", "large-v3"
whisper_model = WhisperModel("small", device="cpu", compute_type="int8")


@router.post("/voice")
async def receive_note(file: UploadFile = File(...), auth: Annotated[str | None, Header()] = None):
    # 1. Enforce Token Security
    print(auth)
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

    # 3. Process transcription locally via faster-whisper
    print(f"Transcribing audio file: {audio_path}")
    start_time = time.time()
    
    segments, info = whisper_model.transcribe(audio_path, beam_size=5)
    transcription = " ".join([segment.text for segment in segments]).strip()
    
    duration = time.time() - start_time
    print(f"Transcription completed in {duration:.2f}s: '{transcription}'")

    if not transcription:
        return {"status": "ignored", "reason": "No speech detected in audio stream"}
    
    return {"status": "success", "transcription": transcription}