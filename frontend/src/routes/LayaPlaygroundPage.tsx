import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'

type QuestionType = 'yes_no' | 'choose_one' | 'choose_multiple' | 'scale' | 'tool'

type Candidate = { name: string; description: string }

type AnswerOption = { name: string; probability: number }

type PlaygroundResult = {
  question_type: string
  choice?: string | null
  yes_probability?: number | null
  score?: number | null
  levels?: string[] | null
  selected?: string[] | null
  options?: AnswerOption[] | null
  backend: string
  model: string | null
  latency_ms: number
  route: string[]
}

const QUESTION_TYPES: { value: QuestionType; label: string; hint: string }[] = [
  { value: 'yes_no', label: 'Yes / No', hint: 'Native Noul call — a single yes/no probability.' },
  { value: 'choose_one', label: 'Choose One', hint: 'Native Choice call — pick the best of several candidates.' },
  {
    value: 'choose_multiple',
    label: 'Choose Multiple',
    hint: "No native multi-select in pydecide — this runs one yes/no question per candidate in a single request, then includes any candidate scoring above the threshold.",
  },
  { value: 'scale', label: 'Rate on a Scale', hint: 'Native Score call — places the text on an ordered scale you define.' },
  { value: 'tool', label: 'Pick a Tool', hint: "Choice call against the assistant's real, current tool list — the actual use case this is all for." },
]

const inputClass =
  'w-full rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent'
const primaryBtnClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50'
const secondaryBtnClass =
  'shrink-0 rounded-lg border border-border bg-card-alt px-3 py-2 text-sm text-text-primary hover:border-accent'

function FieldRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="mb-3 flex flex-col gap-1">
      <label className="text-sm text-text-muted">{label}</label>
      {children}
      {hint && <div className="text-xs text-text-muted">{hint}</div>}
    </div>
  )
}

function CandidateEditor({
  candidates,
  onChange,
  namePlaceholder,
}: {
  candidates: Candidate[]
  onChange: (next: Candidate[]) => void
  namePlaceholder: string
}) {
  return (
    <div className="flex flex-col gap-2">
      {candidates.map((c, i) => (
        <div key={i} className="flex gap-2">
          <input
            className={inputClass}
            placeholder={namePlaceholder}
            value={c.name}
            onChange={(e) => onChange(candidates.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
          />
          <input
            className={inputClass}
            placeholder="Optional description"
            value={c.description}
            onChange={(e) =>
              onChange(candidates.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))
            }
          />
          <button
            type="button"
            className={secondaryBtnClass}
            onClick={() => onChange(candidates.filter((_, j) => j !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className={`${secondaryBtnClass} self-start`}
        onClick={() => onChange([...candidates, { name: '', description: '' }])}
      >
        Add candidate
      </button>
    </div>
  )
}

function OptionBars({ options, highlight }: { options: AnswerOption[]; highlight?: string[] }) {
  const sorted = [...options].sort((a, b) => b.probability - a.probability)
  return (
    <div className="flex flex-col gap-1.5">
      {sorted.map((o) => {
        const isHighlighted = highlight?.includes(o.name)
        return (
          <div key={o.name} className="flex items-center gap-2 text-sm">
            <div className={`w-40 truncate ${isHighlighted ? 'font-semibold text-accent' : ''}`} title={o.name}>
              {o.name}
            </div>
            <div className="h-2 flex-1 overflow-hidden rounded bg-card-alt">
              <div
                className={`h-full ${isHighlighted ? 'bg-accent' : 'bg-text-muted'}`}
                style={{ width: `${Math.round(o.probability * 100)}%` }}
              />
            </div>
            <div className="w-12 text-right text-xs text-text-muted">{Math.round(o.probability * 100)}%</div>
          </div>
        )
      })}
    </div>
  )
}

export default function LayaPlaygroundPage() {
  const [text, setText] = useState('')
  const [questionType, setQuestionType] = useState<QuestionType>('tool')
  const [instructions, setInstructions] = useState('')
  const [candidates, setCandidates] = useState<Candidate[]>([
    { name: '', description: '' },
    { name: '', description: '' },
  ])
  const [yesLabel, setYesLabel] = useState('')
  const [noLabel, setNoLabel] = useState('')
  const [threshold, setThreshold] = useState(0.5)

  const toolsQuery = useQuery({
    queryKey: ['laya-playground-tools'],
    queryFn: async () => {
      const { data } = await api.GET('/laya-playground/tools')
      return data
    },
    enabled: questionType === 'tool',
  })

  const askMutation = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        text,
        question_type: questionType,
        instructions: instructions.trim() || undefined,
      }
      if (questionType === 'choose_one' || questionType === 'choose_multiple' || questionType === 'scale') {
        body.candidates = candidates
          .filter((c) => c.name.trim())
          .map((c) => ({ name: c.name.trim(), description: c.description.trim() || undefined }))
      }
      if (questionType === 'yes_no') {
        body.yes_label = yesLabel.trim() || undefined
        body.no_label = noLabel.trim() || undefined
      }
      if (questionType === 'choose_multiple') {
        body.multi_threshold = threshold
      }
      const { data, error, response } = await api.POST('/laya-playground/ask', { body: body as never })
      if (error) {
        const detail = (error as { detail?: string })?.detail
        throw new Error(detail || `Request failed (${response.status})`)
      }
      return data as PlaygroundResult
    },
  })

  const activeType = QUESTION_TYPES.find((t) => t.value === questionType)!

  const canSubmit = useMemo(() => {
    if (!text.trim()) return false
    if (['choose_one', 'choose_multiple', 'scale'].includes(questionType)) {
      return candidates.filter((c) => c.name.trim()).length >= (questionType === 'scale' ? 2 : 1)
    }
    return true
  }, [text, questionType, candidates])

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">Laya Playground</h1>
        <p className="text-sm text-text-muted">
          Standalone space to try the Laya decision model (via pydecide) against arbitrary text — not wired into
          real tool-calling. See <code>utils/laya_client.py</code> for what "deploying" this for real still
          requires.
        </p>
      </div>

      <Card>
        <FieldRow label="Text to test">
          <textarea
            className={`${inputClass} min-h-32 resize-y`}
            placeholder="Paste or write the message/context you want Laya to judge…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </FieldRow>

        <FieldRow label="Question type">
          <div className="flex flex-wrap gap-2">
            {QUESTION_TYPES.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setQuestionType(t.value)}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  questionType === t.value
                    ? 'border-accent bg-accent text-white'
                    : 'border-border bg-card-alt text-text-primary hover:border-accent'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </FieldRow>
        <div className="mb-3 -mt-2 text-xs text-text-muted">{activeType.hint}</div>

        <FieldRow label="Instructions (optional — a sensible default is used if left blank)">
          <input
            className={inputClass}
            placeholder="e.g. Which of these best matches?"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </FieldRow>

        {questionType === 'yes_no' && (
          <div className="mb-3 flex gap-2">
            <FieldRow label="'Yes' label (optional)">
              <input className={inputClass} value={yesLabel} onChange={(e) => setYesLabel(e.target.value)} />
            </FieldRow>
            <FieldRow label="'No' label (optional)">
              <input className={inputClass} value={noLabel} onChange={(e) => setNoLabel(e.target.value)} />
            </FieldRow>
          </div>
        )}

        {(questionType === 'choose_one' || questionType === 'choose_multiple') && (
          <FieldRow label="Candidates">
            <CandidateEditor candidates={candidates} onChange={setCandidates} namePlaceholder="Candidate name" />
          </FieldRow>
        )}

        {questionType === 'scale' && (
          <FieldRow label="Levels, lowest to highest">
            <CandidateEditor candidates={candidates} onChange={setCandidates} namePlaceholder="Level label" />
          </FieldRow>
        )}

        {questionType === 'choose_multiple' && (
          <FieldRow label={`Inclusion threshold: ${Math.round(threshold * 100)}%`}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
            />
          </FieldRow>
        )}

        {questionType === 'tool' && (
          <FieldRow label={`Live tool list (${toolsQuery.data?.length ?? '…'} tools) — auto-populated, read-only`}>
            {toolsQuery.isLoading && <div className="text-sm text-text-muted">Loading tool list…</div>}
            {toolsQuery.data && (
              <div className="max-h-40 overflow-y-auto rounded border border-border bg-card-alt p-2 text-xs text-text-muted">
                {toolsQuery.data.map((t) => (
                  <div key={t.name}>
                    <span className="font-mono text-text-primary">{t.name}</span> — {t.description}
                  </div>
                ))}
              </div>
            )}
          </FieldRow>
        )}

        <button
          type="button"
          className={primaryBtnClass}
          disabled={!canSubmit || askMutation.isPending}
          onClick={() => askMutation.mutate()}
        >
          {askMutation.isPending ? 'Asking Laya…' : 'Ask Laya'}
        </button>

        {askMutation.isError && (
          <div className="mt-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {(askMutation.error as Error).message}
          </div>
        )}
      </Card>

      {askMutation.data && (
        <Card>
          <h2 className="mb-3 text-base font-semibold">Result</h2>

          {askMutation.data.question_type === 'yes_no' && askMutation.data.yes_probability != null && (
            <div className="mb-3">
              <span className="text-2xl font-semibold">{Math.round(askMutation.data.yes_probability * 100)}%</span>
              <span className="ml-2 text-text-muted">probability yes</span>
            </div>
          )}

          {(askMutation.data.question_type === 'choose_one' || askMutation.data.question_type === 'tool') &&
            askMutation.data.choice && (
              <div className="mb-3">
                <span className="text-text-muted">Chose: </span>
                <span className="font-mono text-lg font-semibold text-accent">{askMutation.data.choice}</span>
              </div>
            )}

          {askMutation.data.question_type === 'choose_multiple' && (
            <div className="mb-3">
              <span className="text-text-muted">Selected: </span>
              {askMutation.data.selected && askMutation.data.selected.length > 0 ? (
                askMutation.data.selected.map((s) => (
                  <span key={s} className="mr-2 rounded bg-accent/20 px-2 py-0.5 font-mono text-sm text-accent">
                    {s}
                  </span>
                ))
              ) : (
                <span className="text-sm text-text-muted">none above threshold</span>
              )}
            </div>
          )}

          {askMutation.data.question_type === 'scale' && askMutation.data.score != null && (
            <div className="mb-3">
              <span className="text-text-muted">Score: </span>
              <span className="font-mono text-lg font-semibold text-accent">
                {askMutation.data.score.toFixed(2)}
              </span>
              {askMutation.data.levels && (
                <span className="ml-2 text-sm text-text-muted">(0 = {askMutation.data.levels[0]}, {askMutation.data.levels.length - 1} = {askMutation.data.levels[askMutation.data.levels.length - 1]})</span>
              )}
            </div>
          )}

          {askMutation.data.options && askMutation.data.options.length > 0 && (
            <OptionBars
              options={askMutation.data.options}
              highlight={
                askMutation.data.choice
                  ? [askMutation.data.choice]
                  : askMutation.data.selected ?? undefined
              }
            />
          )}

          <div className="mt-4 border-t border-border pt-2 text-xs text-text-muted">
            backend: {askMutation.data.backend} · model: {askMutation.data.model ?? '—'} · latency:{' '}
            {Math.round(askMutation.data.latency_ms)}ms
            {askMutation.data.route.length > 0 && <> · route: {askMutation.data.route.join(' → ')}</>}
          </div>
        </Card>
      )}
    </div>
  )
}
