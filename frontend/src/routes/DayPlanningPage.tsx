import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

const TODAY = new Date().toISOString().slice(0, 10)

const inputClass =
  'w-full rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent'
const secondaryBtnClass =
  'shrink-0 rounded-lg border border-border bg-card-alt px-3 py-2 text-sm text-text-primary hover:border-accent'
const primaryBtnClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover'

type TaskRow = { task: string; minutes: string }

function buildMessage(date: string, tasks: TaskRow[]): string {
  const lines = tasks
    .filter((t) => t.task.trim())
    .map((t, i) => `${i + 1}. ${t.task.trim()} — ${t.minutes || 30} mins`)
  return (
    `Plan my day for ${date}. Tasks:\n${lines.join('\n')}\n\n` +
    `Add each of these tasks to the planning note for ${date}, then generate my schedule for that day.`
  )
}

export default function DayPlanningPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const date = searchParams.get('date') || TODAY
  const [tasks, setTasks] = useState<TaskRow[]>([{ task: '', minutes: '' }])
  const [status, setStatus] = useState<SaveState>('idle')
  const [reply, setReply] = useState<string | null>(null)

  function updateTask(i: number, field: keyof TaskRow, value: string) {
    setTasks((prev) => prev.map((t, idx) => (idx === i ? { ...t, [field]: value } : t)))
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/text', {
        body: {
          text: buildMessage(date, tasks),
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

        <div className="mb-3 flex flex-col gap-1">
          <label className="text-sm text-text-muted">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setSearchParams({ date: e.target.value })}
            className={inputClass}
          />
        </div>

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

        <button
          type="button"
          disabled={!hasTasks || mutation.isPending}
          onClick={() => mutation.mutate()}
          className={`${primaryBtnClass} disabled:opacity-50`}
        >
          Build my schedule
        </button>
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
