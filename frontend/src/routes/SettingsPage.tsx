import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { components } from '../api/schema'
import Card from '../components/Card'
import SaveStatus, { type SaveState } from '../components/SaveStatus'

const TIMEZONES =
  typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : []

type Settings = components['schemas']['SettingsResponse']
type SettingsBody = components['schemas']['SettingsUpdate']

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
      <ScheduleCard data={data} onSaved={invalidate} />
      <NotificationsCard data={data} onSaved={invalidate} />
      <PlanningCard data={data} onSaved={invalidate} />
      <SyncCard data={data} onSaved={invalidate} />
      <details className="rounded-xl border border-border bg-card p-4">
        <summary className="cursor-pointer text-lg font-semibold">Advanced</summary>
        <div className="mt-4 flex flex-col gap-4">
          <ContextBudgetCard data={data} onSaved={invalidate} />
          <McpServersCard data={data} onSaved={invalidate} />
        </div>
      </details>
    </div>
  )
}

function formatContext(length: number | null | undefined) {
  if (length == null) return null
  return length >= 1000 ? `${Math.round(length / 1000)}k ctx` : `${length} ctx`
}

function ModelsCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const { status, save } = useSettingsSave(onSaved)
  const [tool, setTool] = useState('')
  const [writer, setWriter] = useState('')

  const modelsQuery = useQuery({
    queryKey: ['lmstudio-models'],
    queryFn: async () => {
      const { data } = await api.GET('/debug/lmstudio-models')
      return data
    },
  })

  useEffect(() => {
    if (!data) return
    setTool(data.lmstudio_chat_model || '')
    setWriter(data.lmstudio_writer_model || '')
  }, [data])

  const models = modelsQuery.data?.models ?? []
  const canList = (modelsQuery.data?.management_configured ?? false) && models.length > 0
  const byId = new Map(models.map((m) => [m.id, m]))
  const unchanged =
    tool.trim() === (data?.lmstudio_chat_model ?? '') &&
    writer.trim() === (data?.lmstudio_writer_model ?? '')

  const optionLabel = (id: string) => {
    const m = byId.get(id)
    if (!m) return `${id} (not in LM Studio's list)`
    return [id, formatContext(m.loaded_context_length ?? m.max_context_length), m.state === 'loaded' ? 'loaded' : 'not loaded']
      .filter(Boolean)
      .join(' · ')
  }

  const picker = (value: string, onChange: (v: string) => void, blankLabel?: string) => {
    if (!canList) {
      return (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={blankLabel ?? 'LM Studio model id'}
          className={inputClass}
        />
      )
    }
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
        {blankLabel !== undefined && <option value="">{blankLabel}</option>}
        {blankLabel === undefined && !value && (
          <option value="" disabled>
            Choose a model…
          </option>
        )}
        {value && !byId.has(value) && <option value={value}>{optionLabel(value)}</option>}
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {optionLabel(m.id)}
          </option>
        ))}
      </select>
    )
  }

  const notLoaded = [tool, writer].filter((id) => id && byId.has(id) && byId.get(id)?.state !== 'loaded')

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Models</h2>
      <p className="mb-3 text-sm text-text-muted">
        The <strong>tool model</strong> picks and runs tools; the <strong>writer model</strong>{' '}
        writes the longer replies, reviews and check-in wording. Both must be loaded in LM
        Studio. Applies immediately.
      </p>
      {!modelsQuery.isPending && !canList && (
        <p className="mb-3 text-sm text-text-muted">
          {modelsQuery.data?.management_configured
            ? "LM Studio's model list is empty or unreachable"
            : 'LMSTUDIO_MANAGEMENT_URL is not set'}
          , so type the exact model ids instead.
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <FieldRow label="Tool model">{picker(tool, setTool)}</FieldRow>
        <FieldRow label="Writer model">{picker(writer, setWriter, 'None (tool model writes)')}</FieldRow>
      </div>
      {notLoaded.length > 0 && (
        <p className="mt-2 text-sm text-accent">
          Not loaded in LM Studio right now: {notLoaded.join(', ')}.
        </p>
      )}
      <button
        type="button"
        onClick={() =>
          save({ lmstudio_chat_model: tool.trim(), lmstudio_writer_model: writer.trim() })
        }
        disabled={unchanged || !tool.trim()}
        className={`${primaryBtnClass} mt-3 disabled:cursor-not-allowed disabled:opacity-50`}
      >
        Save
      </button>
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

function useSettingsSave(onSaved: () => void, failMessage?: string) {
  const status = useSaveStatus()
  const mutation = useMutation({
    mutationFn: async (body: SettingsBody) => {
      const { error } = await api.POST('/settings', { body })
      if (error) throw new Error()
    },
    onMutate: () => status.setState('saving'),
    onSuccess: () => {
      status.setErrorMessage(undefined)
      status.setState('saved')
      onSaved()
    },
    onError: () => {
      if (failMessage) status.setErrorMessage(failMessage)
      status.setState('error')
    },
  })
  return { status, save: (body: SettingsBody) => mutation.mutate(body) }
}

function ScheduleGroup({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  return (
    <section className="mt-5 border-t border-border pt-4 first-of-type:mt-3 first-of-type:border-t-0 first-of-type:pt-0">
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="mb-3 text-sm text-text-muted">{note}</p>
      {children}
    </section>
  )
}

function ScheduleCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const { status, save } = useSettingsSave(onSaved)
  const [morning, setMorning] = useState('')
  const [weather, setWeather] = useState(true)
  const [podcast, setPodcast] = useState(true)
  const [checkinStart, setCheckinStart] = useState('')
  const [latest, setLatest] = useState('')
  const [eveningTime, setEveningTime] = useState('')
  const [commentary, setCommentary] = useState(true)
  const [bedtime, setBedtime] = useState('')
  const [wake, setWake] = useState('')
  const [weekly, setWeekly] = useState('')
  const [timing, setTiming] = useState('last_evening')
  const [monthlyEvening, setMonthlyEvening] = useState('')
  const [monthlyMorning, setMonthlyMorning] = useState('')

  useEffect(() => {
    if (!data) return
    setMorning(data.morning_time || '')
    setWeather(data.weather_enabled)
    setPodcast(data.podcast_enabled)
    setCheckinStart(data.checkin_start_time || '')
    setLatest(data.latest_checkin_time || '')
    setEveningTime(data.evening_time || '')
    setCommentary(data.daily_commentary)
    setBedtime(data.bedtime || '')
    setWake(data.wake_time || '')
    setWeekly(data.weekly_review_time || '')
    setTiming(data.monthly_review_timing || 'last_evening')
    setMonthlyEvening(data.monthly_review_evening_time || '')
    setMonthlyMorning(data.monthly_review_morning_time || '')
  }, [data])

  const time = (value: string, set: (v: string) => void) => (
    <input type="time" value={value} onChange={(e) => set(e.target.value)} className={inputClass} />
  )

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Schedule</h2>
      <p className="text-sm text-text-muted">
        When each part of the day happens, in the timezone above. Every time is independent.
        Takes effect immediately.
      </p>

      <ScheduleGroup
        title="Morning message"
        note="The day-ahead message: calendar, tasks, and the forecast for today and tomorrow."
      >
        <FieldRow label="Send at">{time(morning, setMorning)}</FieldRow>
        <CheckRow checked={weather} onChange={setWeather} label="Include the weather forecast" />
        <CheckRow
          checked={podcast}
          onChange={setPodcast}
          label="Make the morning podcast (starts 25 minutes before, so the message can link to it)"
        />
      </ScheduleGroup>

      <ScheduleGroup
        title="Check-ins"
        note="Short reflection prompts at random times inside this window."
      >
        <div className="grid gap-3 md:grid-cols-2">
          <FieldRow label="Window opens">{time(checkinStart, setCheckinStart)}</FieldRow>
          <FieldRow label="Latest prompt">{time(latest, setLatest)}</FieldRow>
        </div>
      </ScheduleGroup>

      <ScheduleGroup
        title="Evening message"
        note="Bedtime, unticked captures and tomorrow's heads-up."
      >
        <FieldRow label="Send at">{time(eveningTime, setEveningTime)}</FieldRow>
        <CheckRow
          checked={commentary}
          onChange={setCommentary}
          label="Save it as a daily commentary under Reviews/Daily/"
        />
      </ScheduleGroup>

      <ScheduleGroup title="Bedtime reminder" note="A separate wind-down nudge.">
        <FieldRow label="Remind at">{time(bedtime, setBedtime)}</FieldRow>
      </ScheduleGroup>

      <ScheduleGroup
        title="Day planning"
        note="Generated schedules start from this time unless you give another."
      >
        <FieldRow label="Wake time">{time(wake, setWake)}</FieldRow>
      </ScheduleGroup>

      <ScheduleGroup
        title="Weekly review"
        note="Goes out on Sunday and is saved under Reviews/Weekly/."
      >
        <FieldRow label="Send at">{time(weekly, setWeekly)}</FieldRow>
      </ScheduleGroup>

      <ScheduleGroup
        title="Monthly review"
        note="Either on the evening of the month's last day or on the morning of the 1st (covering the month just ended). Saved under Reviews/Monthly/."
      >
        <FieldRow label="When">
          <select value={timing} onChange={(e) => setTiming(e.target.value)} className={inputClass}>
            <option value="last_evening">Evening of the last day of the month</option>
            <option value="first_morning">Morning of the 1st</option>
          </select>
        </FieldRow>
        <div className="grid gap-3 md:grid-cols-2">
          <FieldRow label="Last-day evening time">{time(monthlyEvening, setMonthlyEvening)}</FieldRow>
          <FieldRow label="First-of-month morning time">{time(monthlyMorning, setMonthlyMorning)}</FieldRow>
        </div>
      </ScheduleGroup>

      <button
        type="button"
        onClick={() =>
          save({
            morning_time: morning,
            weather_enabled: weather,
            podcast_enabled: podcast,
            checkin_start_time: checkinStart,
            latest_checkin_time: latest,
            evening_time: eveningTime,
            daily_commentary: commentary,
            bedtime,
            wake_time: wake,
            weekly_review_time: weekly,
            monthly_review_timing: timing,
            monthly_review_evening_time: monthlyEvening,
            monthly_review_morning_time: monthlyMorning,
          })
        }
        className={primaryBtnClass}
      >
        Save schedule
      </button>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

function PlanningCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const { status, save } = useSettingsSave(onSaved)
  const [templateId, setTemplateId] = useState('')
  const [chimeId, setChimeId] = useState('')

  const soundsQuery = useQuery({
    queryKey: ['alert-sounds'],
    queryFn: async () => {
      const { data } = await api.GET('/alert-sounds')
      return data?.alert_sounds ?? []
    },
  })

  useEffect(() => {
    if (!data) return
    setTemplateId(data.planning_template_note_id || '')
    setChimeId(data.chime_alert_sound_id || '')
  }, [data])

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Day planning</h2>
      <p className="mb-3 text-sm text-text-muted">
        A new day&apos;s planning note starts from the template note below (blank = empty
        headings). The chime sound is pinned on the reminders generated at schedule-block
        boundaries (blank = a random sound).
      </p>
      <FieldRow label="Template note id">
        <input
          type="text"
          value={templateId}
          onChange={(e) => setTemplateId(e.target.value)}
          placeholder="blank = no template"
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Chime sound">
        <select value={chimeId} onChange={(e) => setChimeId(e.target.value)} className={inputClass}>
          <option value="">Random (default)</option>
          {(soundsQuery.data ?? []).map((sound) => (
            <option key={sound.id} value={sound.id}>
              {sound.display_name}
            </option>
          ))}
        </select>
      </FieldRow>
      <button
        type="button"
        onClick={() => save({ planning_template_note_id: templateId, chime_alert_sound_id: chimeId })}
        className={primaryBtnClass}
      >
        Save
      </button>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

function NotificationsCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const { status, save } = useSettingsSave(onSaved)
  const [email, setEmail] = useState('')
  const [gotifyUrl, setGotifyUrl] = useState('')
  const [gotifyToken, setGotifyToken] = useState('')
  const [publicBaseUrl, setPublicBaseUrl] = useState('')

  useEffect(() => {
    if (!data) return
    setEmail(data.email_to || '')
    setGotifyUrl(data.gotify_url || '')
    setPublicBaseUrl(data.public_base_url || '')
    setGotifyToken('')
  }, [data])

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Delivery</h2>
      <p className="mb-3 text-sm text-text-muted">
        Every scheduled message goes out by Gotify push and, when a recipient is set, by email
        too (needs the SMTP_* env vars; test both on the Testing page). The base URL builds
        the tap-to-open links in check-in pushes.
      </p>
      <FieldRow label="Email recipient">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="blank = push only"
          className={inputClass}
        />
      </FieldRow>
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
      <button
        type="button"
        onClick={() => {
          const body: SettingsBody = { email_to: email, gotify_url: gotifyUrl, public_base_url: publicBaseUrl }
          // A blank token field keeps the saved token.
          if (gotifyToken) body.gotify_token = gotifyToken
          save(body)
        }}
        className={primaryBtnClass}
      >
        Save
      </button>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
    </Card>
  )
}

function SyncCard({ data, onSaved }: { data?: Settings; onSaved: () => void }) {
  const { status, save } = useSettingsSave(
    onSaved,
    'Failed to save — calendar sync is 1–1440 minutes, device poll 30–86400 seconds.',
  )
  const [syncMinutes, setSyncMinutes] = useState('')
  const [pollSeconds, setPollSeconds] = useState('')

  useEffect(() => {
    if (!data) return
    setSyncMinutes(String(data.calendar_sync_interval_minutes ?? ''))
    setPollSeconds(String(data.device_poll_interval_seconds ?? ''))
  }, [data])

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Sync</h2>
      <p className="mb-3 text-sm text-text-muted">
        How often the app polls the calendar for new or moved events, and how often the
        ESP32-S3 wakes from deep sleep to sync (it reads this on its next sync, no reflash).
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <FieldRow label="Calendar sync (minutes)">
          <input
            type="number"
            min={1}
            max={1440}
            value={syncMinutes}
            onChange={(e) => setSyncMinutes(e.target.value)}
            className={inputClass}
          />
        </FieldRow>
        <FieldRow label="Device poll (seconds)">
          <input
            type="number"
            min={30}
            max={86400}
            value={pollSeconds}
            onChange={(e) => setPollSeconds(e.target.value)}
            className={inputClass}
          />
        </FieldRow>
      </div>
      <button
        type="button"
        onClick={() =>
          save({
            calendar_sync_interval_minutes: parseInt(syncMinutes, 10),
            device_poll_interval_seconds: parseInt(pollSeconds, 10),
          })
        }
        className={primaryBtnClass}
      >
        Save
      </button>
      <SaveStatus state={status.state} errorMessage={status.errorMessage} />
      <p className="mt-3 text-sm text-text-muted">
        Device alert sounds are managed on the{' '}
        <Link to="/admin/alert-sounds" className="text-accent hover:underline">
          alert sounds page
        </Link>
        .
      </p>
    </Card>
  )
}

function CheckRow({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: string
}) {
  return (
    <label className="mb-3 flex items-center gap-2 text-sm text-text-primary">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
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
