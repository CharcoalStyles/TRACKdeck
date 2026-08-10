import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'

const STATUS_LABEL: Record<string, string> = { answered: 'Answered', skipped: 'Skipped', expired: 'Missed' }
const STATUS_COLOR: Record<string, string> = { answered: 'text-accent', skipped: 'text-text-muted', expired: 'text-danger' }

function formatTime(epochSeconds: number) {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function CheckinsAdminPage() {
  const queryClient = useQueryClient()
  const checkinsQuery = useQuery({
    queryKey: ['checkins-today'],
    queryFn: async () => {
      const { data } = await api.GET('/checkins/today')
      return data?.checkins ?? []
    },
  })

  const checkins = checkinsQuery.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Today's Check-Ins</h2>
        <p className="mb-3 text-sm text-text-muted">
          Short reflective prompts sent throughout the day, and how you responded — answered,
          skipped, or missed.
        </p>
        <button
          type="button"
          onClick={() => queryClient.invalidateQueries({ queryKey: ['checkins-today'] })}
          className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent"
        >
          Refresh
        </button>
      </Card>

      {checkins.length === 0 ? (
        <Card>
          <p className="text-sm text-text-muted">
            {checkinsQuery.isPending ? 'Loading...' : 'No check-ins have resolved yet today.'}
          </p>
        </Card>
      ) : (
        checkins.map((checkin) => (
          <Card key={checkin.id}>
            <h2 className="mb-1 text-lg font-semibold">
              {formatTime(checkin.resolved_at ?? checkin.fired_at ?? checkin.scheduled_at)} —{' '}
              {checkin.category}{' '}
              <span className={`text-xs font-semibold ${STATUS_COLOR[checkin.status] ?? 'text-text-muted'}`}>
                {STATUS_LABEL[checkin.status] ?? checkin.status}
              </span>
            </h2>
            <p className={`text-sm text-text-muted ${checkin.reply ? 'mb-3' : ''}`}>{checkin.prompt_text}</p>
            {checkin.reply && (
              <p className="border-l-[3px] border-accent pl-3 text-sm text-text-primary">{checkin.reply}</p>
            )}
          </Card>
        ))
      )}
    </div>
  )
}
