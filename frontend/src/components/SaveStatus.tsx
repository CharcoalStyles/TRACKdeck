export type SaveState = 'idle' | 'saving' | 'saved' | 'error'

interface SaveStatusProps {
  state: SaveState
  errorMessage?: string
  savedMessage?: string
}

export default function SaveStatus({ state, errorMessage, savedMessage = 'Saved.' }: SaveStatusProps) {
  if (state === 'idle') return null
  const text = state === 'saving' ? 'Saving...' : state === 'saved' ? savedMessage : errorMessage || 'Failed to save.'
  const color = state === 'saving' ? 'text-text-muted' : state === 'saved' ? 'text-accent' : 'text-danger'
  return <div className={`mt-2 text-sm ${color}`}>{text}</div>
}
