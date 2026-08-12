import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import ChatWidget from '../components/chat/ChatWidget'
import BasicsForm from '../components/onboarding/BasicsForm'

type ProfileMode = 'onboarding' | 'profile_chat'

const COPY: Record<ProfileMode, { title: string; description: string; greeting: string }> = {
  onboarding: {
    title: 'Get to Know You',
    description:
      "A guided conversation to help build out your profile — the agent will ask about things worth remembering, but you can stop at any point. Whatever's been said already stays saved.",
    greeting:
      "Thanks for filling that in — want to tell me more about any of it? I can go deeper on people, routine, health, or anything else worth remembering. Nothing here is required, and you can stop whenever you like.",
  },
  profile_chat: {
    title: 'Your Profile',
    description:
      "Ask what's currently known about you, or just tell it something to add or correct — this talks directly to your About Me note.",
    greeting: "What would you like to know, or is there something to add or correct?",
  },
}

const primaryBtnClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover'
const secondaryBtnClass =
  'rounded-lg border border-border bg-card-alt px-3 py-2 text-sm font-medium text-text-primary hover:border-accent'

export default function ProfilePage() {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({
    queryKey: ['settings-probe'],
    queryFn: async () => {
      const { data } = await api.GET('/settings')
      return data as { onboarding_complete?: boolean; basics_complete?: boolean } | undefined
    },
  })

  const [viewOverride, setViewOverride] = useState<ProfileMode | null>(null)
  const basicsComplete = settingsQuery.data?.basics_complete ?? false
  const onboardingComplete = settingsQuery.data?.onboarding_complete ?? false
  const resolvedMode: ProfileMode = viewOverride ?? (onboardingComplete ? 'profile_chat' : 'onboarding')
  const copy = COPY[resolvedMode]

  const finishMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/onboarding/complete')
      if (error) throw new Error()
    },
    onSuccess: () => {
      setViewOverride(null)
      queryClient.invalidateQueries({ queryKey: ['settings-probe'] })
    },
  })

  if (!basicsComplete) {
    return (
      <div className="mx-auto max-w-2xl">
        <BasicsForm />
      </div>
    )
  }

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
      <div className="mt-4 flex gap-2">
        {resolvedMode === 'onboarding' && !onboardingComplete && (
          <button
            type="button"
            onClick={() => finishMutation.mutate()}
            disabled={finishMutation.isPending}
            className={primaryBtnClass}
          >
            Finished — Skip to Profile Q&amp;A
          </button>
        )}
        {resolvedMode === 'onboarding' && onboardingComplete && (
          <button type="button" onClick={() => setViewOverride('profile_chat')} className={secondaryBtnClass}>
            ← Back to Profile Q&amp;A
          </button>
        )}
        {resolvedMode === 'profile_chat' && (
          <button type="button" onClick={() => setViewOverride('onboarding')} className={secondaryBtnClass}>
            ← Redo the onboarding interview
          </button>
        )}
      </div>
    </div>
  )
}
