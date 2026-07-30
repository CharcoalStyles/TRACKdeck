"""
Shared Whisper transcription — used by voice.py's ESP32/testing pipeline and
routes/transcribe.py's dashboard-facing transcription-only endpoint, so both
call the same model singleton and joining logic instead of duplicating it.
"""
from faster_whisper import WhisperModel

# Initialize the model strictly on CPU
# Options: "tiny", "base", "small", "medium", "large-v3"
whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")


def transcribe_audio(audio_path: str) -> str:
    """Transcribe the given audio file, returning the joined text (empty
    string if no speech was detected)."""
    segments, _ = whisper_model.transcribe(audio_path, beam_size=5)
    return " ".join(segment.text for segment in segments).strip()
