"""
utils/tts.py
-------------
Text to speech for the morning podcast: Piper voices loaded lazily by name from
.models/, one WAV-less PCM stream per line, joined and encoded to MP3 by ffmpeg.
routes/synth.py keeps its own single voice for the device; this is separate so
a missing podcast voice can never take the app down at import.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_DIR = Path(".models")
FALLBACK_VOICE = "en_US-lessac-medium"
TARGET_RATE = 22050
PAUSE_SECONDS = 0.35

_voices: dict[str, object] = {}
_lock = threading.Lock()


def voice_available(name: str) -> bool:
    return (MODEL_DIR / f"{name}.onnx").exists()


def _load(name: str):
    from piper import PiperVoice

    with _lock:
        if name not in _voices:
            path = MODEL_DIR / f"{name}.onnx"
            _voices[name] = PiperVoice.load(str(path), config_path=str(f"{path}.json"))
        return _voices[name]


def resolve_voice(name: str) -> str:
    if voice_available(name):
        return name
    logger.warning("Podcast voice %s not found in %s; using %s", name, MODEL_DIR, FALLBACK_VOICE)
    return FALLBACK_VOICE


def synthesize_pcm(text: str, voice_name: str) -> tuple[bytes, int]:
    """(16-bit mono PCM, sample rate) for one piece of text."""
    voice = _load(resolve_voice(voice_name))
    pcm = b"".join(bytes(chunk.audio_int16_bytes) for chunk in voice.synthesize(text))
    return pcm, voice.config.sample_rate


def _resample(pcm: bytes, rate: int) -> bytes:
    if rate == TARGET_RATE:
        return pcm
    result = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-",
         "-f", "s16le", "-ar", str(TARGET_RATE), "-ac", "1", "-"],
        input=pcm, capture_output=True, check=True,
    )
    return result.stdout


def render_mp3(turns: list[tuple[str, str]], voices: dict[str, str], out_path: Path, title: str) -> float:
    """Speak (speaker, text) turns with each speaker's voice and write one MP3.
    Returns its duration in seconds."""
    silence = b"\x00\x00" * int(TARGET_RATE * PAUSE_SECONDS)
    parts: list[bytes] = []
    for speaker, text in turns:
        pcm, rate = synthesize_pcm(text, voices.get(speaker) or next(iter(voices.values())))
        parts.append(_resample(pcm, rate))
        parts.append(silence)
    audio = b"".join(parts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(TARGET_RATE), "-ac", "1", "-i", "-",
         "-codec:a", "libmp3lame", "-b:a", "64k", "-metadata", f"title={title}", "-metadata", "artist=trackdeck",
         str(tmp)],
        input=audio, capture_output=True, check=True,
    )
    tmp.replace(out_path)
    return len(audio) / 2 / TARGET_RATE
