import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
import MoodChart from '../components/activity-log/MoodChart'
import DurationChart from '../components/activity-log/DurationChart'
import { ACTIVITY_COLORS } from '../components/activity-log/activityColors'

const ACTIVITY_TYPES = ['Meal', 'Exercise', 'Project Work', 'Socializing', 'Rest']

function formatDateTime(epochSeconds: number) {
  return new Date(epochSeconds * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

export default function ActivityLogPage() {
  const [days, setDays] = useState(30)
  const [activityType, setActivityType] = useState('')

  const logQuery = useQuery({
    queryKey: ['activity-log', days, activityType],
    queryFn: async () => {
      const { data } = await api.GET('/activity-log', {
        params: { query: { days, activity_type: activityType || undefined } },
      })
      return data?.entries ?? []
    },
  })

  const summaryQuery = useQuery({
    queryKey: ['activity-log-summary', days],
    queryFn: async () => {
      const { data } = await api.GET('/activity-log/summary', { params: { query: { days } } })
      return data
    },
  })

  const entries = logQuery.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Activity Log</h2>
        <p className="mb-3 text-sm text-text-muted">
          A structured record of meals, exercise, project work, socializing, and rest — logged by
          talking to the assistant. Read-only here; log new entries through chat or voice.
        </p>
        <div className="flex flex-wrap gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <select
            value={activityType}
            onChange={(e) => setActivityType(e.target.value)}
            className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary"
          >
            <option value="">All types</option>
            {ACTIVITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </Card>

      <Card>
        <h2 className="mb-3 text-lg font-semibold">Mood / Energy Over Time</h2>
        <MoodChart moodByDay={summaryQuery.data?.mood_by_day ?? []} />
      </Card>

      <Card>
        <h2 className="mb-3 text-lg font-semibold">Time by Activity Type</h2>
        <DurationChart durationByType={summaryQuery.data?.duration_by_type ?? []} />
      </Card>

      {entries.length === 0 ? (
        <Card>
          <p className="text-sm text-text-muted">
            {logQuery.isPending
              ? 'Loading...'
              : 'No activity logged in this range yet — try telling the assistant about something you did.'}
          </p>
        </Card>
      ) : (
        entries.map((entry) => {
          const hasDetail = Boolean(entry.duration) || entry.mood_energy !== null || Boolean(entry.reflection)
          const detailParts = [
            entry.duration || null,
            entry.mood_energy !== null ? `mood/energy ${entry.mood_energy}/10` : null,
          ].filter(Boolean)
          return (
            <Card key={entry.id}>
              <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: ACTIVITY_COLORS[entry.activity_type] || '#888' }}
                />
                {entry.activity_type} — {formatDateTime(entry.occurred_at)}
              </h2>
              <p className={`text-sm text-text-muted ${hasDetail ? 'mb-2' : ''}`}>{entry.subject}</p>
              {detailParts.length > 0 && (
                <p className="text-xs text-text-muted">{detailParts.join(' · ')}</p>
              )}
              {entry.reflection && <p className="mt-2 text-sm text-text-primary">{entry.reflection}</p>}
            </Card>
          )
        })
      )}
    </div>
  )
}
