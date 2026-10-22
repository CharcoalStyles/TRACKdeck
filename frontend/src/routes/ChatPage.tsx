import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import ChatWidget from '../components/chat/ChatWidget'

// One conversation at a time: no thread list. Sending continues the most
// recent thread (or starts one after the idle timeout, or on a spoken
// keyword); "New chat" starts a fresh one on purpose.
export default function ChatPage() {
  const [threadId, setThreadId] = useState<string | null>(null)

  const newThread = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/threads/new')
      if (error || !data) throw new Error('Failed to start new chat')
      return data
    },
    onSuccess: (data) => setThreadId(data.thread_id),
  })

  return (
    <div className="mx-auto flex w-full max-w-2xl grow flex-col gap-3">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => newThread.mutate()}
          disabled={newThread.isPending}
          className="rounded-lg border border-accent px-3 py-1.5 text-sm font-semibold text-accent hover:bg-[#1c2b2c] disabled:opacity-50"
        >
          New chat
        </button>
      </div>
      <ChatWidget
        threadId={threadId}
        greeting="Ask about your day, or say what you want written down."
        onReply={(data) => setThreadId(data.thread_id)}
      />
    </div>
  )
}
