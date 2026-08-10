import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import ChatWidget from '../components/chat/ChatWidget'

type ProfileMode = 'onboarding' | 'profile_chat'

const COPY: Record<ProfileMode, { title: string; description: string; toggleLabel: string; greeting: string }> = {
  onboarding: {
    title: 'Get to Know You',
    description:
      "A guided conversation to help build out your profile — the agent will ask about things worth remembering, but you can stop at any point. Whatever's been said already stays saved.",
    toggleLabel: 'Skip to Profile Q&A →',
    greeting:
      "Hey — let's get to know you a bit. Nothing here is required, and you can stop whenever you like. To start, what do you do for work, or spend most of your time on?",
  },
  profile_chat: {
    title: 'Your Profile',
    description:
      "Ask what's currently known about you, or just tell it something to add or correct — this talks directly to your About Me note.",
    toggleLabel: '← Redo the onboarding interview',
    greeting: "What would you like to know, or is there something to add or correct?",
  },
}

export default function ProfilePage() {
  // Settings' GET response has no typed model yet (added when SettingsPage
  // is built) — narrow cast for the one field needed here in the meantime.
  const settingsQuery = useQuery({
    queryKey: ['settings-probe'],
    queryFn: async () => {
      const { data } = await api.GET('/settings')
      return data as { onboarding_complete?: boolean } | undefined
    },
  })

  const [mode, setMode] = useState<ProfileMode | null>(null)
  const resolvedMode: ProfileMode =
    mode ?? (settingsQuery.data?.onboarding_complete ? 'profile_chat' : 'onboarding')
  const copy = COPY[resolvedMode]

  return (
    <div className="flex flex-col mx-auto max-w-2xl rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-lg font-semibold">{copy.title}</h2>
      <p className="mb-4 text-sm text-text-muted">{copy.description}</p>
      <ChatWidget
        key={resolvedMode}
        threadId={resolvedMode}
        mode={resolvedMode}
        greeting={copy.greeting}
        alwaysGreetIfEmpty
      />
      <div className="mt-4">
        <button
          type="button"
          onClick={() => setMode(resolvedMode === 'onboarding' ? 'profile_chat' : 'onboarding')}
          className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm font-medium text-text-primary hover:border-accent"
        >
          {copy.toggleLabel}
        </button>
      </div>
    </div>
  )
}
