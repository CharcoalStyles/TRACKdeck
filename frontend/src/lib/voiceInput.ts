// Bare getUserMedia/MediaRecorder wrapper, no network calls — ported
// near-verbatim from static/js/voiceInput.js's Recorder class.
export class Recorder {
  private mediaRecorder: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private chunks: Blob[] = []

  get isRecording(): boolean {
    return this.mediaRecorder !== null && this.mediaRecorder.state === 'recording'
  }

  async start(): Promise<void> {
    this.chunks = []
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    this.mediaRecorder = new MediaRecorder(this.stream, { mimeType: 'audio/webm' })
    this.mediaRecorder.addEventListener('dataavailable', (event) => {
      if (event.data.size > 0) this.chunks.push(event.data)
    })
    this.mediaRecorder.start()
  }

  stop(): Promise<Blob> {
    return new Promise((resolve) => {
      this.mediaRecorder!.addEventListener(
        'stop',
        () => {
          this.stream!.getTracks().forEach((track) => track.stop())
          resolve(new Blob(this.chunks, { type: 'audio/webm' }))
        },
        { once: true },
      )
      this.mediaRecorder!.stop()
    })
  }
}
