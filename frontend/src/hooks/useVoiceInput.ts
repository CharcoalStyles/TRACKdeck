import { useRef, useState } from 'react'
import { api } from '../api/client'
import { Recorder } from '../lib/voiceInput'

type VoiceState = 'idle' | 'recording' | 'transcribing'

// Mirrors static/js/voiceInput.js's attachVoiceButton() as a hook:
// click while idle -> start recording, click while recording -> stop +
// upload to /transcribe + resolve with the transcript text (possibly "").
export function useVoiceInput() {
  const [state, setState] = useState<VoiceState>('idle')
  const recorderRef = useRef<Recorder>(new Recorder())

  async function toggle(): Promise<string | null> {
    const recorder = recorderRef.current

    if (recorder.isRecording) {
      setState('transcribing')
      try {
        const blob = await recorder.stop()
        const formData = new FormData()
        formData.append('file', blob, 'dictation.webm')
        const { data, error } = await api.POST('/transcribe', {
          body: formData as never,
        })
        if (error || !data) throw new Error('Transcription failed')
        return data.transcription
      } finally {
        setState('idle')
      }
    }

    try {
      await recorder.start()
      setState('recording')
      return null
    } catch {
      setState('idle')
      throw new Error('Could not access the microphone')
    }
  }

  return { state, toggle }
}
