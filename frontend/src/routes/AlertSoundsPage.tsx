import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

function formatSize(bytes: number) {
  return `${(bytes / 1024).toFixed(0)} KB`
}
function formatDate(epochSeconds: number) {
  return new Date(epochSeconds * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

export default function AlertSoundsPage() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [status, setStatus] = useState<SaveState>('idle')
  const [errorMessage, setErrorMessage] = useState<string | undefined>()

  const soundsQuery = useQuery({
    queryKey: ['alert-sounds'],
    queryFn: async () => {
      const { data } = await api.GET('/alert-sounds')
      return data?.alert_sounds ?? []
    },
  })

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData()
      formData.append('file', file, file.name)
      const { error } = await api.POST('/alert-sounds', { body: formData as never })
      if (error) throw new Error((error as { detail?: string })?.detail || 'Upload failed.')
    },
    onMutate: () => setStatus('saving'),
    onSuccess: () => {
      setStatus('saved')
      if (fileInputRef.current) fileInputRef.current.value = ''
      queryClient.invalidateQueries({ queryKey: ['alert-sounds'] })
    },
    onError: (err: Error) => {
      setErrorMessage(err.message)
      setStatus('error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE('/alert-sounds/{sound_id}', { params: { path: { sound_id: id } } })
      if (error) throw new Error()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-sounds'] }),
  })

  function handleUpload() {
    const file = fileInputRef.current?.files?.[0]
    if (!file) {
      setErrorMessage('Choose a file first.')
      setStatus('error')
      return
    }
    uploadMutation.mutate(file)
  }

  const sounds = soundsQuery.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Upload Alert Sound</h2>
        <p className="mb-3 text-sm text-text-muted">
          Upload an MP3 or WAV clip — it's converted to the 16kHz/16-bit mono PCM WAV the ESP32-S3
          needs, then picked up automatically on the device's next sync. Clips over 30s are
          rejected.
        </p>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input ref={fileInputRef} type="file" accept="audio/*" className="text-sm text-text-muted" />
          <button
            type="button"
            onClick={handleUpload}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover"
          >
            Upload &amp; Convert
          </button>
        </div>
        <SaveStatus state={status} errorMessage={errorMessage} />
      </Card>

      {sounds.length === 0 ? (
        <Card>
          <p className="text-sm text-text-muted">
            {soundsQuery.isPending ? 'Loading...' : 'No alert sounds uploaded yet.'}
          </p>
        </Card>
      ) : (
        sounds.map((sound) => (
          <Card key={sound.id}>
            <h2 className="mb-1 text-lg font-semibold">{sound.display_name}</h2>
            <p className="mb-3 text-sm text-text-muted">
              {sound.duration_seconds.toFixed(1)}s · {formatSize(sound.size_bytes)} · added{' '}
              {formatDate(sound.created_at)}
            </p>
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <audio controls src={`/alert-sounds/${sound.id}/audio`} className="mb-3 w-full" />
            <button
              type="button"
              onClick={() => deleteMutation.mutate(sound.id)}
              disabled={deleteMutation.isPending}
              className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm text-danger hover:border-danger disabled:opacity-50"
            >
              Delete
            </button>
          </Card>
        ))
      )}
    </div>
  )
}
