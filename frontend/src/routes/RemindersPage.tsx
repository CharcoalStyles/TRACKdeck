import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

function formatDue(epochSeconds: number) {
  return new Date(epochSeconds * 1000).toLocaleString([], {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// <input type="datetime-local"> wants "YYYY-MM-DDTHH:MM" in the browser's
// local time — the assistant's system prompt already grounds voice/chat
// reminders in the user's local timezone the same way.
function toDatetimeLocalValue(epochSeconds: number) {
  const d = new Date(epochSeconds * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function RemindersPage() {
  const queryClient = useQueryClient()
  const [editingIds, setEditingIds] = useState<Set<string>>(new Set())
  const [status, setStatus] = useState<SaveState>('idle')

  const remindersQuery = useQuery({
    queryKey: ['reminders'],
    queryFn: async () => {
      const { data } = await api.GET('/reminders')
      return data?.reminders ?? []
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE('/reminders/{reminder_id}', {
        params: { path: { reminder_id: id } },
      })
      if (error) throw new Error()
    },
    onMutate: () => setStatus('saving'),
    onSuccess: () => {
      setStatus('idle')
      queryClient.invalidateQueries({ queryKey: ['reminders'] })
    },
    onError: () => setStatus('error'),
  })

  const updateMutation = useMutation({
    mutationFn: async ({ id, message, dueAt }: { id: string; message: string; dueAt: string }) => {
      const { error } = await api.PATCH('/reminders/{reminder_id}', {
        params: { path: { reminder_id: id } },
        body: { message, due_at: dueAt },
      })
      if (error) throw new Error()
    },
    onMutate: () => setStatus('saving'),
    onSuccess: (_, { id }) => {
      setStatus('idle')
      setEditingIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      queryClient.invalidateQueries({ queryKey: ['reminders'] })
    },
    onError: () => setStatus('error'),
  })

  const reminders = remindersQuery.data ?? []

  return (
    <div className="flex flex-col gap-4 w-full">
      <Card className='w-full'>
        <h2 className="mb-1 text-lg font-semibold">Upcoming To-Dos</h2>
        <p className="mb-3 text-sm text-text-muted">
          Reminders you've set via voice or chat — edit or cancel them here.
        </p>
        <button
          type="button"
          onClick={() => queryClient.invalidateQueries({ queryKey: ['reminders'] })}
          className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent"
        >
          Refresh
        </button>
        <SaveStatus state={status} />
      </Card>

      {reminders.length === 0 ? (
        <Card>
          <p className="text-sm text-text-muted">
            {remindersQuery.isPending ? 'Loading...' : 'No upcoming to-dos.'}
          </p>
        </Card>
      ) : (
        reminders.map((reminder) =>
          editingIds.has(reminder.id) ? (
            <EditCard
              key={reminder.id}
              message={reminder.message}
              dueAt={toDatetimeLocalValue(reminder.due_at)}
              onCancel={() =>
                setEditingIds((prev) => {
                  const next = new Set(prev)
                  next.delete(reminder.id)
                  return next
                })
              }
              onSave={(message, dueAt) => updateMutation.mutate({ id: reminder.id, message, dueAt })}
            />
          ) : (
            <Card key={reminder.id}>
              <h2 className="mb-1 text-lg font-semibold">{reminder.message}</h2>
              <p className="mb-3 text-sm text-text-muted">Due {formatDue(reminder.due_at)}</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setEditingIds((prev) => new Set(prev).add(reminder.id))}
                  className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate(reminder.id)}
                  className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent"
                >
                  Delete
                </button>
              </div>
            </Card>
          ),
        )
      )}
    </div>
  )
}

function EditCard({
  message: initialMessage,
  dueAt: initialDueAt,
  onSave,
  onCancel,
}: {
  message: string
  dueAt: string
  onSave: (message: string, dueAt: string) => void
  onCancel: () => void
}) {
  const [message, setMessage] = useState(initialMessage)
  const [dueAt, setDueAt] = useState(initialDueAt)

  return (
    <Card>
      <div className="mb-3 flex flex-col gap-1">
        <label className="text-sm text-text-muted">Message</label>
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
        />
      </div>
      <div className="mb-3 flex flex-col gap-1">
        <label className="text-sm text-text-muted">Due</label>
        <input
          type="datetime-local"
          value={dueAt}
          onChange={(e) => setDueAt(e.target.value)}
          className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
        />
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onSave(message, dueAt)}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover"
        >
          Save
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent"
        >
          Cancel
        </button>
      </div>
    </Card>
  )
}
