import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
import Toggle from '../components/Toggle'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

const TIMEZONES =
  typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : []

function useSaveStatus() {
  const [state, setState] = useState<SaveState>('idle')
  const [errorMessage, setErrorMessage] = useState<string | undefined>()
  return { state, setState, errorMessage, setErrorMessage }
}

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const { data } = await api.GET('/settings')
      return data
    },
  })
  const data = settingsQuery.data

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['settings'] })

  return (
    <div className="flex flex-col gap-4">
      <LearningModeCard data={data} onSaved={invalidate} />
      <LlmProviderCard data={data} onSaved={invalidate} />
      <ModelAssignmentsCard data={data} onSaved={invalidate} />
      <LocationTimeCard data={data} onSaved={invalidate} />
      <DigestCard data={data} onSaved={invalidate} />
      <CheckinWindowCard data={data} onSaved={invalidate} />
      <BedtimeCard data={data} onSaved={invalidate} />
      <NotificationsCard data={data} onSaved={invalidate} />
      <DeviceSyncCard data={data} onSaved={invalidate} />
      <RecallCard data={data} onSaved={invalidate} />
      <ContextBudgetCard data={data} onSaved={invalidate} />
      <McpServersCard data={data} onSaved={invalidate} />
      <ResetAboutMeCard />
    </div>
  )
}

function ResetAboutMeCard() {
  const queryClient = useQueryClient()
  const status = useSaveStatus()

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/onboarding/reset')
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['settings-probe'] })
    },
    onError: () => status.setState('error'),
  })

  function handleReset() {
    if (
      !window.confirm(
        'Reset About Me? This deletes your profile note and restarts onboarding from the basics form. This cannot be undone.'
      )
    ) {
      return
    }
    mutation.mutate()
  }

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Reset Profile</h2>
      <p className="mb-3 text-sm text-text-muted">
        Deletes your About Me note and clears the onboarding conversation, so the basics form
        and guided interview start fresh next time you visit Profile. Notes linked from About
        Me (individual people) and other settings are left untouched.
      </p>
      <button
        type="button"
        onClick={handleReset}
        className="rounded-lg border border-danger px-4 py-2 text-sm font-semibold text-danger hover:bg-danger/10"
      >
        Reset About Me
      </button>
      <SaveStatus state={status.state} savedMessage="Reset." />
    </Card>
  )
}

type Settings = NonNullable<ReturnType<typeof useQuery<{
  learning_mode: boolean
  default_location: string
  timezone: string
  digest_time: string
  digest_email_to: string
  wake_time: string
  bedtime: string
  latest_checkin_time: string
  gotify_url: string
  gotify_token_set: boolean
  public_base_url: string
  device_poll_interval_seconds: number
  recall_max_distance: number
  recall_recency_days: number
  max_history_tokens: number
  mcp_servers: string
  llm_provider: string
  lmstudio_writer_model: string
  openrouter_configured: boolean
}>>['data']>

function LearningModeCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const mutation = useMutation({
    mutationFn: async (learning_mode: boolean) => {
      const { error } = await api.POST('/settings', { body: { learning_mode } })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => status.setState('error'),
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Assistant Behavior</h2>
      <p className="mb-3 text-sm text-text-muted">
        Standing toggles — these apply to every interaction until changed here.
      </p>
      <Toggle
        checked={!!data?.learning_mode}
        onChange={(checked) => mutation.mutate(checked)}
        label="Learning mode"
        sublabel="Proactively notices and records durable facts about you into your About Me profile as they come up in conversation."
      />
      <SaveStatus state={status.state} />
    </Card>
  )
}

function LlmProviderCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()

  const mutation = useMutation({
    mutationFn: async (llm_provider: string) => {
      const { error } = await api.POST('/settings', { body: { llm_provider } })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => {
      status.setErrorMessage('Failed to switch — check OPENROUTER_API_KEY is set in .env.')
      status.setState('error')
    },
  })

  const provider = data?.llm_provider ?? 'lmstudio'
  const openrouterConfigured = !!data?.openrouter_configured
  const isKnownProvider = provider === 'lmstudio' || provider === 'openrouter'

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">LLM Provider</h2>
      <p className="mb-3 text-sm text-text-muted">
        Which chat-completion backend the assistant uses for every conversation. Switches
        immediately, no restart needed.
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <ProviderOption
          label="LM Studio"
          sublabel="Local, on your own hardware."
          selected={provider === 'lmstudio'}
          onSelect={() => mutation.mutate('lmstudio')}
        />
        <ProviderOption
          label="OpenRouter"
          sublabel={
            openrouterConfigured
              ? 'Hosted — pick a model on the OpenRouter Models page.'
              : 'Needs OPENROUTER_API_KEY set in .env first.'
          }
          selected={provider === 'openrouter'}
          disabled={!openrouterConfigured}
          onSelect={() => mutation.mutate('openrouter')}
        />
      </div>
      {!isKnownProvider && (
        <p className="mt-3 text-sm text-text-muted">
          Currently using <span className="text-text-primary">{provider}</span> (set via
          LLM_PROVIDER at startup) — not switchable from here.
        </p>
      )}
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

type WriterChoice = 'default' | 'tool' | 'custom'
type RowDraft = { tool: string; writerChoice: WriterChoice; writerCustom: string }

function ModelAssignmentsCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const queryClient = useQueryClient()
  const status = useSaveStatus()
  const [defaultWriter, setDefaultWriter] = useState('')
  const [draft, setDraft] = useState<Record<string, RowDraft>>({})

  const matrixQuery = useQuery({
    queryKey: ['model-assignments'],
    queryFn: async () => {
      const { data } = await api.GET('/settings/model-assignments')
      return data
    },
  })
  const matrix = matrixQuery.data

  const modelsQuery = useQuery({
    queryKey: ['lmstudio-models'],
    queryFn: async () => {
      const { data } = await api.GET('/debug/lmstudio-models')
      return data
    },
  })

  useEffect(() => {
    if (data) setDefaultWriter(data.lmstudio_writer_model || '')
  }, [data])

  useEffect(() => {
    if (!matrix) return
    const next: Record<string, RowDraft> = {}
    for (const r of matrix.rows) {
      const w = r.writer_override
      next[r.key] = {
        tool: r.tool_override,
        writerChoice: w === '' ? 'default' : w === matrix.no_writer_value ? 'tool' : 'custom',
        writerCustom: w === '' || w === matrix.no_writer_value ? '' : w,
      }
    }
    setDraft(next)
  }, [matrix])

  const mutation = useMutation({
    mutationFn: async (body: {
      lmstudio_writer_model?: string
      model_assignments?: Record<string, Record<string, string>>
    }) => {
      const { error } = await api.POST('/settings', { body })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
      queryClient.invalidateQueries({ queryKey: ['model-assignments'] })
    },
    onError: () => status.setState('error'),
  })

  function toOverrides(): Record<string, Record<string, string>> {
    const out: Record<string, Record<string, string>> = {}
    if (!matrix) return out
    for (const r of matrix.rows) {
      const d = draft[r.key]
      if (!d) continue
      const entry: Record<string, string> = {}
      if (r.tool_calls && d.tool.trim()) entry.tool = d.tool.trim()
      if (d.writerChoice === 'tool') entry.writer = matrix.no_writer_value
      else if (d.writerChoice === 'custom' && d.writerCustom.trim()) entry.writer = d.writerCustom.trim()
      if (Object.keys(entry).length) out[r.key] = entry
    }
    return out
  }

  const saved = matrix
    ? Object.fromEntries(
        matrix.rows
          .filter((r) => r.tool_override || r.writer_override)
          .map((r) => [
            r.key,
            {
              ...(r.tool_override ? { tool: r.tool_override } : {}),
              ...(r.writer_override ? { writer: r.writer_override } : {}),
            },
          ]),
      )
    : {}
  const dirty = JSON.stringify(toOverrides()) !== JSON.stringify(saved)

  function patch(key: string, change: Partial<RowDraft>) {
    setDraft((d) => ({ ...d, [key]: { ...d[key], ...change } }))
  }

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Models by Mode</h2>
      <p className="mb-3 text-sm text-text-muted">
        Two jobs per mode: the <strong>tool model</strong> picks and runs tools; the{' '}
        <strong>reply model</strong> writes what you read. Blank means the default. Every model
        named here must be loaded in LM Studio. Applies immediately.
      </p>

      {matrix && !matrix.split_applies && (
        <p className="mb-3 rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-muted">
          The provider is <span className="text-text-primary">{matrix.provider}</span>. A separate
          writer only applies on LM Studio, so the table below is inactive.
        </p>
      )}

      <div className="mb-4 grid gap-3 md:grid-cols-2">
        <FieldRow label="Default tool model">
          <div className="rounded border border-border bg-card-alt px-3 py-2 font-mono text-sm text-text-primary">
            {matrix?.default_tool_model || '—'}
          </div>
          <span className="text-xs text-text-muted">Set on the Models page.</span>
        </FieldRow>
        <FieldRow label="Default writer model">
          <div className="flex gap-2">
            <input
              type="text"
              value={defaultWriter}
              onChange={(e) => setDefaultWriter(e.target.value)}
              list="lmstudioModelOptions"
              placeholder="e.g. gemma-4-e4b-it (blank = no writer)"
              className={inputClass}
            />
            <button
              type="button"
              onClick={() => mutation.mutate({ lmstudio_writer_model: defaultWriter })}
              disabled={defaultWriter.trim() === (data?.lmstudio_writer_model ?? '')}
              className={`${primaryBtnClass} disabled:cursor-not-allowed disabled:opacity-50`}
            >
              Save
            </button>
          </div>
        </FieldRow>
      </div>
      <datalist id="lmstudioModelOptions">
        {(modelsQuery.data?.models ?? []).map((m) => (
          <option key={m.id} value={m.id} />
        ))}
      </datalist>

      <div className="hidden gap-3 border-b border-border pb-2 text-xs font-semibold uppercase tracking-wide text-text-muted md:grid md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div>Mode</div>
        <div>Tool calling</div>
        <div>Writes the reply</div>
      </div>

      {(matrix?.rows ?? []).map((r) => {
        const d = draft[r.key]
        if (!d) return null
        const writerIsOwn = r.writer_model !== null
        return (
          <div
            key={r.key}
            className="grid gap-3 border-b border-border py-3 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)]"
          >
            <div>
              <div className="font-semibold text-text-primary">{r.label}</div>
              <div className="mt-1 text-xs text-text-muted">{r.reply_rule}</div>
            </div>

            <div className="min-w-0">
              <div className="mb-1 text-xs uppercase tracking-wide text-text-muted md:hidden">
                Tool calling
              </div>
              {r.tool_calls ? (
                <>
                  <ModelName model={r.tool_model} isOverride={!!r.tool_override} />
                  <input
                    type="text"
                    value={d.tool}
                    onChange={(e) => patch(r.key, { tool: e.target.value })}
                    list="lmstudioModelOptions"
                    placeholder="default"
                    aria-label={`${r.label}: tool model override`}
                    className={`${inputClass} mt-2`}
                  />
                </>
              ) : (
                <span className="text-sm text-text-muted">No tool calling</span>
              )}
            </div>

            <div className="min-w-0">
              <div className="mb-1 text-xs uppercase tracking-wide text-text-muted md:hidden">
                Writes the reply
              </div>
              <ModelName
                model={r.reply_model}
                isOverride={!!r.writer_override && r.writer_override !== matrix?.no_writer_value}
                note={writerIsOwn ? 'writer' : 'tool model'}
              />
              <select
                value={d.writerChoice}
                onChange={(e) => patch(r.key, { writerChoice: e.target.value as WriterChoice })}
                aria-label={`${r.label}: reply writer`}
                className={`${inputClass} mt-2`}
              >
                <option value="default">
                  Default{matrix?.default_writer_model ? ` (${matrix.default_writer_model})` : ' (no writer)'}
                </option>
                <option value="tool">Tool model only</option>
                <option value="custom">Specific model…</option>
              </select>
              {d.writerChoice === 'custom' && (
                <input
                  type="text"
                  value={d.writerCustom}
                  onChange={(e) => patch(r.key, { writerCustom: e.target.value })}
                  list="lmstudioModelOptions"
                  placeholder="model id"
                  aria-label={`${r.label}: writer model id`}
                  className={`${inputClass} mt-2`}
                />
              )}
            </div>
          </div>
        )
      })}

      <p className="mt-3 text-xs text-text-muted">
        “Writes the reply” is the model that would write when the mode’s rule hands over to the
        writer. Note tidying and composing use the same writer as the mode they happen in.
      </p>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          onClick={() => mutation.mutate({ model_assignments: toOverrides() })}
          disabled={!dirty}
          className={`${primaryBtnClass} disabled:cursor-not-allowed disabled:opacity-50`}
        >
          Save assignments
        </button>
        {dirty && <span className="text-xs text-text-muted">Unsaved changes</span>}
      </div>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

function ModelName({
  model,
  isOverride,
  note,
}: {
  model: string | null
  isOverride: boolean
  note?: string
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="break-all font-mono text-sm text-text-primary">{model || '—'}</span>
      {note && <span className="text-xs text-text-muted">({note})</span>}
      <span
        className={`rounded px-1.5 py-0.5 text-xs font-semibold ${
          isOverride ? 'bg-accent/10 text-accent' : 'bg-card-alt text-text-muted'
        }`}
      >
        {isOverride ? 'override' : 'default'}
      </span>
    </div>
  )
}

function ProviderOption({
  label,
  sublabel,
  selected,
  disabled,
  onSelect,
}: {
  label: string
  sublabel: string
  selected: boolean
  disabled?: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onSelect}
      className={`flex-1 rounded-lg border px-4 py-3 text-left text-sm transition ${
        selected ? 'border-accent bg-accent/10' : 'border-border bg-card-alt hover:border-accent'
      } ${disabled ? 'cursor-not-allowed opacity-50 hover:border-border' : ''}`}
    >
      <div className="flex items-center justify-between font-semibold text-text-primary">
        {label}
        {selected && <span className="text-xs font-semibold text-accent">Active</span>}
      </div>
      <div className="mt-1 text-xs text-text-muted">{sublabel}</div>
    </button>
  )
}

function LocationTimeCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [location, setLocation] = useState('')
  const [timezone, setTimezone] = useState('')

  useEffect(() => {
    if (!data) return
    setLocation(data.default_location || '')
    setTimezone(data.timezone || '')
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', {
        body: { default_location: location, timezone },
      })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => {
      status.setErrorMessage('Failed to save — check the timezone name is a valid IANA zone.')
      status.setState('error')
    },
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Location &amp; Time</h2>
      <p className="mb-3 text-sm text-text-muted">
        Used for weather lookups when you don't name a place, and for grounding the assistant's
        sense of "today"/"now" (calendar day boundaries, the daily digest).
      </p>
      <FieldRow label="Default location">
        <input
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="e.g. Canberra"
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Timezone">
        <div className="flex gap-2">
          <input
            type="text"
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            list="timezoneOptions"
            placeholder="e.g. Australia/Canberra"
            className={inputClass}
          />
          <button
            type="button"
            onClick={() => setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone)}
            className={secondaryBtnClass}
          >
            Detect
          </button>
        </div>
        <datalist id="timezoneOptions">
          {TIMEZONES.map((tz) => (
            <option key={tz} value={tz} />
          ))}
        </datalist>
      </FieldRow>
      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

function DigestCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [digestTime, setDigestTime] = useState('')
  const [email, setEmail] = useState('')

  useEffect(() => {
    if (!data) return
    setDigestTime(data.digest_time || '')
    setEmail(data.digest_email_to || '')
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', {
        body: { digest_time: digestTime, digest_email_to: email },
      })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => status.setState('error'),
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Daily Digest</h2>
      <p className="mb-3 text-sm text-text-muted">
        Local time the end-of-day recap email is sent (see the Timezone above). Takes effect
        immediately, no restart needed.
      </p>
      <FieldRow label="Send time">
        <input
          type="time"
          value={digestTime}
          onChange={(e) => setDigestTime(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Recipient email">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="e.g. you@example.com"
          className={inputClass}
        />
      </FieldRow>
      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus state={status.state} />
    </Card>
  )
}

function CheckinWindowCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [wakeTime, setWakeTime] = useState('')
  const [latestCheckinTime, setLatestCheckinTime] = useState('')

  useEffect(() => {
    if (!data) return
    setWakeTime(data.wake_time || '')
    setLatestCheckinTime(data.latest_checkin_time || '')
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', {
        body: { wake_time: wakeTime, latest_checkin_time: latestCheckinTime },
      })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => status.setState('error'),
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Mental-Health Check-Ins</h2>
      <p className="mb-3 text-sm text-text-muted">
        Local time window short reflective prompts may fire in each day. Takes effect
        immediately, no restart needed.
      </p>
      <FieldRow label="Earliest check-in time">
        <input
          type="time"
          value={wakeTime}
          onChange={(e) => setWakeTime(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Latest check-in time">
        <input
          type="time"
          value={latestCheckinTime}
          onChange={(e) => setLatestCheckinTime(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus state={status.state} />
    </Card>
  )
}

function BedtimeCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [bedtime, setBedtime] = useState('')

  useEffect(() => {
    if (!data) return
    setBedtime(data.bedtime || '')
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', { body: { bedtime } })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => status.setState('error'),
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Bedtime Reminder</h2>
      <p className="mb-3 text-sm text-text-muted">
        Local time a wind-down nudge is pushed each night (see the Timezone above) — separate
        from the daily digest and from the check-in window's own times. Takes effect
        immediately, no restart needed.
      </p>
      <FieldRow label="Bedtime">
        <input
          type="time"
          value={bedtime}
          onChange={(e) => setBedtime(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus state={status.state} />
    </Card>
  )
}

function NotificationsCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [gotifyUrl, setGotifyUrl] = useState('')
  const [gotifyToken, setGotifyToken] = useState('')
  const [publicBaseUrl, setPublicBaseUrl] = useState('')

  useEffect(() => {
    if (!data) return
    setGotifyUrl(data.gotify_url || '')
    setPublicBaseUrl(data.public_base_url || '')
    setGotifyToken('')
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const body: { gotify_url: string; public_base_url: string; gotify_token?: string } = {
        gotify_url: gotifyUrl,
        public_base_url: publicBaseUrl,
      }
      // Leaving the token field blank keeps the currently saved token —
      // only send it when the user actually typed a new one.
      if (gotifyToken) body.gotify_token = gotifyToken
      const { error } = await api.POST('/settings', { body })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => status.setState('error'),
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Notifications</h2>
      <p className="mb-3 text-sm text-text-muted">
        Gotify server used for push notifications (reminders, check-ins, errors), and the base
        URL used to build check-in tap-to-open links in those pushes.
      </p>
      <FieldRow label="Gotify URL">
        <input
          type="text"
          value={gotifyUrl}
          onChange={(e) => setGotifyUrl(e.target.value)}
          placeholder="e.g. https://gotify.example.com"
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Gotify token">
        <input
          type="password"
          value={gotifyToken}
          onChange={(e) => setGotifyToken(e.target.value)}
          placeholder={data?.gotify_token_set ? 'Saved — leave blank to keep' : 'e.g. AbCdEfGhIjKlMno'}
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Public base URL">
        <input
          type="text"
          value={publicBaseUrl}
          onChange={(e) => setPublicBaseUrl(e.target.value)}
          placeholder="e.g. https://assistant.example.com"
          className={inputClass}
        />
      </FieldRow>
      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus state={status.state} />
    </Card>
  )
}

function DeviceSyncCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [pollInterval, setPollInterval] = useState('')

  useEffect(() => {
    if (!data) return
    setPollInterval(String(data.device_poll_interval_seconds ?? ''))
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', {
        body: { device_poll_interval_seconds: parseInt(pollInterval, 10) },
      })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => {
      status.setErrorMessage('Failed to save — must be between 30 and 86400.')
      status.setState('error')
    },
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Device Sync</h2>
      <p className="mb-3 text-sm text-text-muted">
        How often (seconds) the ESP32-S3 wakes from deep sleep to poll for what's coming up.
        Retunable here without reflashing firmware — the device reads this value on its next sync.
      </p>
      <FieldRow label="Poll interval (seconds)">
        <input
          type="number"
          min={30}
          max={86400}
          step={1}
          value={pollInterval}
          onChange={(e) => setPollInterval(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

function RecallCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [maxDistance, setMaxDistance] = useState('')
  const [recencyDays, setRecencyDays] = useState('')

  useEffect(() => {
    if (!data) return
    setMaxDistance(String(data.recall_max_distance ?? ''))
    setRecencyDays(String(data.recall_recency_days ?? ''))
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', {
        body: {
          recall_max_distance: parseFloat(maxDistance),
          recall_recency_days: parseInt(recencyDays, 10),
        },
      })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => {
      status.setErrorMessage('Failed to save — distance must be 0–2, recency 1–3650 days.')
      status.setState('error')
    },
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Cross-Thread Recall</h2>
      <p className="mb-3 text-sm text-text-muted">
        How the assistant pulls "relevant past context" from other conversations into a reply. A
        match farther than the distance cutoff is dropped, and anything older than the recency
        window is never considered — see the Thread Debug page to see what's actually being
        recalled and tune these from real data.
      </p>
      <FieldRow label="Distance cutoff (0–2, lower = stricter)">
        <input
          type="number"
          min={0.01}
          max={2}
          step={0.01}
          value={maxDistance}
          onChange={(e) => setMaxDistance(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Recency window (days)">
        <input
          type="number"
          min={1}
          max={3650}
          step={1}
          value={recencyDays}
          onChange={(e) => setRecencyDays(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

function ContextBudgetCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [maxHistoryTokens, setMaxHistoryTokens] = useState('')

  useEffect(() => {
    if (!data) return
    setMaxHistoryTokens(String(data.max_history_tokens ?? ''))
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', {
        body: { max_history_tokens: parseInt(maxHistoryTokens, 10) },
      })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setState('saved')
      onSaved()
    },
    onError: () => {
      status.setErrorMessage('Failed to save — must be between 500 and 200000.')
      status.setState('error')
    },
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Context Budget</h2>
      <p className="mb-3 text-sm text-text-muted">
        Fallback token budget for the message history sent to the model each turn — older
        messages are trimmed once a conversation exceeds this. Only used when
        LMSTUDIO_MANAGEMENT_URL isn't configured or LM Studio's live loaded context length can't
        be fetched; otherwise that live number is used instead of this guess. Set it to roughly
        match the context length your model is loaded with in LM Studio as a safety net.
      </p>
      <FieldRow label="Fallback history budget (tokens, approximate)">
        <input
          type="number"
          min={500}
          max={200000}
          step={100}
          value={maxHistoryTokens}
          onChange={(e) => setMaxHistoryTokens(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

function McpServersCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [value, setValue] = useState('')

  useEffect(() => {
    if (!data) return
    try {
      setValue(JSON.stringify(JSON.parse(data.mcp_servers || '{}'), null, 2))
    } catch {
      setValue(data.mcp_servers || '')
    }
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', { body: { mcp_servers: value } })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setErrorMessage(undefined)
      status.setState('saved')
      onSaved()
    },
    onError: () => status.setState('error'),
  })

  function handleSave() {
    try {
      JSON.parse(value || '{}')
    } catch {
      status.setErrorMessage('Not valid JSON.')
      status.setState('error')
      return
    }
    mutation.mutate()
  }

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">MCP Servers</h2>
      <p className="mb-3 text-sm text-text-muted">
        External MCP servers whose tools get added to the agent's toolset, as JSON:{' '}
        <code className="rounded bg-card-alt px-1 py-0.5 text-xs">
          {'{"name": {"enabled": true, "transport": "stdio", "command": "...", "args": [...]}}'}
        </code>{' '}
        for a local subprocess, or{' '}
        <code className="rounded bg-card-alt px-1 py-0.5 text-xs">
          {'{"transport": "streamable_http", "url": "..."}'}
        </code>{' '}
        for a remote one. Requires an app restart to take effect — the tool list is only built
        once at startup.
      </p>
      <FieldRow label="Server config (JSON)">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={6}
          spellCheck={false}
          className={`${inputClass} font-mono`}
        />
      </FieldRow>
      <button type="button" onClick={handleSave} className={primaryBtnClass}>
        Save
      </button>
      <SaveStatus
        state={status.state}
        errorMessage={status.errorMessage}
        savedMessage="Saved — restart the app for this to take effect."
      />
    </Card>
  )
}

function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-3 flex flex-col gap-1">
      <label className="text-sm text-text-muted">{label}</label>
      {children}
    </div>
  )
}

const inputClass =
  'w-full rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent'
const primaryBtnClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover'
const secondaryBtnClass =
  'shrink-0 rounded-lg border border-border bg-card-alt px-3 py-2 text-sm text-text-primary hover:border-accent'
