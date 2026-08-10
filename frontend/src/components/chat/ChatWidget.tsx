import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useChat } from '../../hooks/useChat'
import { useVoiceInput } from '../../hooks/useVoiceInput'

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
  const { messages, send, isSending } = useChat({
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
  const inputRef = useRef<HTMLInputElement>(null)

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
      <form onSubmit={handleSubmit} className="flex gap-2.5 border-t border-[#2a2a2a] pt-3">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          autoComplete="off"
          disabled={disabled}
          className="flex-1 rounded-lg border border-border bg-card-alt px-3.5 py-2.5 text-sm text-text-primary outline-none focus:border-accent"
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
