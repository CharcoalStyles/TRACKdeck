import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

const TODAY = new Date().toISOString().slice(0, 10)

export default function ReflectionPage() {
  const [searchParams] = useSearchParams()
  const date = searchParams.get('date') || TODAY
  const session = searchParams.get('session') || 'planning'
  const [status, setStatus] = useState<SaveState>('idle')

  const [energyRating, setEnergyRating] = useState('')
  const [whatWorkedWell, setWhatWorkedWell] = useState('')
  const [whatHadFriction, setWhatHadFriction] = useState('')
  const [adjustments, setAdjustments] = useState('')

  const reflectionQuery = useQuery({
    queryKey: ['reflection', date, session],
    queryFn: async () => {
      const { data, error } = await api.GET('/reflection', { params: { query: { date, session } } })
      if (error) throw new Error('No planning note found for this day.')
      return data
    },
  })

  useEffect(() => {
    if (!reflectionQuery.data) return
    setEnergyRating(reflectionQuery.data.energy_rating ?? '')
    setWhatWorkedWell(reflectionQuery.data.what_worked_well ?? '')
    setWhatHadFriction(reflectionQuery.data.what_had_friction ?? '')
    setAdjustments(reflectionQuery.data.adjustments ?? '')
  }, [reflectionQuery.data])

  const saveMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/reflection', {
        body: {
          date,
          session,
          energy_rating: energyRating || null,
          what_worked_well: whatWorkedWell || null,
          what_had_friction: whatHadFriction || null,
          adjustments: adjustments || null,
        },
      })
      if (error) throw new Error()
    },
    onMutate: () => setStatus('saving'),
    onSuccess: () => setStatus('saved'),
    onError: () => setStatus('error'),
  })

  return (
    <div className="flex flex-col gap-4 w-full max-w-xl">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">
          {reflectionQuery.data?.title ?? 'End of Day Reflection'}
        </h2>
        <p className="mb-3 text-sm text-text-muted">{date}</p>

        {reflectionQuery.isPending && <p className="text-sm text-text-muted">Loading...</p>}
        {reflectionQuery.isError && (
          <p className="text-sm text-danger">No planning note found for {date}.</p>
        )}

        {reflectionQuery.data?.schedule && (
          <pre className="mb-4 whitespace-pre-wrap rounded border border-border bg-card-alt p-3 text-sm">
            {reflectionQuery.data.schedule}
          </pre>
        )}
      </Card>

      {reflectionQuery.data && (
        <Card>
          <div className="mb-3 flex flex-col gap-1">
            <label className="text-sm text-text-muted">Energy & Mood (1-10)</label>
            <input
              type="text"
              value={energyRating}
              onChange={(e) => setEnergyRating(e.target.value)}
              className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
            />
          </div>
          <div className="mb-3 flex flex-col gap-1">
            <label className="text-sm text-text-muted">What worked well</label>
            <textarea
              value={whatWorkedWell}
              onChange={(e) => setWhatWorkedWell(e.target.value)}
              rows={2}
              className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
            />
          </div>
          <div className="mb-3 flex flex-col gap-1">
            <label className="text-sm text-text-muted">What had friction</label>
            <textarea
              value={whatHadFriction}
              onChange={(e) => setWhatHadFriction(e.target.value)}
              rows={2}
              className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
            />
          </div>
          <div className="mb-3 flex flex-col gap-1">
            <label className="text-sm text-text-muted">Adjustments for next time</label>
            <textarea
              value={adjustments}
              onChange={(e) => setAdjustments(e.target.value)}
              rows={2}
              className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
            />
          </div>
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover"
          >
            Save
          </button>
          <SaveStatus state={status} />
        </Card>
      )}
    </div>
  )
}
