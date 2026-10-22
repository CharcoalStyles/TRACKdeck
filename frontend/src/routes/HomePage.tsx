import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import Card from '../components/Card'
import CapturesList from '../components/captures/CapturesList'

function TodayPane() {
  const query = useQuery({
    queryKey: ['today'],
    queryFn: async () => {
      const { data } = await api.GET('/today')
      return data
    },
    refetchInterval: 60_000,
  })
  const today = query.data

  return (
    <Card className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold">{today ? today.weekday : 'Today'}</h2>
        {today && <p className="text-sm tabular-nums text-text-muted">{today.date}</p>}
      </div>
      {query.isPending && <p className="text-sm text-text-muted">Loading…</p>}
      {query.isError && <p className="text-sm text-red-400">Could not load today.</p>}
      {today && (
        <>
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">Calendar</h3>
            {today.events.length === 0 ? (
              <p className="text-sm text-text-faint">Nothing scheduled.</p>
            ) : (
              <ul className="flex flex-col gap-1 text-sm">
                {today.events.map((e, i) => (
                  <li key={`${e.start}-${i}`} className="flex gap-3">
                    <span className="w-24 shrink-0 tabular-nums text-text-muted">
                      {e.start}
                      {e.end ? `–${e.end}` : ''}
                    </span>
                    <span className="break-words">{e.title}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <h3 className="mb-1 flex items-baseline justify-between text-xs font-semibold uppercase tracking-wide text-text-muted">
              Reminders
              <Link to="/reminders" className="font-normal normal-case text-accent hover:underline">
                All
              </Link>
            </h3>
            {today.reminders.length === 0 ? (
              <p className="text-sm text-text-faint">None left today.</p>
            ) : (
              <ul className="flex flex-col gap-1 text-sm">
                {today.reminders.map((r) => (
                  <li key={r.id} className="flex gap-3">
                    <span className="w-24 shrink-0 tabular-nums text-text-muted">{r.time}</span>
                    <span className="break-words">{r.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {today.checkins.length > 0 && (
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">Check-ins</h3>
              <ul className="flex flex-col gap-2 text-sm">
                {today.checkins.map((c, i) => (
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

export default function HomePage() {
  return (
    <div className="grid w-full grid-cols-1 content-start gap-4 md:grid-cols-2">
      <TodayPane />
      <Card className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Captures</h2>
          <Link to="/captures" className="text-sm text-accent hover:underline">
            Earlier days
          </Link>
        </div>
        <CapturesList days={2} />
      </Card>
    </div>
  )
}
