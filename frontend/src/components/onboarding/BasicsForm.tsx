import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import Card from '../Card'
import SaveStatus, { type SaveState } from '../SaveStatus'

const inputClass =
  'w-full rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent'
const textareaClass = `${inputClass} min-h-20`
const primaryBtnClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover'
const secondaryBtnClass =
  'shrink-0 rounded-lg border border-border bg-card-alt px-3 py-2 text-sm text-text-primary hover:border-accent'

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3 flex flex-col gap-1">
      <label className="text-sm text-text-muted">{label}</label>
      {children}
    </div>
  )
}

type Person = { name: string; relation: string }

export default function BasicsForm({ onDone = () => {} }: { onDone?: () => void }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<SaveState>('idle')

  const [name, setName] = useState('')
  const [birthday, setBirthday] = useState('')
  const [location, setLocation] = useState('')
  const [occupation, setOccupation] = useState('')
  const [currentJob, setCurrentJob] = useState('')
  const [people, setPeople] = useState<Person[]>([{ name: '', relation: '' }])
  const [preferences, setPreferences] = useState('')
  const [routine, setRoutine] = useState('')
  const [interests, setInterests] = useState('')
  const [healthGoals, setHealthGoals] = useState('')
  const [importantDates, setImportantDates] = useState('')
  const [wakeTime, setWakeTime] = useState('')
  const [bedtime, setBedtime] = useState('')

  function updatePerson(i: number, field: keyof Person, value: string) {
    setPeople((prev) => prev.map((p, idx) => (idx === i ? { ...p, [field]: value } : p)))
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/onboarding/basics', {
        body: {
          name: name || null,
          birthday: birthday || null,
          location: location || null,
          occupation: occupation || null,
          current_job: currentJob || null,
          people: people
            .filter((p) => p.name.trim())
            .map((p) => ({ name: p.name.trim(), relation: p.relation.trim() || null })),
          preferences: preferences || null,
          routine: routine || null,
          interests: interests || null,
          health_goals: healthGoals || null,
          important_dates: importantDates || null,
          wake_time: wakeTime || null,
          bedtime: bedtime || null,
        },
      })
      if (error) throw new Error()
    },
    onMutate: () => setState('saving'),
    onSuccess: () => {
      setState('saved')
      queryClient.invalidateQueries({ queryKey: ['settings-probe'] })
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      onDone()
    },
    onError: () => setState('error'),
  })

  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">The Basics</h2>
      <p className="mb-4 text-sm text-text-muted">
        Nothing here is required — fill in whatever you like, skip the rest. Once you save, the
        assistant will follow up conversationally to go deeper on anything worth it.
      </p>

      <FieldRow label="Name">
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
      </FieldRow>
      <FieldRow label="Birthday">
        <input
          type="date"
          value={birthday}
          onChange={(e) => setBirthday(e.target.value)}
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Where you live">
        <input
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="e.g. Canberra, Australia"
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Occupation / field">
        <input
          type="text"
          value={occupation}
          onChange={(e) => setOccupation(e.target.value)}
          placeholder="e.g. Software engineer"
          className={inputClass}
        />
      </FieldRow>
      <FieldRow label="Current job">
        <input
          type="text"
          value={currentJob}
          onChange={(e) => setCurrentJob(e.target.value)}
          placeholder="e.g. Acme Corp, Senior Backend Engineer"
          className={inputClass}
        />
      </FieldRow>

      <FieldRow label="Wake time">
        <input type="time" value={wakeTime} onChange={(e) => setWakeTime(e.target.value)} className={inputClass} />
      </FieldRow>
      <FieldRow label="Bedtime">
        <input type="time" value={bedtime} onChange={(e) => setBedtime(e.target.value)} className={inputClass} />
      </FieldRow>

      <div className="mb-3 flex flex-col gap-1">
        <label className="text-sm text-text-muted">People worth remembering</label>
        {people.map((p, i) => (
          <div key={i} className="flex gap-2">
            <input
              type="text"
              value={p.name}
              onChange={(e) => updatePerson(i, 'name', e.target.value)}
              placeholder="Name"
              className={inputClass}
            />
            <input
              type="text"
              value={p.relation}
              onChange={(e) => updatePerson(i, 'relation', e.target.value)}
              placeholder="Relation (e.g. sister)"
              className={inputClass}
            />
            <button
              type="button"
              onClick={() => setPeople((prev) => prev.filter((_, idx) => idx !== i))}
              className={secondaryBtnClass}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setPeople((prev) => [...prev, { name: '', relation: '' }])}
          className={`${secondaryBtnClass} self-start`}
        >
          + Add person
        </button>
      </div>

      <FieldRow label="Preferences (likes/dislikes, food, habits)">
        <textarea value={preferences} onChange={(e) => setPreferences(e.target.value)} className={textareaClass} />
      </FieldRow>
      <FieldRow label="Routine (daily/weekly patterns, work schedule)">
        <textarea value={routine} onChange={(e) => setRoutine(e.target.value)} className={textareaClass} />
      </FieldRow>
      <FieldRow label="Interests (hobbies, ongoing projects)">
        <textarea value={interests} onChange={(e) => setInterests(e.target.value)} className={textareaClass} />
      </FieldRow>
      <FieldRow label="Health & goals">
        <textarea value={healthGoals} onChange={(e) => setHealthGoals(e.target.value)} className={textareaClass} />
      </FieldRow>
      <FieldRow label="Important dates (anniversaries, other people's birthdays)">
        <textarea
          value={importantDates}
          onChange={(e) => setImportantDates(e.target.value)}
          className={textareaClass}
        />
      </FieldRow>

      <button type="button" onClick={() => mutation.mutate()} className={primaryBtnClass}>
        Save &amp; Continue
      </button>
      <SaveStatus state={state} errorMessage="Failed to save — check the location resolves, or leave it blank and set it later from Settings." />
    </Card>
  )
}
