import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useChat } from '../../hooks/useChat'
import { useVoiceInput } from '../../hooks/useVoiceInput'

function formatTokenCount(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

interface ChatWidgetProps {
  threadId: string | null
  mode?: 'onboarding' | 'profile_chat' | 'project_chat' | null
  oneShot?: boolean
  agentRun?: boolean
  greeting?: string | null
  alwaysGreetIfEmpty?: boolean
  onSendStart?: () => void
  onReply?: (data: { reply: string; thread_id: string; keyword: string }) => void
}

export default function ChatWidget({
  threadId,
  mode = null,
  oneShot = false,
  agentRun = false,
  greeting = null,
  alwaysGreetIfEmpty = false,
  onSendStart,
  onReply,
}: ChatWidgetProps) {
  const { messages, send, isSending, size, clearConversation } = useChat({
    threadId,
    mode,
    oneShot,
    agentRun,
    greeting,
    alwaysGreetIfEmpty,
    onSendStart,
    onReply,
  })
  const voice = useVoiceInput()
  const [input, setInput] = useState('')
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const formRef = useRef<HTMLFormElement>(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [messages])

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!input.trim() || isSending) return
    const text = input
    setInput('')
    void send(text)
  }

  function handleInputKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      formRef.current?.requestSubmit()
    }
  }

  async function handleClear() {
    if (!window.confirm('Clear this conversation? This cannot be undone.')) return
    await clearConversation()
  }

  async function handleMicClick() {
    setVoiceError(null)
    try {
      const transcript = await voice.toggle()
      if (transcript !== null) {
        if (!transcript.trim()) {
          setVoiceError("Didn't catch that — try again.")
          return
        }
        void send(transcript)
      }
    } catch {
      setVoiceError('Could not use the microphone — try typing instead.')
    }
  }

  const micLabel = voice.state === 'recording' ? '⏹️' : voice.state === 'transcribing' ? '…' : '🎙️'
  const disabled = isSending || voice.state === 'transcribing'

  return (
    <div className="flex grow min-h-90 flex-col">
      <div ref={logRef} className="flex flex-1 flex-col gap-2.5 overflow-y-auto px-0.5 pb-4 pt-1">
        {messages.map((m, i) => (
          <div
            key={i}
            className={
              m.role === 'user'
                ? 'max-w-[80%] self-end whitespace-pre-wrap break-words rounded-xl rounded-br-[3px] bg-accent px-3.5 py-2.5 text-sm leading-relaxed text-[#06181a]'
                : `max-w-[80%] self-start whitespace-pre-wrap break-words rounded-xl rounded-bl-[3px] bg-card-alt px-3.5 py-2.5 text-sm leading-relaxed text-text-primary ${m.loading ? 'italic text-text-muted' : ''}`
            }
          >
            {m.content}
          </div>
        ))}
        {voiceError && <div className="self-start text-sm italic text-text-muted">{voiceError}</div>}
      </div>
      {size && size.message_count > 0 && (
        <div className="flex items-center justify-between px-0.5 pb-1.5 text-xs text-text-muted">
          <span className={size.estimated_tokens / size.budget_tokens > 0.8 ? 'text-danger' : ''}>
            {formatTokenCount(size.estimated_tokens)} / {formatTokenCount(size.budget_tokens)} tokens
          </span>
          <button
            type="button"
            onClick={handleClear}
            className="text-text-muted underline decoration-dotted hover:text-text-primary"
          >
            Clear conversation
          </button>
        </div>
      )}
      <form ref={formRef} onSubmit={handleSubmit} className="flex gap-2.5 border-t border-[#2a2a2a] pt-3">
        <textarea
          ref={inputRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleInputKeyDown}
          placeholder="Type a message... (Shift+Enter for a new line)"
          autoComplete="off"
          disabled={disabled}
          className="max-h-40 flex-1 resize-none rounded-lg border border-border bg-card-alt px-3.5 py-2.5 text-sm text-text-primary outline-none field-sizing-content focus:border-accent"
        />
        <button
          type="button"
          onClick={handleMicClick}
          disabled={disabled}
          aria-label="Dictate message"
          title="Dictate message"
          className={`rounded-full px-3.5 py-2.5 text-base font-semibold text-white transition-colors disabled:opacity-70 ${
            voice.state === 'recording'
              ? 'animate-pulse bg-danger-hover'
              : voice.state === 'transcribing'
                ? 'bg-text-muted'
                : 'bg-accent hover:bg-accent-hover'
          }`}
        >
          {micLabel}
        </button>
        <button
          type="submit"
          disabled={disabled}
          className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-70"
        >
          Send
        </button>
      </form>
    </div>
  )
}
