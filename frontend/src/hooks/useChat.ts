import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  loading?: boolean
}

interface SendTextResult {
  reply: string
  thread_id: string
  keyword: string
}

interface UseChatOptions {
  threadId: string | null
  mode?: 'onboarding' | 'profile_chat' | 'project_chat' | null
  oneShot?: boolean
  agentRun?: boolean
  greeting?: string | null
  // false (default, matches index.html's ChatWidget/"+ New Chat"): greeting
  // only ever appears for the very first null-threadId render, never again
  // once a real thread (even an empty new one) is selected — setThread()
  // in the original class just clears, it doesn't re-show the greeting.
  // true (matches profile.html, which reconstructs ChatWidget per mode
  // toggle): greeting reappears any time the resolved history is empty,
  // since it's contextual to whichever mode/thread is now active.
  alwaysGreetIfEmpty?: boolean
  onSendStart?: () => void
  onReply?: (data: SendTextResult) => void
}

// Ports static/js/chat.js's ChatWidget send/history logic. Local message
// state (not a Query cache) mirrors the original class's direct DOM
// mutation — one history fetch on thread switch, then optimistic
// append/replace on send, no extra round-trip after replying.
export function useChat({
  threadId,
  mode = null,
  oneShot = false,
  agentRun = false,
  greeting = null,
  alwaysGreetIfEmpty = false,
  onSendStart,
  onReply,
}: UseChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  // The thread a send actually targets — starts as the threadId prop but
  // gets pinned to the real minted id after a null-threadId send's first
  // reply, same as the original class mutating `this.threadId` in place.
  const effectiveThreadId = useRef<string | null>(threadId)

  useEffect(() => {
    effectiveThreadId.current = threadId
    let cancelled = false

    async function load() {
      if (!threadId) {
        setMessages(greeting ? [{ role: 'assistant', content: greeting }] : [])
        return
      }
      setIsLoadingHistory(true)
      try {
        const { data } = await api.GET('/threads/{thread_id}/messages', {
          params: { path: { thread_id: threadId } },
        })
        if (cancelled) return
        // Backend only ever emits "user"/"assistant" (agent/runtime.py's
        // get_thread_messages), but the Pydantic model declares role as a
        // plain str, so narrow it here rather than widening ChatMessage.
        const history = (data?.messages ?? []) as ChatMessage[]
        setMessages(
          history.length > 0
            ? history
            : alwaysGreetIfEmpty && greeting
              ? [{ role: 'assistant', content: greeting }]
              : [],
        )
      } finally {
        if (!cancelled) setIsLoadingHistory(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
    // greeting is only read on thread switch, not a live dependency
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId])

  const sendMutation = useMutation({
    mutationFn: async (text: string) => {
      const { data, error } = await api.POST('/text', {
        body: {
          text,
          thread_id: effectiveThreadId.current,
          one_shot: oneShot,
          mode,
          agent_run: agentRun,
        },
      })
      if (error || !data) throw new Error('Send failed')
      return data
    },
  })

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed) return

    setMessages((prev) => [
      ...prev,
      { role: 'user', content: trimmed },
      { role: 'assistant', content: '...', loading: true },
    ])
    onSendStart?.()

    try {
      const data = await sendMutation.mutateAsync(trimmed)
      effectiveThreadId.current = data.thread_id
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: data.reply }
        return next
      })
      onReply?.(data)
    } catch {
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = {
          role: 'assistant',
          content: '(Something went wrong sending that — try again.)',
        }
        return next
      })
    }
  }

  return { messages, isLoadingHistory, send, isSending: sendMutation.isPending }
}
