import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'

type Kind = 'reminder' | 'event' | 'task'

interface CaptureItem {
  id: string
  time: string
  text: string
  done: boolean
  source?: string | null
  via?: string | null
}

const inputClass = 'rounded border border-border bg-card-alt px-2 py-1 text-sm text-text-primary'
const smallBtn = 'rounded border border-border bg-card-alt px-2 py-1 text-xs hover:border-accent'

function dayLabel(date: string) {
  const d = new Date(`${date}T12:00:00`)
  return d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })
}

// "2026-10-23T15:00" from <input type="datetime-local"> → the "YYYY-MM-DD HH:MM" the backend parses.
const toWhen = (value: string) => value.replace('T', ' ')

function errorText(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  return typeof detail === 'string' ? detail : 'Something went wrong.'
}

function CaptureRow({ date, item, onChanged }: { date: string; item: CaptureItem; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(item.text)
  const [converting, setConverting] = useState(false)
  const [kind, setKind] = useState<Kind>('reminder')
  const [when, setWhen] = useState('')
  const [minutes, setMinutes] = useState(30)
  const [message, setMessage] = useState<string | null>(null)
  const path = { date_str: date, capture_id: item.id }

  const patch = useMutation({
    mutationFn: async (body: { text?: string; done?: boolean }) => {
      const { error } = await api.PATCH('/captures/{date_str}/{capture_id}', { params: { path }, body })
      if (error) throw new Error(errorText(error))
    },
    onSuccess: () => {
      setEditing(false)
      onChanged()
    },
    onError: (e: Error) => setMessage(e.message),
  })

  const convert = useMutation({
    mutationFn: async () => {
      const body =
        kind === 'task'
          ? { to: kind, minutes, when: when ? when.slice(0, 10) : undefined }
          : { to: kind, when: toWhen(when) }
      const { error } = await api.POST('/captures/{date_str}/{capture_id}/convert', { params: { path }, body })
      if (error) throw new Error(errorText(error))
    },
    onSuccess: () => {
      setConverting(false)
      setMessage(null)
      onChanged()
    },
    onError: (e: Error) => setMessage(e.message),
  })

  const remove = useMutation({
    mutationFn: async () => {
      const { error } = await api.DELETE('/captures/{date_str}/{capture_id}', { params: { path } })
      if (error) throw new Error(errorText(error))
    },
    onSuccess: onChanged,
    onError: (e: Error) => setMessage(e.message),
  })

  function saveEdit(e: FormEvent) {
    e.preventDefault()
    if (draft.trim() && draft.trim() !== item.text) patch.mutate({ text: draft })
    else setEditing(false)
  }

  return (
    <li className="flex flex-col gap-1 border-b border-border py-2 last:border-b-0">
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          id={`cap-${item.id}`}
          checked={item.done}
          onChange={(e) => patch.mutate({ done: e.target.checked })}
          className="mt-1"
          aria-label="Done"
        />
        <span className="mt-0.5 shrink-0 text-xs tabular-nums text-text-faint">{item.time}</span>
        {item.source === 'voice' && (
          <span
            className="mt-0.5 shrink-0 rounded bg-card-alt px-1 text-xs text-text-muted"
            title={item.via === 'fallback' ? 'Heard by voice but not understood as a request, so it was saved here automatically.' : 'Said by voice.'}
          >
            {item.via === 'fallback' ? 'from voice · auto-saved' : 'from voice'}
          </span>
        )}
        {editing ? (
          <form onSubmit={saveEdit} className="flex grow flex-wrap gap-2">
            <input
              id={`cap-edit-${item.id}`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoFocus
              className={`${inputClass} grow`}
            />
            <button type="submit" className={smallBtn}>Save</button>
            <button type="button" onClick={() => { setEditing(false); setDraft(item.text) }} className={smallBtn}>
              Cancel
            </button>
          </form>
        ) : (
          <span className={`grow break-words text-sm ${item.done ? 'text-text-faint line-through' : ''}`}>
            {item.text}
          </span>
        )}
        {!editing && (
          <span className="flex shrink-0 gap-1">
            <button type="button" onClick={() => setEditing(true)} className={smallBtn}>Edit</button>
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() => { if (window.confirm('Delete this capture?')) remove.mutate() }}
              className={smallBtn}
            >
              Delete
            </button>
            {!item.done && (
              <button type="button" onClick={() => setConverting((v) => !v)} className={smallBtn}>
                Convert
              </button>
            )}
          </span>
        )}
      </div>
      {converting && (
        <div className="ml-6 flex flex-wrap items-center gap-2 text-sm">
          <select
            id={`cap-kind-${item.id}`}
            value={kind}
            onChange={(e) => setKind(e.target.value as Kind)}
            className={inputClass}
          >
            <option value="reminder">Reminder</option>
            <option value="event">Calendar event</option>
            <option value="task">Planning task</option>
          </select>
          <input
            id={`cap-when-${item.id}`}
            type={kind === 'task' ? 'date' : 'datetime-local'}
            value={kind === 'task' ? when.slice(0, 10) : when}
            onChange={(e) => setWhen(e.target.value)}
            className={inputClass}
            aria-label={kind === 'task' ? 'Day (defaults to the capture’s day)' : 'When'}
          />
          {kind === 'task' && (
            <input
              id={`cap-min-${item.id}`}
              type="number"
              min={5}
              step={5}
              value={minutes}
              onChange={(e) => setMinutes(Number(e.target.value) || 30)}
              className={`${inputClass} w-20`}
              aria-label="Minutes"
            />
          )}
          <button
            type="button"
            disabled={convert.isPending || (kind !== 'task' && !when)}
            onClick={() => convert.mutate()}
            className="rounded bg-accent px-3 py-1 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {convert.isPending ? 'Converting…' : 'Create'}
          </button>
        </div>
      )}
      {message && <p className="ml-6 text-xs text-red-400">{message}</p>}
    </li>
  )
}

export default function CapturesList({ days, showAdd = true }: { days: number; showAdd?: boolean }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState('')

  const query = useQuery({
    queryKey: ['captures', days],
    queryFn: async () => {
      const { data } = await api.GET('/captures', { params: { query: { days } } })
      return data
    },
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['captures'] })

  const add = useMutation({
    mutationFn: async (value: string) => {
      const { error } = await api.POST('/captures', { body: { text: value } })
      if (error) throw new Error(errorText(error))
    },
    onSuccess: () => {
      setText('')
      refresh()
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (text.trim() && !add.isPending) add.mutate(text)
  }

  const data = query.data
  return (
    <div className="flex flex-col gap-3">
      {showAdd && (
        <form onSubmit={submit} className="flex gap-2">
          <input
            id="capture-new"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Jot something down…"
            className={`${inputClass} grow py-2`}
          />
          <button
            type="submit"
            disabled={add.isPending || !text.trim()}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
          >
            Add
          </button>
        </form>
      )}
      {add.isError && <p className="text-sm text-red-400">Could not save that capture.</p>}
      {query.isPending && <p className="text-sm text-text-muted">Loading…</p>}
      {query.isError && <p className="text-sm text-red-400">Could not load captures.</p>}
      {data?.days.map((day) => (
        <section key={day.date}>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
            {dayLabel(day.date)}
          </h3>
          {day.captures.length === 0 ? (
            <p className="text-sm text-text-faint">Nothing captured yet.</p>
          ) : (
            <ul>
              {day.captures.map((c) => (
                <CaptureRow key={c.id} date={day.date} item={c} onChanged={refresh} />
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  )
}
