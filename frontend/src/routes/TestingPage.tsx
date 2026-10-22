import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import Card from '../components/Card'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

// Debug/ops endpoints intentionally left loosely typed on the frontend
// (locally-cast, no backend response_model) — this page is a raw trigger
// grid over main.py's POST /debug/* routes, low payoff for full typing.
// Plain fetch rather than the typed api client: these paths are
// dynamically built (e.g. a query-string minutes param), so there's no
// literal path-key match for openapi-fetch to type against anyway.
interface DeviceState {
  last_synced_at?: number | null
  battery_mv?: number | null
  wake_reason?: string | null
  reset_reason?: string | null
  time_awake_ms?: number | null
  firmware_version?: string | null
  rssi_dbm?: number | null
}

interface LlmProvider {
  provider: string
  model?: string | null
  base_url?: string | null
}

interface AlertSound {
  id: string
  display_name: string
}

async function triggerDebug(path: string) {
  const response = await fetch(path, { method: 'POST' })
  if (!response.ok) throw new Error(`Server returned ${response.status}`)
}

async function fetchDebug<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`Server returned ${response.status}`)
  return response.json()
}

function useTrigger(path: string) {
  const [status, setStatus] = useState<SaveState>('idle')
  const mutation = useMutation({
    mutationFn: () => triggerDebug(path),
    onMutate: () => setStatus('saving'),
    onSuccess: () => setStatus('saved'),
    onError: () => setStatus('error'),
  })
  return { trigger: () => mutation.mutate(), isPending: mutation.isPending, status }
}

function TriggerCard({
  title,
  description,
  path,
  buttonLabel,
  pendingText,
  successText,
}: {
  title: string
  description: string
  path: string
  buttonLabel: string
  pendingText: string
  successText: string
}) {
  const { trigger, isPending, status } = useTrigger(path)
  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">{title}</h2>
      <p className="mb-3 text-sm text-text-muted">{description}</p>
      <button
        type="button"
        onClick={trigger}
        disabled={isPending}
        className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
      >
        {buttonLabel}
      </button>
      <SaveStatus
        state={status}
        savedMessage={successText}
        errorMessage="Failed — check server logs."
      />
      {status === 'saving' && <p className="mt-2 text-sm text-text-muted">{pendingText}</p>}
    </Card>
  )
}

export default function TestingPage() {
  const [minutes, setMinutes] = useState(1)
  const [alertSoundId, setAlertSoundId] = useState('')
  const reminderTrigger = useTrigger(
    `/debug/reminder?delay_seconds=${minutes * 60}${alertSoundId ? `&alert_sound_id=${alertSoundId}` : ''}`,
  )

  const alertSoundsQuery = useQuery({
    queryKey: ['alert-sounds'],
    queryFn: () => fetchDebug<{ alert_sounds: AlertSound[] }>('/alert-sounds').then((r) => r.alert_sounds),
  })

  const deviceStateQuery = useQuery({
    queryKey: ['debug-device-state'],
    queryFn: () => fetchDebug<DeviceState>('/debug/device-state'),
  })

  const llmProviderQuery = useQuery({
    queryKey: ['debug-llm-provider'],
    queryFn: () => fetchDebug<LlmProvider>('/debug/llm-provider'),
  })

  const [syncPreview, setSyncPreview] = useState<string | null>(null)
  const syncPreviewMutation = useMutation({
    mutationFn: () => fetchDebug<unknown>('/debug/device-sync'),
    onSuccess: (data) => setSyncPreview(JSON.stringify(data, null, 2)),
  })

  const state = deviceStateQuery.data

  return (
    <div className="flex flex-col gap-4">
      <TriggerCard
        title="Morning Message"
        description="Fires the day-ahead message immediately. Sends a real Gotify push every time you click."
        path="/debug/morning"
        buttonLabel="Send morning message now"
        pendingText="Working..."
        successText="Done."
      />
      <TriggerCard
        title="Evening Message"
        description="Fires the evening message immediately: a real push (and email if set), the daily commentary file if that setting is on, and the nightly thread sweep."
        path="/debug/evening"
        buttonLabel="Send evening message now"
        pendingText="Working..."
        successText="Done."
      />
      <TriggerCard
        title="Weekly Review"
        description="Writes this week's review to Reviews/Weekly/ and pushes it."
        path="/debug/weekly-review"
        buttonLabel="Run weekly review now"
        pendingText="Working..."
        successText="Done."
      />
      <TriggerCard
        title="Monthly Review"
        description="Writes the monthly review to Reviews/Monthly/ and pushes it (the month follows the Settings page timing)."
        path="/debug/monthly-review"
        buttonLabel="Run monthly review now"
        pendingText="Working..."
        successText="Done."
      />
      <TriggerCard
        title="Bedtime Reminder"
        description="Manually fires the bedtime reminder immediately. Sends a real Gotify push every time you click."
        path="/debug/bedtime"
        buttonLabel="Send bedtime reminder now"
        pendingText="Sending..."
        successText="Sent."
      />
      <TriggerCard
        title="Check-In Prompt"
        description="Creates and immediately fires a test check-in — bypasses the day's 3-5 target and waking-hours window, running the real create/schedule/fire path with a real Gotify push."
        path="/debug/checkin"
        buttonLabel="Send test check-in now"
        pendingText="Sending..."
        successText="Sent."
      />
      <TriggerCard
        title="Calendar Sync"
        description="Manually runs a calendar reminder sync pass immediately, without waiting for the scheduled interval."
        path="/debug/calendar-sync"
        buttonLabel="Sync calendar now"
        pendingText="Syncing..."
        successText="Synced."
      />
      <TriggerCard
        title="Email"
        description="Sends a one-off test email to the recipient set on the Settings page — confirms the SMTP_* env vars are configured correctly."
        path="/debug/email"
        buttonLabel="Send test email"
        pendingText="Sending..."
        successText="Sent."
      />
      <TriggerCard
        title="Gotify Notification"
        description="Sends a one-off test push — confirms GOTIFY_URL/GOTIFY_TOKEN are configured correctly."
        path="/debug/notify"
        buttonLabel="Send test notification"
        pendingText="Sending..."
        successText="Sent."
      />

      <Card>
        <h2 className="mb-1 text-lg font-semibold">Ad-Hoc Reminder</h2>
        <p className="mb-3 text-sm text-text-muted">
          Creates a real reminder due in the given number of minutes and schedules it — exercises
          the full pipeline (store → scheduler → fire → Gotify), not just the fire step.
        </p>
        <div className="flex items-center gap-2">
          <label className="text-sm text-text-muted">Minutes:</label>
          <input
            type="number"
            min={1}
            max={60}
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value) || 1)}
            className="w-16 rounded border border-border bg-card-alt px-2 py-1 text-sm text-text-primary"
          />
          <label className="text-sm text-text-muted">Sound:</label>
          <select
            value={alertSoundId}
            onChange={(e) => setAlertSoundId(e.target.value)}
            className="rounded border border-border bg-card-alt px-2 py-1 text-sm text-text-primary"
          >
            <option value="">Random (default)</option>
            {(alertSoundsQuery.data ?? []).map((sound) => (
              <option key={sound.id} value={sound.id}>
                {sound.display_name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={reminderTrigger.trigger}
            disabled={reminderTrigger.isPending}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
          >
            Create test reminder
          </button>
        </div>
        <SaveStatus
          state={reminderTrigger.status}
          savedMessage={`Scheduled — check Gotify in ~${minutes} minute(s).`}
          errorMessage="Failed — check server logs."
        />
      </Card>

      <Card>
        <h2 className="mb-1 text-lg font-semibold">Active LLM</h2>
        <p className="mb-3 text-sm text-text-muted">
          What model/base_url the app is actually using right now.
        </p>
        <pre className="whitespace-pre-line text-sm text-text-muted">
          {!llmProviderQuery.data
            ? 'Loading…'
            : [
                `Provider: ${llmProviderQuery.data.provider}`,
                `Model: ${llmProviderQuery.data.model ?? '—'}`,
                `Base URL: ${llmProviderQuery.data.base_url ?? '—'}`,
              ].join('\n')}
        </pre>
      </Card>

      <Card>
        <h2 className="mb-1 text-lg font-semibold">Device Status</h2>
        <p className="mb-3 text-sm text-text-muted">
          Last telemetry the ESP32-S3 reported on its most recent sync — for watching the beta
          device without needing to check logs.
        </p>
        <button
          type="button"
          onClick={() => deviceStateQuery.refetch()}
          className="mb-3 rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent"
        >
          Refresh
        </button>
        <pre className="whitespace-pre-line text-sm text-text-muted">
          {!state
            ? 'Loading…'
            : !state.last_synced_at
              ? 'No sync recorded yet.'
              : [
                  `Last synced: ${Math.max(0, Math.round(Date.now() / 1000 - state.last_synced_at))}s ago`,
                  `Battery: ${state.battery_mv != null ? `${(state.battery_mv / 1000).toFixed(2)}V` : '—'}`,
                  `Wake reason: ${state.wake_reason ?? '—'}`,
                  `Reset reason: ${state.reset_reason ?? '—'}`,
                  `Time awake this cycle: ${state.time_awake_ms != null ? state.time_awake_ms + 'ms' : '—'}`,
                  `Firmware: ${state.firmware_version ?? '—'}`,
                  `RSSI: ${state.rssi_dbm != null ? state.rssi_dbm + ' dBm' : '—'}`,
                ].join('\n')}
        </pre>
      </Card>

      <Card>
        <h2 className="mb-1 text-lg font-semibold">Preview Sync Payload</h2>
        <p className="mb-3 text-sm text-text-muted">
          Shows the exact JSON POST /device/sync would return right now — useful for checking the
          payload shape while writing firmware, without needing real hardware.
        </p>
        <button
          type="button"
          onClick={() => syncPreviewMutation.mutate()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover"
        >
          Fetch payload
        </button>
        {syncPreview && (
          <pre className="mt-3 max-h-[320px] overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-[#2a2a2a] bg-header p-3 text-sm">
            {syncPreview}
          </pre>
        )}
      </Card>
    </div>
  )
}
