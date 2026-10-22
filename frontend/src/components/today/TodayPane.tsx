import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import Card from '../Card'
import type { components } from '../../api/schema'

type DayEvent = components['schemas']['TodayEvent']

const inputClass = 'rounded border border-border bg-card-alt px-2 py-1 text-sm text-text-primary'
const smallBtn = 'rounded border border-border bg-card-alt px-2 py-1 text-xs hover:border-accent'
const sectionTitle = 'mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted'

function errorText(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  return typeof detail === 'string' ? detail : 'Something went wrong.'
}

function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T12:00:00`)
  d.setDate(d.getDate() + days)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// An end time at or before the start means the event runs past midnight.
function endStamp(date: string, start: string, end: string): string {
  return `${end <= start ? shiftDate(date, 1) : date} ${end}`
}

interface EventFormValues {
  title: string
  start: string
  end: string
  location: string
}

function EventForm({
  initial,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
  idPrefix,
}: {
  initial: EventFormValues
  submitLabel: string
  pending: boolean
  error: string | null
  onSubmit: (values: EventFormValues) => void
  onCancel: () => void
  idPrefix: string
}) {
  const [values, setValues] = useState(initial)
  const set = (key: keyof EventFormValues) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [key]: e.target.value }))

  function submit(e: FormEvent) {
    e.preventDefault()
    if (values.title.trim() && values.start) onSubmit(values)
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 rounded border border-border p-2">
      <input
        id={`${idPrefix}-title`}
        value={values.title}
        onChange={set('title')}
        placeholder="Title"
        autoFocus
        className={inputClass}
      />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <input id={`${idPrefix}-start`} type="time" value={values.start} onChange={set('start')} className={inputClass} aria-label="Start" />
        <span className="text-text-muted">to</span>
        <input id={`${idPrefix}-end`} type="time" value={values.end} onChange={set('end')} className={inputClass} aria-label="End (blank = one hour)" />
        <input
          id={`${idPrefix}-location`}
          value={values.location}
          onChange={set('location')}
          placeholder="Where (optional)"
          className={`${inputClass} grow`}
        />
      </div>
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={pending || !values.title.trim() || !values.start}
          className="rounded bg-accent px-3 py-1 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
        >
          {pending ? 'Saving…' : submitLabel}
        </button>
        <button type="button" onClick={onCancel} className={smallBtn}>Cancel</button>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
    </form>
  )
}

function EventRow({ event, date, onChanged }: { event: DayEvent; date: string; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const initial: EventFormValues = {
    title: event.title,
    start: event.start,
    end: event.end ?? '',
    location: event.location,
  }

  const save = useMutation({
    mutationFn: async (v: EventFormValues) => {
      const body: { title?: string; start?: string; end?: string; location?: string } = {}
      if (v.title !== initial.title) body.title = v.title
      if (v.start !== initial.start) body.start = `${date} ${v.start}`
      if (v.end !== initial.end && v.end) body.end = endStamp(date, v.start, v.end)
      if (v.location !== initial.location) body.location = v.location
      if (Object.keys(body).length === 0) return
      const { error } = await api.PATCH('/calendar-events/{uid}', { params: { path: { uid: event.uid! } }, body })
      if (error) throw new Error(errorText(error))
    },
    onSuccess: () => {
      setEditing(false)
      setMessage(null)
      onChanged()
    },
    onError: (e: Error) => setMessage(e.message),
  })

  const remove = useMutation({
    mutationFn: async () => {
      const { error } = await api.DELETE('/calendar-events/{uid}', { params: { path: { uid: event.uid! } } })
      if (error) throw new Error(errorText(error))
    },
    onSuccess: onChanged,
    onError: (e: Error) => setMessage(e.message),
  })

  if (editing) {
    return (
      <li>
        <EventForm
          idPrefix={`ev-${event.uid}`}
          initial={initial}
          submitLabel="Save"
          pending={save.isPending}
          error={message}
          onSubmit={(v) => save.mutate(v)}
          onCancel={() => { setEditing(false); setMessage(null) }}
        />
      </li>
    )
  }

  return (
    <li className="flex flex-col gap-0.5">
      <div className="flex gap-3">
        <span className="w-24 shrink-0 tabular-nums text-text-muted">
          {event.start}
          {event.end ? `–${event.end}` : ''}
        </span>
        <span className="grow break-words">
          {event.title}
          {event.location && <span className="text-text-muted"> · {event.location}</span>}
          {event.generated && <span className="ml-2 rounded bg-card-alt px-1 text-xs text-text-faint">planned block</span>}
          {event.repeats && <span className="ml-2 rounded bg-card-alt px-1 text-xs text-text-faint">repeats</span>}
        </span>
        {event.uid && (
          <span className="flex shrink-0 gap-1">
            {!event.repeats && <button type="button" onClick={() => setEditing(true)} className={smallBtn}>Edit</button>}
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() => { if (window.confirm(`Delete “${event.title}”?`)) remove.mutate() }}
              className={smallBtn}
            >
              Delete
            </button>
          </span>
        )}
      </div>
      {message && <p className="ml-24 text-xs text-red-400">{message}</p>}
    </li>
  )
}

export default function TodayPane() {
  const queryClient = useQueryClient()
  const [date, setDate] = useState<string | undefined>(undefined)
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)

  const query = useQuery({
    queryKey: ['today', date ?? 'now'],
    queryFn: async () => {
      const { data } = await api.GET('/today', { params: { query: date ? { date } : {} } })
      return data
    },
    refetchInterval: 60_000,
  })
  const day = query.data
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['today'] })
  const go = (target: string) => {
    setDate(target)
    setAdding(false)
  }

  const add = useMutation({
    mutationFn: async (v: EventFormValues) => {
      const viewed = day!.date
      const { error } = await api.POST('/calendar-events', {
        body: {
          title: v.title,
          start: `${viewed} ${v.start}`,
          end: v.end ? endStamp(viewed, v.start, v.end) : undefined,
          location: v.location || undefined,
        },
      })
      if (error) throw new Error(errorText(error))
    },
    onSuccess: () => {
      setAdding(false)
      setAddError(null)
      refresh()
    },
    onError: (e: Error) => setAddError(e.message),
  })

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">
            {day ? (day.is_today ? `Today, ${day.weekday}` : day.weekday) : 'Today'}
          </h2>
          {day && <p className="text-sm tabular-nums text-text-muted">{day.date}</p>}
        </div>
        <div className="flex items-center gap-1">
          <button type="button" disabled={!day} onClick={() => day && go(shiftDate(day.date, -1))} className={smallBtn} aria-label="Previous day">
            ←
          </button>
          <input
            id="today-date"
            type="date"
            value={day?.date ?? ''}
            onChange={(e) => e.target.value && go(e.target.value)}
            className={inputClass}
            aria-label="Jump to date"
          />
          <button type="button" disabled={!day} onClick={() => day && go(shiftDate(day.date, 1))} className={smallBtn} aria-label="Next day">
            →
          </button>
          {day && !day.is_today && (
            <button type="button" onClick={() => { setDate(undefined); setAdding(false) }} className={smallBtn}>
              Today
            </button>
          )}
        </div>
      </div>
      {query.isPending && <p className="text-sm text-text-muted">Loading…</p>}
      {query.isError && <p className="text-sm text-red-400">Could not load this day.</p>}
      {day && (
        <>
          <section>
            <h3 className={`${sectionTitle} flex items-baseline justify-between`}>
              Calendar
              {!adding && (
                <button type="button" onClick={() => setAdding(true)} className="font-normal normal-case text-accent hover:underline">
                  Add event
                </button>
              )}
            </h3>
            {adding && (
              <div className="mb-2">
                <EventForm
                  idPrefix="ev-new"
                  initial={{ title: '', start: '', end: '', location: '' }}
                  submitLabel="Add"
                  pending={add.isPending}
                  error={addError}
                  onSubmit={(v) => add.mutate(v)}
                  onCancel={() => { setAdding(false); setAddError(null) }}
                />
              </div>
            )}
            {day.events.length === 0 ? (
              <p className="text-sm text-text-faint">Nothing scheduled.</p>
            ) : (
              <ul className="flex flex-col gap-1 text-sm">
                {day.events.map((e) => (
                  <EventRow key={e.uid ?? `${e.start}-${e.title}`} event={e} date={day.date} onChanged={refresh} />
                ))}
              </ul>
            )}
          </section>
          <section>
            <h3 className={`${sectionTitle} flex items-baseline justify-between`}>
              Reminders
              <Link to="/reminders" className="font-normal normal-case text-accent hover:underline">
                All
              </Link>
            </h3>
            {day.reminders.length === 0 ? (
              <p className="text-sm text-text-faint">{day.is_today ? 'None left today.' : 'None on this day.'}</p>
            ) : (
              <ul className="flex flex-col gap-1 text-sm">
                {day.reminders.map((r) => (
                  <li key={r.id} className="flex gap-3">
                    <span className="w-24 shrink-0 tabular-nums text-text-muted">{r.time}</span>
                    <span className="break-words">{r.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {day.checkins.length > 0 && (
            <section>
              <h3 className={sectionTitle}>Check-ins</h3>
              <ul className="flex flex-col gap-2 text-sm">
                {day.checkins.map((c, i) => (
                  <li key={`${c.time}-${i}`}>
                    <p className="text-text-muted">
                      <span className="tabular-nums">{c.time}</span> {c.prompt}
                    </p>
                    <p className="whitespace-pre-wrap break-words">{c.answer}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </Card>
  )
}
