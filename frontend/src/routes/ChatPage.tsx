import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import ChatWidget from '../components/chat/ChatWidget'

export default function ChatPage() {
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  // A fresh, un-onboarded install lands on the basics form instead of an
  // empty chat page — same settings-probe query ProfilePage uses, so this
  // shares its cache rather than firing a second request.
  const settingsProbe = useQuery({
    queryKey: ['settings-probe'],
    queryFn: async () => {
      const { data } = await api.GET('/settings')
      return data as { basics_complete?: boolean } | undefined
    },
  })
  useEffect(() => {
    if (settingsProbe.data && !settingsProbe.data.basics_complete) {
      navigate('/profile', { replace: true })
    }
  }, [settingsProbe.data, navigate])

  const threadsQuery = useQuery({
    queryKey: ['threads'],
    queryFn: async () => {
      const { data } = await api.GET('/threads')
      return data ?? []
    },
  })

  const newThreadMutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/threads/new')
      if (error || !data) throw new Error('Failed to start new chat')
      return data
    },
    onSuccess: (data) => {
      setActiveThreadId(data.thread_id)
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })

  const threads = threadsQuery.data ?? []

  return (
    <div className="flex flex-col md:flex-row grow gap-0 -m-4">
      <aside className="flex w-full md:w-55 shrink-0 flex-col border-r border-[#2a2a2a] bg-header p-4">
        <button
          onClick={() => newThreadMutation.mutate()}
          className="mb-4 rounded-lg border border-accent px-3 py-2 text-sm font-semibold text-accent hover:bg-[#1c2b2c]"
        >
          + New Chat
        </button>
        <div className="flex flex-1 flex-col gap-1 overflow-y-auto">
          {threads.length === 0 ? (
            <div className="px-2.5 py-2 text-sm text-text-faint">
              {threadsQuery.isPending ? 'Loading...' : 'No conversations yet today — start one below.'}
            </div>
          ) : (
            threads.map((t) => (
              <button
                key={t.thread_id}
                onClick={() => setActiveThreadId(t.thread_id)}
                title={t.keyword}
                className={`overflow-hidden text-ellipsis whitespace-nowrap rounded-md px-2.5 py-2 text-left text-sm ${
                  t.thread_id === activeThreadId
                    ? 'bg-[#1c2b2c] font-semibold text-accent'
                    : 'text-[#aaaaaa] hover:bg-[#222222] hover:text-text-primary'
                }`}
              >
                {t.keyword}
              </button>
            ))
          )}
        </div>
      </aside>
      <main className="flex grow flex-col p-5">
        <ChatWidget
          threadId={activeThreadId}
          greeting="Pick a conversation on the left, or start a new one — this talks to the same agent as everything else, no fixed mode."
          onReply={(data) => {
            setActiveThreadId(data.thread_id)
            queryClient.invalidateQueries({ queryKey: ['threads'] })
          }}
        />
      </main>
    </div>
  )
}
