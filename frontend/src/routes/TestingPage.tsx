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

type PromptCategory = 'low' | 'medium' | 'high'
type PromptBank = Record<PromptCategory, string[]>
const PROMPT_CATEGORIES: PromptCategory[] = ['low', 'medium', 'high']

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
  const reminderTrigger = useTrigger(`/debug/reminder?delay_seconds=${minutes * 60}`)

  const deviceStateQuery = useQuery({
    queryKey: ['debug-device-state'],
    queryFn: () => fetchDebug<DeviceState>('/debug/device-state'),
  })

  const [syncPreview, setSyncPreview] = useState<string | null>(null)
  const syncPreviewMutation = useMutation({
    mutationFn: () => fetchDebug<unknown>('/debug/device-sync'),
    onSuccess: (data) => setSyncPreview(JSON.stringify(data, null, 2)),
  })

  const promptsQuery = useQuery({
    queryKey: ['debug-checkin-prompts'],
    queryFn: () => fetchDebug<PromptBank>('/debug/checkin/prompts'),
  })
  const allPrompts = PROMPT_CATEGORIES.flatMap((category) =>
    (promptsQuery.data?.[category] ?? []).map((text, index) => ({ category, index, text })),
  )

  const [selectedPromptKey, setSelectedPromptKey] = useState('')
  const [previewLevel, setPreviewLevel] = useState<'select' | 'light' | 'moderate'>('light')
  const [personalizationPreview, setPersonalizationPreview] = useState<string | null>(null)
  const selectedPrompt =
    allPrompts.find((p) => `${p.category}:${p.index}` === selectedPromptKey) ?? allPrompts[0]

  const personalizationPreviewMutation = useMutation({
    mutationFn: () => {
      if (!selectedPrompt) throw new Error('No prompt selected')
      const params = new URLSearchParams({ category: selectedPrompt.category, level: previewLevel })
      // "select" chooses across the whole category bank rather than rewording
      // one specific line, so the picked prompt only supplies the category.
      if (previewLevel !== 'select') params.set('base_prompt', selectedPrompt.text)
      return fetchDebug<unknown>(`/debug/checkin/preview?${params.toString()}`)
    },
    onSuccess: (data) => setPersonalizationPreview(JSON.stringify(data, null, 2)),
  })

  const state = deviceStateQuery.data

  return (
    <div className="flex flex-col gap-4">
      <TriggerCard
        title="Daily Digest"
        description="Manually sends today's digest immediately, without waiting for the scheduled time. Sends a real email every time you click."
        path="/debug/digest"
        buttonLabel="Send digest now"
        pendingText="Sending..."
        successText="Sent."
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
        title="Vault Reconcile"
        description="Forces a full notes-vault reconciliation sweep immediately, without waiting for the live watcher or a restart."
        path="/debug/reconcile-vault"
        buttonLabel="Reconcile vault now"
        pendingText="Reconciling..."
        successText="Reconciled."
      />
      <TriggerCard
        title="Gotify Notification"
        description="Sends a one-off test push — confirms GOTIFY_URL/GOTIFY_TOKEN are configured correctly."
        path="/debug/notify"
        buttonLabel="Send test notification"
        pendingText="Sending..."
        successText="Sent."
      />
      <TriggerCard
        title="Email"
        description="Sends a one-off test email — confirms the SMTP_* env vars are configured correctly."
        path="/debug/email"
        buttonLabel="Send test email"
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
        <h2 className="mb-1 text-lg font-semibold">Preview Check-In Personalization</h2>
        <p className="mb-3 text-sm text-text-muted">
          Pick one of the built-in prompts and a level, then preview the raw LLM output — without
          creating a real check-in or a real Gotify push. "Light" and "moderate" both reword
          whichever prompt is selected, so you can compare them against the same input. "Moderate"
          is preview-only — it's never picked for a live check-in, only "none"/"select"/"light"
          are in that rotation.
        </p>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <select
            value={selectedPromptKey || (allPrompts[0] ? `${allPrompts[0].category}:${allPrompts[0].index}` : '')}
            onChange={(e) => setSelectedPromptKey(e.target.value)}
            disabled={!promptsQuery.data}
            className="min-w-0 flex-1 rounded border border-border bg-card-alt px-2 py-1 text-sm text-text-primary"
          >
            {PROMPT_CATEGORIES.map((category) => (
              <optgroup key={category} label={category}>
                {(promptsQuery.data?.[category] ?? []).map((text, index) => (
                  <option key={index} value={`${category}:${index}`}>
                    {text.length > 70 ? `${text.slice(0, 67)}...` : text}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <select
            value={previewLevel}
            onChange={(e) => setPreviewLevel(e.target.value as typeof previewLevel)}
            className="rounded border border-border bg-card-alt px-2 py-1 text-sm text-text-primary"
          >
            <option value="select">Select</option>
            <option value="light">Light</option>
            <option value="moderate">Moderate</option>
          </select>
          <button
            type="button"
            onClick={() => personalizationPreviewMutation.mutate()}
            disabled={personalizationPreviewMutation.isPending || !selectedPrompt}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {personalizationPreviewMutation.isPending ? 'Asking the model...' : 'Preview'}
          </button>
        </div>
        {personalizationPreview && (
          <pre className="max-h-[320px] overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-[#2a2a2a] bg-header p-3 text-sm">
            {personalizationPreview}
          </pre>
        )}
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
