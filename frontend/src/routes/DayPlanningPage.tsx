import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

const TODAY = new Date().toISOString().slice(0, 10)

const inputClass =
  'w-full rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent'
const textareaClass = `${inputClass} min-h-16`
const secondaryBtnClass =
  'shrink-0 rounded-lg border border-border bg-card-alt px-3 py-2 text-sm text-text-primary hover:border-accent'
const primaryBtnClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover'

type TaskRow = { task: string; minutes: string }

function buildMessage(
  date: string,
  tasks: TaskRow[],
  notes: string,
  startTime: string,
  endTime: string,
): string {
  const lines = tasks
    .filter((t) => t.task.trim())
    .map((t, i) => `${i + 1}. ${t.task.trim()} — ${t.minutes || 30} mins`)
  const notesBlock = notes.trim()
    ? `\n\nGuidance on how to arrange these: ${notes.trim()}`
    : ''
  const windowBlock = startTime && endTime ? `\n\nSchedule window: ${startTime} to ${endTime}` : ''

  // No tasks typed here doesn't mean nothing to schedule — it usually
  // means they were already saved in an earlier session (e.g. the night
  // before) and this run is just the morning-of "go" trigger. Don't ask
  // the model to (re-)add anything in that case, just generate from
  // whatever's already in the note.
  if (lines.length === 0) {
    return (
      `Generate my schedule for ${date} from the tasks already saved in its planning note.` +
      `${notesBlock}${windowBlock}`
    )
  }

  return (
    `Plan my day for ${date}. Tasks:\n${lines.join('\n')}${notesBlock}${windowBlock}\n\n` +
    `Add each of these tasks to the planning note for ${date}, then generate my schedule for that day.`
  )
}

export default function DayPlanningPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const date = searchParams.get('date') || TODAY
  const [tasks, setTasks] = useState<TaskRow[]>([{ task: '', minutes: '' }])
  const [notes, setNotes] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [status, setStatus] = useState<SaveState>('idle')
  const [reply, setReply] = useState<string | null>(null)

  function updateTask(i: number, field: keyof TaskRow, value: string) {
    setTasks((prev) => prev.map((t, idx) => (idx === i ? { ...t, [field]: value } : t)))
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/text', {
        body: {
          text: buildMessage(date, tasks, notes, startTime, endTime),
          thread_id: `day_planning:${date}`,
          mode: 'day_planning',
          one_shot: true,
          agent_run: false,
        },
      })
      if (error) throw new Error()
      return data
    },
    onMutate: () => {
      setStatus('saving')
      setReply(null)
    },
    onSuccess: (data) => {
      setStatus('saved')
      setReply(data?.reply ?? null)
    },
    onError: () => setStatus('error'),
  })

  const hasTasks = tasks.some((t) => t.task.trim())

  return (
    <div className="flex flex-col gap-4 w-full max-w-xl">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Plan my day</h2>
        <p className="mb-3 text-sm text-text-muted">
          List today's tasks with a time estimate, then build a schedule around your calendar.
        </p>
        <div className="mb-4 rounded border border-border bg-card-alt p-3 text-xs text-text-muted">
          <p className="mb-1 font-semibold text-text-primary">Two ways to use this:</p>
          <p className="mb-1">
            <strong>Set up now:</strong> add tasks below (with a rough time estimate each), then hit
            the button — they're saved to the day's planning note and a schedule is built around
            your calendar straight away.
          </p>
          <p>
            <strong>Set up the night before, go in the morning:</strong> add tasks now but come back
            tomorrow before running it — or leave every task row blank, set a "From" time, and hit
            the button to schedule whatever's already saved for that date without adding anything
            new. Good for a quick "start my day" trigger once tasks are already in place.
          </p>
        </div>

        <div className="mb-3 flex flex-col gap-1">
          <label className="text-sm text-text-muted">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setSearchParams({ date: e.target.value })}
            className={inputClass}
          />
        </div>

        <div className="mb-3 flex gap-2">
          <div className="flex flex-1 flex-col gap-1">
            <label className="text-sm text-text-muted">From (optional)</label>
            <input
              type="time"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className={inputClass}
            />
          </div>
          <div className="flex flex-1 flex-col gap-1">
            <label className="text-sm text-text-muted">Until (optional)</label>
            <input
              type="time"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className={inputClass}
            />
          </div>
        </div>
        <p className="mb-3 -mt-2 text-xs text-text-muted">
          Leave blank to plan the whole day (wake time to bedtime) — set both to plan just part of
          it, like an evening.
        </p>

        <div className="mb-3 flex flex-col gap-1">
          <label className="text-sm text-text-muted">Tasks</label>
          {tasks.map((t, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text"
                value={t.task}
                onChange={(e) => updateTask(i, 'task', e.target.value)}
                placeholder="e.g. Kitchen dishes"
                className={inputClass}
              />
              <input
                type="number"
                min={1}
                value={t.minutes}
                onChange={(e) => updateTask(i, 'minutes', e.target.value)}
                placeholder="Mins"
                className={`${inputClass} w-24`}
              />
              <button
                type="button"
                onClick={() => setTasks((prev) => prev.filter((_, idx) => idx !== i))}
                className={secondaryBtnClass}
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setTasks((prev) => [...prev, { task: '', minutes: '' }])}
            className={`${secondaryBtnClass} self-start`}
          >
            + Add task
          </button>
        </div>

        <div className="mb-3 flex flex-col gap-1">
          <label className="text-sm text-text-muted">Anything else to consider?</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. Put shopping after my lunch break"
            className={textareaClass}
          />
        </div>

        <button
          type="button"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
          className={`${primaryBtnClass} disabled:opacity-50`}
        >
          {hasTasks ? 'Build my schedule' : 'Generate schedule from saved tasks'}
        </button>
        {!hasTasks && (
          <p className="mt-1 text-xs text-text-muted">
            No tasks entered here — this will schedule whatever's already saved in {date}'s
            planning note (e.g. from a previous session) instead of adding anything new.
          </p>
        )}
        <SaveStatus state={status} />
      </Card>

      {reply && (
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-text-muted">Schedule</h2>
          <pre className="mb-3 whitespace-pre-wrap rounded border border-border bg-card-alt p-3 text-sm">
            {reply}
          </pre>
          <Link to={`/reflection?date=${date}`} className="text-sm text-accent hover:underline">
            View planning note &amp; log reflection →
          </Link>
        </Card>
      )}
    </div>
  )
}
