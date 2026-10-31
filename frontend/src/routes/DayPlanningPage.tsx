import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

// Local date, not toISOString(): that is the UTC date, which is yesterday in the
// morning for anyone east of Greenwich.
const TODAY = new Date().toLocaleDateString('en-CA')

const inputClass =
  'w-full rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent'
const textareaClass = `${inputClass} min-h-16`
const secondaryBtnClass =
  'shrink-0 rounded-lg border border-border bg-card-alt px-3 py-2 text-sm text-text-primary hover:border-accent'
const primaryBtnClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover'

type TaskRow = { task: string; minutes: string; after: string }
type FixedBlockRow = { name: string; startTime: string; endTime: string }
type TaskLibraryItem = {
  id: string
  label: string
  default_minutes: number
  group_name?: string | null
  order_hint?: string | null
}
type TaskLibraryInput = { label: string; default_minutes: number; group_name: string | null; order_hint: string | null }

export default function DayPlanningPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const date = searchParams.get('date') || TODAY
  const [tasks, setTasks] = useState<TaskRow[]>([{ task: '', minutes: '', after: '' }])
  const [fixedBlocks, setFixedBlocks] = useState<FixedBlockRow[]>([])
  const [notes, setNotes] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [status, setStatus] = useState<SaveState>('idle')
  const [reply, setReply] = useState<string | null>(null)

  function updateTask(i: number, field: keyof TaskRow, value: string) {
    setTasks((prev) => prev.map((t, idx) => (idx === i ? { ...t, [field]: value } : t)))
  }

  function updateFixedBlock(i: number, field: keyof FixedBlockRow, value: string) {
    setFixedBlocks((prev) => prev.map((b, idx) => (idx === i ? { ...b, [field]: value } : b)))
  }

  const taskLibraryQuery = useQuery({
    queryKey: ['task-library'],
    queryFn: async () => {
      const { data } = await api.GET('/task-library')
      return data ?? []
    },
  })

  const runMutation = useMutation({
    mutationFn: async () => {
      const body = {
        date,
        tasks: tasks.filter((t) => t.task.trim()).map((t) => ({ task: t.task.trim(), minutes: Number(t.minutes) || 30, after: t.after.trim() || null })),
        fixed_blocks: fixedBlocks
          .filter((b) => b.name.trim() && b.startTime && b.endTime)
          .map((b) => ({ name: b.name.trim(), start_time: b.startTime, end_time: b.endTime })),
        notes: notes.trim() || null,
        start_time: startTime || null,
        end_time: endTime || null,
      }
      const { data, error } = await api.POST('/day-plans/run', { body })
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
      setTasks([{ task: '', minutes: '', after: '' }])
      setFixedBlocks([])
    },
    onError: () => setStatus('error'),
  })

  function addLibraryItem(item: TaskLibraryItem) {
    setTasks((prev) => [...prev, { task: item.label, minutes: String(item.default_minutes), after: '' }])
  }

  const hasTasks = tasks.some((t) => t.task.trim())

  return (
    <div className="flex flex-col gap-4 w-full max-w-xl">
      <TaskLibraryCard items={taskLibraryQuery.data ?? []} onAdd={addLibraryItem} />

      <Card>
        <h2 className="mb-1 text-lg font-semibold">Plan my day</h2>
        <p className="mb-3 text-sm text-text-muted">
          List today's tasks with a time estimate, then build a schedule around your calendar.
        </p>
        <p className="mb-4 text-xs text-text-muted">
          Add tasks (with a rough time estimate each) and hit the button — they're saved to the
          day's planning note and a schedule is built around your calendar straight away. Leave the
          task list empty to schedule whatever's already saved in that day's note.
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
          Blank start means wake time, blank end means bedtime. Long tasks are split into 15–25 minute
          sprints with shuffled order and 5–15 minute breaks.
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
              <input
                type="text"
                value={t.after}
                onChange={(e) => updateTask(i, 'after', e.target.value)}
                placeholder="After task… (optional)"
                className={`${inputClass} w-48`}
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
            onClick={() => setTasks((prev) => [...prev, { task: '', minutes: '', after: '' }])}
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

        <button
          type="button"
          disabled={runMutation.isPending}
          onClick={() => runMutation.mutate()}
          className={`${primaryBtnClass} disabled:opacity-50`}
        >
          {runMutation.isPending ? 'Building...' : hasTasks ? 'Build my schedule' : 'Build from saved tasks'}
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

function TaskLibraryCard({ items, onAdd }: { items: TaskLibraryItem[]; onAdd: (item: TaskLibraryItem) => void }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  const createMutation = useMutation({
    mutationFn: async (input: TaskLibraryInput) => {
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
      input: TaskLibraryInput
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
                      <p className="text-xs text-text-muted">
                        {item.default_minutes} mins{item.order_hint ? ` — ${item.order_hint}` : ''}
                      </p>
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
  onSave: (input: TaskLibraryInput) => void
  onCancel: () => void
  onDelete?: () => void
}) {
  const [label, setLabel] = useState(initial?.label ?? '')
  const [minutes, setMinutes] = useState(String(initial?.default_minutes ?? 20))
  const [group, setGroup] = useState(initial?.group_name ?? '')
  const [orderHint, setOrderHint] = useState(initial?.order_hint ?? '')

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
      <input
        type="text"
        value={orderHint}
        onChange={(e) => setOrderHint(e.target.value)}
        placeholder='Order hint (optional, e.g. "before Shower" or "after Dishes")'
        className={`${inputClass} mb-2`}
      />
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() =>
            onSave({
              label: label.trim(),
              default_minutes: Number(minutes) || 20,
              group_name: group.trim() || null,
              order_hint: orderHint.trim() || null,
            })
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
