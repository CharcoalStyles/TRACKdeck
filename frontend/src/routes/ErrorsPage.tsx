import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'

function formatTime(epochSeconds: number) {
  return new Date(epochSeconds * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

export default function ErrorsPage() {
  const queryClient = useQueryClient()
  const errorsQuery = useQuery({
    queryKey: ['device-errors'],
    queryFn: async () => {
      const { data } = await api.GET('/device/errors')
      return data?.errors ?? []
    },
  })

  const errors = errorsQuery.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Device Errors</h2>
        <p className="mb-3 text-sm text-text-muted">
          Error reports from the ESP32-S3 — includes suppressed repeats (deduped per error type
          within a cooldown window), not just ones that triggered a Gotify alert.
        </p>
        <button
          type="button"
          onClick={() => queryClient.invalidateQueries({ queryKey: ['device-errors'] })}
          className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent"
        >
          Refresh
        </button>
      </Card>

      {errors.length === 0 ? (
        <Card>
          <p className="text-sm text-text-muted">
            {errorsQuery.isPending ? 'Loading...' : 'No device errors reported.'}
          </p>
        </Card>
      ) : (
        errors.map((err) => {
          const detailParts = [
            err.firmware_version ? `firmware ${err.firmware_version}` : null,
            err.wake_reason ? `wake=${err.wake_reason}` : null,
            err.reset_reason ? `reset=${err.reset_reason}` : null,
            err.battery_pct !== null
              ? `battery=${err.battery_pct}%`
              : err.battery_mv !== null
                ? `battery=${err.battery_mv}mV`
                : null,
            err.rssi_dbm !== null ? `rssi=${err.rssi_dbm}dBm` : null,
            err.free_internal_heap_bytes !== null
              ? `free_internal_heap=${err.free_internal_heap_bytes}B`
              : null,
          ].filter(Boolean)

          return (
            <Card key={err.id}>
              <h2 className="mb-1 text-lg font-semibold">
                {formatTime(err.created_at)} — {err.error_type}{' '}
                <span className={`text-xs font-semibold ${err.alerted ? 'text-accent' : 'text-text-muted'}`}>
                  {err.alerted ? 'Alerted' : 'Suppressed'}
                </span>
              </h2>
              {err.message && <p className="mb-2 text-sm text-text-muted">{err.message}</p>}
              {detailParts.length > 0 && (
                <p className="text-xs text-text-muted">{detailParts.join(' · ')}</p>
              )}
            </Card>
          )
        })
      )}
    </div>
  )
}
