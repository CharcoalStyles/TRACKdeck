import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'

function formatDay(date: string) {
  return new Date(`${date}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

export default function PodcastPage() {
  const queryClient = useQueryClient()
  const [picked, setPicked] = useState<string | null>(null)

  const { data } = useQuery({
    queryKey: ['podcasts'],
    queryFn: async () => {
      const { data } = await api.GET('/podcasts')
      return data
    },
    // Keep checking while an episode is being made.
    refetchInterval: (query) => (query.state.data?.running ? 5000 : false),
  })

  const runMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/podcasts/run')
      if (error) throw new Error()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['podcasts'] }),
  })

  const episodes = data?.episodes ?? []
  const current = picked ?? episodes[0]?.date ?? null
  const hasScript = episodes.find((e) => e.date === current)?.has_script

  const scriptQuery = useQuery({
    queryKey: ['podcast-script', current],
    enabled: !!current && !!hasScript,
    queryFn: async () => {
      const { data } = await api.GET('/podcasts/{date_str}/script', {
        params: { path: { date_str: current as string } },
      })
      return data?.script ?? ''
    },
  })

  return (
    <div className="flex w-full flex-col gap-4">
      <Card className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">Morning podcast</h2>
          <button
            type="button"
            onClick={() => runMutation.mutate()}
            disabled={data?.running || runMutation.isPending}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {data?.running ? 'Making it…' : 'Make today’s now'}
          </button>
        </div>
        {data?.error && <p className="text-sm text-danger">Last run failed: {data.error}</p>}
        {current ? (
          <>
            <p className="text-sm text-text-muted">{formatDay(current)}</p>
            <audio key={current} controls preload="none" src={`/podcasts/${current}.mp3`} className="w-full" />
          </>
        ) : (
          <p className="text-sm text-text-muted">No episodes yet.</p>
        )}
      </Card>

      {current && hasScript && (
        <Card>
          <h2 className="mb-2 text-lg font-semibold">Script</h2>
          <pre className="whitespace-pre-wrap text-sm text-text-muted">{scriptQuery.data}</pre>
        </Card>
      )}

      {data?.has_samples && (
        <Card>
          <h2 className="mb-1 text-lg font-semibold">Voice samples</h2>
          <p className="mb-2 text-sm text-text-muted">
            The four voice pairs the show rotates through, in order (pair 1 to 4).
          </p>
          <audio controls preload="none" src="/podcasts/voice-samples.mp3" className="w-full" />
        </Card>
      )}

      {episodes.length > 1 && (
        <Card>
          <h2 className="mb-2 text-lg font-semibold">Earlier episodes</h2>
          <ul className="flex flex-col gap-1">
            {episodes.map((e) => (
              <li key={e.date}>
                <button
                  type="button"
                  onClick={() => setPicked(e.date)}
                  className={`text-sm hover:text-accent ${e.date === current ? 'text-accent' : 'text-text-primary'}`}
                >
                  {formatDay(e.date)}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
