import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'
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
      <ModelsCard data={data} onSaved={invalidate} />
      <LocationTimeCard data={data} onSaved={invalidate} />
      <EveningCard data={data} onSaved={invalidate} />
      <CheckinWindowCard data={data} onSaved={invalidate} />
      <BedtimeCard data={data} onSaved={invalidate} />
      <NotificationsCard data={data} onSaved={invalidate} />
      <DeviceSyncCard data={data} onSaved={invalidate} />
      <ContextBudgetCard data={data} onSaved={invalidate} />
      <McpServersCard data={data} onSaved={invalidate} />
    </div>
  )
}

type Settings = NonNullable<ReturnType<typeof useQuery<{
  default_location: string
  timezone: string
  evening_time: string
  wake_time: string
  bedtime: string
  latest_checkin_time: string
  gotify_url: string
  gotify_token_set: boolean
  public_base_url: string
  device_poll_interval_seconds: number
  max_history_tokens: number
  mcp_servers: string
  lmstudio_writer_model: string
}>>['data']>

function ModelsCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [writer, setWriter] = useState('')

  const modelsQuery = useQuery({
    queryKey: ['lmstudio-models'],
    queryFn: async () => {
      const { data } = await api.GET('/debug/lmstudio-models')
      return data
    },
  })

  useEffect(() => {
    if (data) setWriter(data.lmstudio_writer_model || '')
  }, [data])

  const mutation = useMutation({
    mutationFn: async (lmstudio_writer_model: string) => {
      const { error } = await api.POST('/settings', { body: { lmstudio_writer_model } })
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
      <h2 className="mb-1 text-lg font-semibold">Models</h2>
      <p className="mb-3 text-sm text-text-muted">
        The <strong>tool model</strong> picks and runs tools; the <strong>writer model</strong>{' '}
        writes the longer replies, reviews and check-in wording. Both must be loaded in LM
        Studio. Applies immediately.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <FieldRow label="Tool model">
          <div className="rounded border border-border bg-card-alt px-3 py-2 font-mono text-sm text-text-primary">
            {modelsQuery.data?.configured_model || '—'}
          </div>
          <span className="text-xs text-text-muted">Set on the Models page.</span>
        </FieldRow>
        <FieldRow label="Writer model">
          <div className="flex gap-2">
            <input
              type="text"
              value={writer}
              onChange={(e) => setWriter(e.target.value)}
              list="lmstudioModelOptions"
              placeholder="e.g. gemma-4-e4b-it (blank = tool model writes)"
              className={inputClass}
            />
            <button
              type="button"
              onClick={() => mutation.mutate(writer.trim())}
              disabled={writer.trim() === (data?.lmstudio_writer_model ?? '')}
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
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
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
        sense of "today"/"now" (calendar day boundaries, the scheduled messages).
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

function EveningCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const status = useSaveStatus()
  const [eveningTime, setEveningTime] = useState('')

  useEffect(() => {
    if (!data) return
    setEveningTime(data.evening_time || '')
  }, [data])

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/settings', {
        body: { evening_time: eveningTime },
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
      <h2 className="mb-1 text-lg font-semibold">Evening Message</h2>
      <p className="mb-3 text-sm text-text-muted">
        Local time the end-of-day message is pushed (see the Timezone above). Takes effect
        immediately, no restart needed.
      </p>
      <FieldRow label="Send time">
        <input
          type="time"
          value={eveningTime}
          onChange={(e) => setEveningTime(e.target.value)}
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
        from the evening message and from the check-in window's own times. Takes effect
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
