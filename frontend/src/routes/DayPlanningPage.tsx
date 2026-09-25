import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
type FixedBlockRow = { name: string; startTime: string; endTime: string }
type TaskLibraryItem = { id: string; label: string; default_minutes: number; group_name?: string | null }
type DayPlan = {
  id: string
  date: string
  start_time: string | null
  end_time: string | null
  notes: string | null
  status: string
  reply?: string | null
  trigger_at?: string | null
}

function formatTriggerAt(iso: string) {
  return new Date(iso).toLocaleString([], {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function DayPlanningPage() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const date = searchParams.get('date') || TODAY
  const [editingPlanId, setEditingPlanId] = useState<string | null>(null)
  const [tasks, setTasks] = useState<TaskRow[]>([{ task: '', minutes: '' }])
  const [fixedBlocks, setFixedBlocks] = useState<FixedBlockRow[]>([])
  const [notes, setNotes] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [status, setStatus] = useState<SaveState>('idle')
  const [reply, setReply] = useState<string | null>(null)
  const [scheduledMessage, setScheduledMessage] = useState<string | null>(null)

  function updateTask(i: number, field: keyof TaskRow, value: string) {
    setTasks((prev) => prev.map((t, idx) => (idx === i ? { ...t, [field]: value } : t)))
  }

  function updateFixedBlock(i: number, field: keyof FixedBlockRow, value: string) {
    setFixedBlocks((prev) => prev.map((b, idx) => (idx === i ? { ...b, [field]: value } : b)))
  }

  function resetForm() {
    setEditingPlanId(null)
    setTasks([{ task: '', minutes: '' }])
    setFixedBlocks([])
    setNotes('')
    setStartTime('')
    setEndTime('')
    setReply(null)
    setScheduledMessage(null)
  }

  const taskLibraryQuery = useQuery({
    queryKey: ['task-library'],
    queryFn: async () => {
      const { data } = await api.GET('/task-library')
      return data ?? []
    },
  })

  const upcomingPlansQuery = useQuery({
    queryKey: ['day-plans', 'upcoming'],
    queryFn: async () => {
      const { data } = await api.GET('/day-plans')
      return (data ?? []) as DayPlan[]
    },
  })

  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = {
        date,
        tasks: tasks.filter((t) => t.task.trim()).map((t) => ({ task: t.task.trim(), minutes: Number(t.minutes) || 30 })),
        fixed_blocks: fixedBlocks
          .filter((b) => b.name.trim() && b.startTime && b.endTime)
          .map((b) => ({ name: b.name.trim(), start_time: b.startTime, end_time: b.endTime })),
        notes: notes.trim() || null,
        start_time: startTime || null,
        end_time: endTime || null,
      }
      const { data, error } = editingPlanId
        ? await api.PUT('/day-plans/{plan_id}', { params: { path: { plan_id: editingPlanId } }, body })
        : await api.POST('/day-plans', { body })
      if (error) throw new Error()
      return data
    },
    onMutate: () => {
      setStatus('saving')
      setReply(null)
      setScheduledMessage(null)
    },
    onSuccess: (data) => {
      setStatus('saved')
      if (data?.reply) {
        setReply(data.reply)
      } else if (data?.trigger_at) {
        setScheduledMessage(`Scheduled — will build your schedule at ${formatTriggerAt(data.trigger_at)}.`)
      }
      queryClient.invalidateQueries({ queryKey: ['day-plans', 'upcoming'] })
      if (editingPlanId) resetForm()
    },
    onError: () => setStatus('error'),
  })

  const cancelPlanMutation = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.POST('/day-plans/{plan_id}/cancel', { params: { path: { plan_id: id } } })
      if (error) throw new Error()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['day-plans', 'upcoming'] }),
  })

  async function startEditing(plan: DayPlan) {
    const { data } = await api.GET('/day-plans/{plan_id}', { params: { path: { plan_id: plan.id } } })
    if (!data) return
    setEditingPlanId(plan.id)
    setSearchParams({ date: plan.date })
    setTasks(
      data.tasks.length ? data.tasks.map((t) => ({ task: t.task, minutes: String(t.minutes) })) : [{ task: '', minutes: '' }],
    )
    setFixedBlocks(data.fixed_blocks.map((b) => ({ name: b.name, startTime: b.start_time, endTime: b.end_time })))
    setNotes(data.notes ?? '')
    setStartTime(data.start_time ?? '')
    setEndTime(data.end_time ?? '')
    setReply(null)
    setScheduledMessage(null)
  }

  function addLibraryItem(item: TaskLibraryItem) {
    setTasks((prev) => [...prev, { task: item.label, minutes: String(item.default_minutes) }])
  }

  const hasTasks = tasks.some((t) => t.task.trim())
  const upcomingPlans = upcomingPlansQuery.data ?? []

  return (
    <div className="flex flex-col gap-4 w-full max-w-xl">
      <TaskLibraryCard items={taskLibraryQuery.data ?? []} onAdd={addLibraryItem} />

      <Card>
        <h2 className="mb-1 text-lg font-semibold">{editingPlanId ? 'Edit plan' : 'Plan my day'}</h2>
        <p className="mb-3 text-sm text-text-muted">
          List today's tasks with a time estimate, then build a schedule around your calendar.
        </p>
        {!editingPlanId && (
          <div className="mb-4 rounded border border-border bg-card-alt p-3 text-xs text-text-muted">
            <p className="mb-1 font-semibold text-text-primary">Two ways to use this:</p>
            <p className="mb-1">
              <strong>Set up now:</strong> add tasks below (with a rough time estimate each), then hit
              the button — they're saved to the day's planning note and, if the start time is now or
              already past, a schedule is built around your calendar straight away.
            </p>
            <p>
              <strong>Set up ahead of time:</strong> set a future start time (e.g. tomorrow at 09:00) —
              your tasks are saved now, but the actual schedule isn't built until 15 minutes before that
              time. It'll show up under Upcoming Plans below until then, where you can edit or cancel it.
            </p>
          </div>
        )}

        <div className="mb-3 flex flex-col gap-1">
          <label className="text-sm text-text-muted">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setSearchParams({ date: e.target.value })}
            className={inputClass}
            disabled={!!editingPlanId}
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
          it, like an evening. The "From" time (or wake time, if blank) also decides when the
          schedule actually gets built: 15 minutes beforehand.
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
          <label className="text-sm text-text-muted">Fixed blocks (time already spoken for)</label>
          <p className="-mt-1 mb-1 text-xs text-text-muted">
            e.g. "Work, 09:00 to 17:00" — counted as occupied like a calendar event, and added to
            the calendar itself if it isn't already there.
          </p>
          {fixedBlocks.map((b, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text"
                value={b.name}
                onChange={(e) => updateFixedBlock(i, 'name', e.target.value)}
                placeholder="e.g. Work"
                className={inputClass}
              />
              <input
                type="time"
                value={b.startTime}
                onChange={(e) => updateFixedBlock(i, 'startTime', e.target.value)}
                className={`${inputClass} w-32`}
              />
              <input
                type="time"
                value={b.endTime}
                onChange={(e) => updateFixedBlock(i, 'endTime', e.target.value)}
                className={`${inputClass} w-32`}
              />
              <button
                type="button"
                onClick={() => setFixedBlocks((prev) => prev.filter((_, idx) => idx !== i))}
                className={secondaryBtnClass}
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setFixedBlocks((prev) => [...prev, { name: '', startTime: '', endTime: '' }])}
            className={`${secondaryBtnClass} self-start`}
          >
            + Add fixed block
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

        <div className="flex gap-2">
          <button
            type="button"
            disabled={saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
            className={`${primaryBtnClass} disabled:opacity-50`}
          >
            {editingPlanId ? 'Save changes' : hasTasks ? 'Build my schedule' : 'Generate schedule from saved tasks'}
          </button>
          {editingPlanId && (
            <button type="button" onClick={resetForm} className={secondaryBtnClass}>
              Cancel edit
            </button>
          )}
        </div>
        {!editingPlanId && !hasTasks && (
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

      {scheduledMessage && (
        <Card>
          <p className="text-sm text-text-primary">{scheduledMessage}</p>
        </Card>
      )}

      <Card>
        <h2 className="mb-1 text-lg font-semibold">Upcoming Plans</h2>
        <p className="mb-3 text-sm text-text-muted">
          Plans queued up for a future date — nothing's generated yet, edit or cancel freely.
        </p>
        {upcomingPlans.length === 0 ? (
          <p className="text-sm text-text-muted">
            {upcomingPlansQuery.isPending ? 'Loading...' : 'No upcoming plans.'}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {upcomingPlans.map((plan) => (
              <div
                key={plan.id}
                className="flex items-center justify-between gap-2 rounded border border-border bg-card-alt p-3"
              >
                <div>
                  <p className="text-sm font-semibold">{plan.date}</p>
                  <p className="text-xs text-text-muted">
                    {plan.start_time ? `From ${plan.start_time}` : 'Whole day'}
                    {plan.end_time ? ` to ${plan.end_time}` : ''}
                    {plan.trigger_at ? ` — builds at ${formatTriggerAt(plan.trigger_at)}` : ''}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button type="button" onClick={() => startEditing(plan)} className={secondaryBtnClass}>
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => cancelPlanMutation.mutate(plan.id)}
                    className={secondaryBtnClass}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

function TaskLibraryCard({ items, onAdd }: { items: TaskLibraryItem[]; onAdd: (item: TaskLibraryItem) => void }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  const createMutation = useMutation({
    mutationFn: async (input: { label: string; default_minutes: number; group_name: string | null }) => {
      const { error } = await api.POST('/task-library', { body: input })
      if (error) throw new Error()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task-library'] })
      setCreating(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: async ({
      id,
      input,
    }: {
      id: string
      input: { label: string; default_minutes: number; group_name: string | null }
    }) => {
      const { error } = await api.PUT('/task-library/{item_id}', { params: { path: { item_id: id } }, body: input })
      if (error) throw new Error()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task-library'] })
      setEditingId(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE('/task-library/{item_id}', { params: { path: { item_id: id } } })
      if (error) throw new Error()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['task-library'] }),
  })

  const groups = new Map<string, TaskLibraryItem[]>()
  for (const item of items) {
    const key = item.group_name || 'Other'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(item)
  }

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Task Library</h2>
        <button type="button" onClick={() => setCreating(true)} className={secondaryBtnClass}>
          + New task
        </button>
      </div>
      {creating && (
        <TaskLibraryForm
          onCancel={() => setCreating(false)}
          onSave={(input) => createMutation.mutate(input)}
        />
      )}
      {items.length === 0 && !creating && (
        <p className="text-sm text-text-muted">No reusable tasks yet — add one above.</p>
      )}
      <div className="flex flex-col gap-3">
        {[...groups.entries()].map(([group, groupItems]) => (
          <div key={group}>
            <p className="mb-1 text-xs font-semibold uppercase text-text-muted">{group}</p>
            <div className="flex flex-col gap-2">
              {groupItems.map((item) =>
                editingId === item.id ? (
                  <TaskLibraryForm
                    key={item.id}
                    initial={item}
                    onCancel={() => setEditingId(null)}
                    onSave={(input) => updateMutation.mutate({ id: item.id, input })}
                    onDelete={() => deleteMutation.mutate(item.id)}
                  />
                ) : (
                  <div
                    key={item.id}
                    className="flex items-center justify-between gap-2 rounded border border-border bg-card-alt p-3"
                  >
                    <div>
                      <p className="text-sm font-semibold">{item.label}</p>
                      <p className="text-xs text-text-muted">{item.default_minutes} mins</p>
                    </div>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => onAdd(item)} className={secondaryBtnClass}>
                        Add
                      </button>
                      <button type="button" onClick={() => setEditingId(item.id)} className={secondaryBtnClass}>
                        Edit
                      </button>
                    </div>
                  </div>
                ),
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function TaskLibraryForm({
  initial,
  onSave,
  onCancel,
  onDelete,
}: {
  initial?: TaskLibraryItem
  onSave: (input: { label: string; default_minutes: number; group_name: string | null }) => void
  onCancel: () => void
  onDelete?: () => void
}) {
  const [label, setLabel] = useState(initial?.label ?? '')
  const [minutes, setMinutes] = useState(String(initial?.default_minutes ?? 20))
  const [group, setGroup] = useState(initial?.group_name ?? '')

  return (
    <div className="mb-3 rounded border border-border bg-card-alt p-3">
      <div className="mb-2 flex gap-2">
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="e.g. Clean the kitchen"
          className={inputClass}
        />
        <input
          type="number"
          min={1}
          value={minutes}
          onChange={(e) => setMinutes(e.target.value)}
          placeholder="Mins"
          className={`${inputClass} w-24`}
        />
      </div>
      <input
        type="text"
        value={group}
        onChange={(e) => setGroup(e.target.value)}
        placeholder="Group (optional, e.g. Chores)"
        className={`${inputClass} mb-2`}
      />
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() =>
            onSave({ label: label.trim(), default_minutes: Number(minutes) || 20, group_name: group.trim() || null })
          }
          disabled={!label.trim()}
          className={`${primaryBtnClass} disabled:opacity-50`}
        >
          Save
        </button>
        <button type="button" onClick={onCancel} className={secondaryBtnClass}>
          Cancel
        </button>
        {onDelete && (
          <button type="button" onClick={onDelete} className={secondaryBtnClass}>
            Delete
          </button>
        )}
      </div>
    </div>
  )
}
