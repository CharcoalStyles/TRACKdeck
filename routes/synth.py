import os
import io
import time
import wave
import base64
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from piper import PiperVoice

import auth

# You can add global prefixes or tags here
router = APIRouter()

# Update paths to your downloaded model files
MODEL_PATH = ".models/en_US-lessac-medium.onnx"
CONFIG_PATH = ".models/en_US-lessac-medium.onnx.json"

# CPU-bound synthesis cost scales with input length, and this route has no
# rate limiting — cap it so a single request can't tie up the synthesis
# thread indefinitely.
MAX_TEXT_LENGTH = 2000

# Load the model into memory at startup
if not os.path.exists(MODEL_PATH):
    raise RuntimeError(f"Model file not found at {MODEL_PATH}")

voice = PiperVoice.load(MODEL_PATH, config_path=CONFIG_PATH)

class TTSRequest(BaseModel):
    text: str

class TTSResponse(BaseModel):
    text: str
    audio_base64: str
    media_type: str
    sample_rate: int
    generation_time: float

@router.post("/synthesize", response_model=TTSResponse)
async def synthesize_text_json(
    request: TTSRequest, _: Annotated[None, Depends(auth.require_device_token)]
):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    if len(request.text) > MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Text too long ({len(request.text)} chars, max {MAX_TEXT_LENGTH}).",
        )

    try:
        start = time.time()
        # 1. Create an in-memory stream for the WAV construction
        wav_buffer = io.BytesIO()
        
        # 2. Open standard wave structures using our buffer
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)          # Mono channel
            wav_file.setsampwidth(2)         # 16-bit depth (2 bytes per sample)
            wav_file.setframerate(voice.config.sample_rate)
            
            # 3. Write raw PCM chunk yields into the WAV buffer

            for chunk in voice.synthesize(request.text):
                # Explicitly cast chunk.raw_data into native Python bytes
                wav_file.writeframes(bytes(chunk.audio_int16_bytes))
        
        # 4. Pull out the binary data from the start of the buffer
        wav_bytes = wav_buffer.getvalue()
        
        # 5. Convert raw bytes into a web-safe Base64 string wrapper
        base64_audio = base64.b64encode(wav_bytes).decode("utf-8")

        end = time.time()
        
        # 6. Deliver the full context payload
        return TTSResponse(
            text=request.text,
            audio_base64=base64_audio,
            media_type="audio/wav",
            sample_rate=voice.config.sample_rate,
            generation_time=end - start
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))