import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'

type LmStudioModel = {
  id: string
  state: string
  max_context_length: number | null
  loaded_context_length: number | null
}

function formatContext(length: number | null) {
  if (length === null) return '—'
  if (length >= 1000) return `${Math.round(length / 1000)}k`
  return String(length)
}

export default function ModelsPage() {
  const queryClient = useQueryClient()
  const [manualModel, setManualModel] = useState('')

  const modelsQuery = useQuery({
    queryKey: ['lmstudio-models'],
    queryFn: async () => {
      const { data } = await api.GET('/debug/lmstudio-models')
      return data
    },
  })

  const switchMutation = useMutation({
    mutationFn: async (modelId: string) => {
      const { error } = await api.POST('/settings', { body: { lmstudio_chat_model: modelId } })
      if (error) throw new Error('Failed to switch model')
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['lmstudio-models'] }),
  })

  const configuredModel = modelsQuery.data?.configured_model ?? null

  // Keeps the manual-entry field in sync with whatever's actually
  // configured (e.g. after picking a row from the table below, or after a
  // page reload) without fighting the user's own typing mid-edit.
  useEffect(() => {
    setManualModel(configuredModel ?? '')
  }, [configuredModel])

  const models: LmStudioModel[] = modelsQuery.data?.models ?? []
  const managementConfigured = modelsQuery.data?.management_configured ?? false

  return (
    <>
      <Card>
        <h2 className="mb-1 text-lg font-semibold">LM Studio Models</h2>
        <p className="mb-3 text-sm text-text-muted">
          {managementConfigured ? (
            <>
              Live catalog from LM Studio's local management API — every model it currently has
              downloaded, its context length, and whether it's actually loaded right now.
            </>
          ) : (
            <>
              <code>LMSTUDIO_MANAGEMENT_URL</code> isn't set, so the local catalog can't be listed
              here — type the exact model id LM Studio should use instead.
            </>
          )}
        </p>
        <p className="mb-3 text-sm text-accent">
          {managementConfigured ? 'Click a model below to switch immediately, no restart needed.' : ''}
          {configuredModel && <> Currently: {configuredModel}</>}
        </p>
        {!managementConfigured && (
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={manualModel}
              onChange={(e) => setManualModel(e.target.value)}
              placeholder="e.g. qwen2.5-7b-instruct"
              className="min-w-0 flex-1 rounded border border-border bg-card-alt px-2 py-1 text-sm text-text-primary"
            />
            <button
              type="button"
              onClick={() => switchMutation.mutate(manualModel.trim())}
              disabled={!manualModel.trim() || switchMutation.isPending}
              className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent disabled:opacity-50"
            >
              Save
            </button>
          </div>
        )}
      </Card>

      {managementConfigured && (
        <Card className="p-0">
          {modelsQuery.isPending ? (
            <p className="p-6 text-sm text-text-muted">Loading...</p>
          ) : modelsQuery.isError ? (
            <p className="p-6 text-sm text-text-muted">
              Failed to reach LM Studio's management API — check server logs.
            </p>
          ) : models.length === 0 ? (
            <p className="p-6 text-sm text-text-muted">
              No models found — download one in LM Studio first.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-text-muted">
                    <th className="px-4 py-2 font-medium">Model</th>
                    <th className="px-4 py-2 font-medium">Context</th>
                    <th className="px-4 py-2 font-medium">State</th>
                    {managementConfigured && <th className="px-4 py-2 font-medium" />}
                  </tr>
                </thead>
                <tbody>
                  {models.map((model) => {
                    const isActiveModel = model.id === configuredModel
                    const isLoaded = model.state === 'loaded'
                    return (
                      <tr
                        key={model.id}
                        className={`border-b border-border last:border-0 ${isActiveModel ? 'bg-card-alt' : ''}`}
                      >
                        <td className="px-4 py-2 text-text-primary">{model.id}</td>
                        <td className="px-4 py-2 text-text-muted">
                          {formatContext(model.loaded_context_length ?? model.max_context_length)}
                        </td>
                        <td className={`px-4 py-2 ${isLoaded ? 'text-accent' : 'text-text-muted'}`}>
                          {isLoaded ? 'Loaded' : 'Not loaded'}
                        </td>
                        {managementConfigured && (
                          <td className="px-4 py-2 text-right">
                            {isActiveModel ? (
                              <span className="text-xs font-semibold text-accent">Active</span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => switchMutation.mutate(model.id)}
                                disabled={switchMutation.isPending}
                                className="rounded border border-border bg-card-alt px-2 py-1 text-xs hover:border-accent disabled:opacity-50"
                              >
                                Set active
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </>
  )
}
