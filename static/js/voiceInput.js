// static/js/voiceInput.js
//
// Shared browser mic-recording primitives. Two layers:
//   - Recorder: bare getUserMedia/MediaRecorder wrapper, no network calls —
//     safe to use even on pages with no session (e.g. checkin.html).
//   - transcribeAudio / attachVoiceButton: convenience layer for pages that
//     want to record + POST /transcribe + get text back, using the session
//     cookie (no device-token dance needed, unlike POST /voice).

export class Recorder {
  constructor() {
    this._mediaRecorder = null;
    this._stream = null;
    this._chunks = [];
  }

  get isRecording() {
    return this._mediaRecorder !== null && this._mediaRecorder.state === 'recording';
  }

  async start() {
    this._chunks = [];
    this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this._mediaRecorder = new MediaRecorder(this._stream, { mimeType: 'audio/webm' });
    this._mediaRecorder.addEventListener('dataavailable', (event) => {
      if (event.data.size > 0) this._chunks.push(event.data);
    });
    this._mediaRecorder.start();
  }

  /** Stops recording and resolves with the recorded audio Blob. */
  stop() {
    return new Promise((resolve) => {
      this._mediaRecorder.addEventListener('stop', () => {
        this._stream.getTracks().forEach((track) => track.stop());
        resolve(new Blob(this._chunks, { type: 'audio/webm' }));
      }, { once: true });
      this._mediaRecorder.stop();
    });
  }
}

/** Uploads a recorded blob to POST /transcribe and returns the transcription
 * text (possibly ""  when no speech was detected). */
export async function transcribeAudio(blob) {
  const formData = new FormData();
  formData.append('file', blob, 'dictation.webm');

  const response = await fetch('/transcribe', {
    method: 'POST',
    credentials: 'same-origin',
    body: formData,
  });
  if (!response.ok) throw new Error(`Server returned ${response.status}`);

  const data = await response.json();
  return data.transcription;
}

/** Wires click-to-record-and-transcribe behavior onto an existing button
 * element. Cycles idle -> recording -> transcribing -> idle, calling
 * onTranscript(text) on success (text may be "") or onError(err) on
 * mic/network failure. */
export function attachVoiceButton(buttonEl, { onTranscript, onError } = {}) {
  const recorder = new Recorder();

  buttonEl.addEventListener('click', async () => {
    if (recorder.isRecording) {
      buttonEl.disabled = true;
      buttonEl.classList.remove('recording');
      buttonEl.classList.add('transcribing');
      try {
        const blob = await recorder.stop();
        const text = await transcribeAudio(blob);
        if (onTranscript) onTranscript(text);
      } catch (err) {
        if (onError) onError(err);
      } finally {
        buttonEl.classList.remove('transcribing');
        buttonEl.disabled = false;
      }
      return;
    }

    try {
      await recorder.start();
      buttonEl.classList.add('recording');
    } catch (err) {
      if (onError) onError(err);
    }
  });
}
