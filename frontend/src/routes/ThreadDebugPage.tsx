import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'

// GET /debug/thread/{id} is a genuinely loose debug/inspection payload
// (optional fields vary by message type) — typed locally here rather
// than via a backend response_model, matching the plan's call to leave
// debug endpoints as light casts rather than fully modeling every shape.
interface RecallMatch {
  distance: number
  thread_id: string
  timestamp: number | null
  document: string
}
interface ToolCall {
  name: string
  args: Record<string, unknown>
}
interface Turn {
  type: string
  content: string | null
  tool_calls?: ToolCall[]
  tool_name?: string | null
  recall_query?: string
  recalled?: RecallMatch[]
}
interface ThreadDebugData {
  thread_id: string
  opening_message: string | null
  turns: Turn[]
}

const ROLE_LABEL: Record<string, string> = { human: 'User', ai: 'Assistant', tool: 'Tool result' }

function formatTime(epochSeconds: number | null) {
  if (epochSeconds == null) return '—'
  return new Date(epochSeconds * 1000).toLocaleString()
}

export default function ThreadDebugPage() {
  const [selectedThread, setSelectedThread] = useState('')
  const [result, setResult] = useState<ThreadDebugData | null>(null)

  const threadsQuery = useQuery({
    queryKey: ['debug-threads'],
    queryFn: async () => {
      const { data } = await api.GET('/debug/threads')
      return data?.threads ?? []
    },
  })

  const loadMutation = useMutation({
    mutationFn: async (threadId: string) => {
      const { data } = await api.GET('/debug/thread/{thread_id}', {
        params: { path: { thread_id: threadId } },
      })
      return data as unknown as ThreadDebugData
    },
    onSuccess: (data) => setResult(data),
  })

  const threads = threadsQuery.data ?? []

  useEffect(() => {
    if (!selectedThread && threads.length > 0) setSelectedThread(threads[0].thread_id)
  }, [threads, selectedThread])

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Thread Debug</h2>
        <p className="mb-3 text-sm text-text-muted">
          Full trace for one thread, straight from memory.db's checkpoint — including threads
          swept from the sidebar by the nightly digest, or from before the last restart. Shows
          every turn (tool calls and their results included, unlike the Chat page), with each
          assistant reply annotated by what cross-thread recall actually pulled in for it.
          There's no reasoning trace — the model never emits reasoning separate from tool calls
          or its final reply.
        </p>
        <div className="flex gap-2">
          <select
            value={selectedThread}
            onChange={(e) => setSelectedThread(e.target.value)}
            disabled={threads.length === 0}
            className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary"
          >
            {threads.length === 0 ? (
              <option>No threads yet</option>
            ) : (
              threads.map((t) => (
                <option key={t.thread_id} value={t.thread_id}>
                  {t.thread_id}
                </option>
              ))
            )}
          </select>
          <button
            type="button"
            disabled={!selectedThread || loadMutation.isPending}
            onClick={() => loadMutation.mutate(selectedThread)}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
          >
            Load
          </button>
        </div>
      </Card>

      {result && (
        <>
          <Card>
            <h2 className="mb-1 text-lg font-semibold">Opening message</h2>
            <p className="text-sm text-text-muted">
              {result.opening_message ?? '(none — thread has no human message)'}
            </p>
          </Card>

          {result.turns.map((turn, i) => (
            <Card key={i}>
              <h2 className="mb-1 text-lg font-semibold">
                {turn.type === 'tool' && turn.tool_name
                  ? `Tool result — ${turn.tool_name}`
                  : (ROLE_LABEL[turn.type] ?? turn.type)}
              </h2>
              {turn.content && <p className="whitespace-pre-wrap text-sm text-text-muted">{turn.content}</p>}
              {turn.tool_calls?.map((call, j) => (
                <pre
                  key={j}
                  className="mt-3 whitespace-pre-wrap break-words rounded-lg border border-[#2a2a2a] bg-header p-3 text-sm"
                >
                  {`${call.name}(${JSON.stringify(call.args, null, 2)})`}
                </pre>
              ))}
              {turn.recalled !== undefined && (
                <>
                  <p className="mb-1 mt-3 text-xs font-semibold text-text-muted">
                    Cross-thread recall for this turn:
                  </p>
                  {turn.recalled.length === 0 ? (
                    <p className="text-sm text-text-muted">
                      Nothing recalled — no match cleared the distance/recency/thread-exclusion
                      filters.
                    </p>
                  ) : (
                    turn.recalled.map((match, k) => (
                      <pre
                        key={k}
                        className="mt-2 whitespace-pre-wrap break-words rounded-lg border border-[#2a2a2a] bg-header p-3 text-sm"
                      >
                        {`distance=${match.distance.toFixed(3)}  thread=${match.thread_id}  ${formatTime(match.timestamp)}\n${match.document}`}
                      </pre>
                    ))
                  )}
                </>
              )}
            </Card>
          ))}
        </>
      )}
    </div>
  )
}
