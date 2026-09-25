import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import Card from '../components/Card'

type OpenRouterModel = {
  id: string
  name: string
  context_length: number | null
  prompt_price_per_million: number | null
  completion_price_per_million: number | null
  is_free: boolean
}

type LmStudioModel = {
  id: string
  state: string
  max_context_length: number | null
  loaded_context_length: number | null
}

type SortKey = 'name' | 'context_length' | 'prompt_price_per_million'

function formatContext(length: number | null) {
  if (length === null) return '—'
  if (length >= 1000) return `${Math.round(length / 1000)}k`
  return String(length)
}

function formatPrice(model: OpenRouterModel) {
  if (model.is_free) return 'Free'
  if (model.prompt_price_per_million === null || model.completion_price_per_million === null) return '—'
  return `$${model.prompt_price_per_million.toFixed(2)} / $${model.completion_price_per_million.toFixed(2)}`
}

type Tab = 'openrouter' | 'lmstudio'

function useActiveProviderQuery() {
  // Shared across both tabs and the page shell below — same queryKey means
  // React Query dedupes this to a single request regardless of how many
  // components ask for it.
  return useQuery({
    queryKey: ['debug-llm-provider'],
    queryFn: async () => {
      const { data } = await api.GET('/debug/llm-provider')
      return data
    },
  })
}

export default function ModelsPage() {
  const providerQuery = useActiveProviderQuery()
  const [tab, setTab] = useState<Tab | null>(null)

  // Default to whichever engine is actually loaded once we know — but only
  // the first time data arrives, so a manual tab click afterward (e.g. to
  // browse the other catalog) is never clobbered by a background refetch.
  useEffect(() => {
    if (tab === null && providerQuery.data) {
      setTab(providerQuery.data.provider === 'lmstudio' ? 'lmstudio' : 'openrouter')
    }
  }, [providerQuery.data, tab])

  const activeTab = tab ?? 'openrouter'

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-4 border-b border-border">
        <TabButton
          label="OpenRouter"
          isLoaded={providerQuery.data?.provider === 'openrouter'}
          active={activeTab === 'openrouter'}
          onClick={() => setTab('openrouter')}
        />
        <TabButton
          label="LM Studio"
          isLoaded={providerQuery.data?.provider === 'lmstudio'}
          active={activeTab === 'lmstudio'}
          onClick={() => setTab('lmstudio')}
        />
      </div>
      {activeTab === 'openrouter' ? <OpenRouterModelsSection /> : <LmStudioModelsSection />}
    </div>
  )
}

function TabButton({
  label,
  isLoaded,
  active,
  onClick,
}: {
  label: string
  isLoaded: boolean
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 px-1 pb-2 text-sm font-medium ${
        active ? 'border-b-2 border-accent text-accent' : 'text-text-muted hover:text-accent'
      }`}
    >
      {label}
      {isLoaded && (
        <span
          title="Currently the active provider"
          className="h-1.5 w-1.5 rounded-full bg-accent"
        />
      )}
    </button>
  )
}

function OpenRouterModelsSection() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [freeOnly, setFreeOnly] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDesc, setSortDesc] = useState(false)

  const modelsQuery = useQuery({
    queryKey: ['openrouter-models'],
    queryFn: async () => {
      const { data } = await api.GET('/debug/openrouter-models')
      return data
    },
  })

  // Only fetched to name the active provider in the read-only banner below
  // — not needed at all once settings.llm_provider is openrouter, since the
  // catalog response above already says so directly (`active`). Same
  // queryKey the page shell's tab bar uses, so this doesn't add a request.
  const providerQuery = useActiveProviderQuery()

  const switchMutation = useMutation({
    mutationFn: async (modelId: string) => {
      const { error } = await api.POST('/settings', { body: { openrouter_chat_model: modelId } })
      if (error) throw new Error('Failed to switch model')
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['openrouter-models'] }),
  })

  const models = modelsQuery.data?.models ?? []
  const active = modelsQuery.data?.active ?? false
  const configuredModel = modelsQuery.data?.configured_model ?? null

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    let list = models.filter(
      (m) =>
        (!freeOnly || m.is_free) &&
        (!needle || m.id.toLowerCase().includes(needle) || m.name.toLowerCase().includes(needle)),
    )
    list = [...list].sort((a, b) => {
      let cmp: number
      if (sortKey === 'name') {
        cmp = a.name.localeCompare(b.name)
      } else {
        const av = a[sortKey] ?? -Infinity
        const bv = b[sortKey] ?? -Infinity
        cmp = av - bv
      }
      return sortDesc ? -cmp : cmp
    })
    return list
  }, [models, search, freeOnly, sortKey, sortDesc])

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDesc((d) => !d)
    } else {
      setSortKey(key)
      setSortDesc(key !== 'name')
    }
  }

  const sortIndicator = (key: SortKey) => (sortKey === key ? (sortDesc ? ' ↓' : ' ↑') : '')

  return (
    <>
      <Card>
        <h2 className="mb-1 text-lg font-semibold">OpenRouter Models</h2>
        <p className="mb-3 text-sm text-text-muted">
          Live catalog from OpenRouter's public <code>/models</code> endpoint — name, context
          length, and per-token pricing for every model it serves. Mainly useful for finding
          current free-tier (<code>:free</code>) models.
        </p>
        {active ? (
          <p className="mb-3 text-sm text-accent">
            OpenRouter is the active provider — click a model below to switch immediately, no
            restart needed.
            {configuredModel && <> Currently: {configuredModel}</>}
          </p>
        ) : (
          <p className="mb-3 text-sm text-text-muted">
            Read-only — the active provider is currently{' '}
            <span className="text-text-primary">{providerQuery.data?.provider ?? '…'}</span>, not
            openrouter, so switching is disabled here. Switch to it from the{' '}
            <Link to="/settings" className="text-accent hover:underline">
              Settings page's LLM Provider card
            </Link>{' '}
            (immediate, no restart), then pick a model straight from this page afterward.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or id..."
            className="min-w-0 flex-1 rounded border border-border bg-card-alt px-2 py-1 text-sm text-text-primary"
          />
          <label className="flex items-center gap-2 text-sm text-text-muted">
            <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
            Free only
          </label>
          <button
            type="button"
            onClick={() => modelsQuery.refetch()}
            className="rounded-lg border border-border bg-card-alt px-3 py-2 text-sm hover:border-accent"
          >
            Refresh
          </button>
        </div>
      </Card>

      <Card className="p-0">
        {modelsQuery.isPending ? (
          <p className="p-6 text-sm text-text-muted">Loading...</p>
        ) : modelsQuery.isError ? (
          <p className="p-6 text-sm text-text-muted">
            Failed to reach OpenRouter's catalog — check server logs.
          </p>
        ) : filtered.length === 0 ? (
          <p className="p-6 text-sm text-text-muted">No models match.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-text-muted">
                  <th
                    className="cursor-pointer select-none px-4 py-2 font-medium"
                    onClick={() => toggleSort('name')}
                  >
                    Model{sortIndicator('name')}
                  </th>
                  <th
                    className="cursor-pointer select-none px-4 py-2 font-medium"
                    onClick={() => toggleSort('context_length')}
                  >
                    Context{sortIndicator('context_length')}
                  </th>
                  <th
                    className="cursor-pointer select-none px-4 py-2 font-medium"
                    onClick={() => toggleSort('prompt_price_per_million')}
                  >
                    $/M tokens (prompt / completion){sortIndicator('prompt_price_per_million')}
                  </th>
                  {active && <th className="px-4 py-2 font-medium" />}
                </tr>
              </thead>
              <tbody>
                {filtered.map((model) => {
                  const isActiveModel = model.id === configuredModel
                  return (
                    <tr
                      key={model.id}
                      className={`border-b border-border last:border-0 ${isActiveModel ? 'bg-card-alt' : ''}`}
                    >
                      <td className="px-4 py-2">
                        <div className="text-text-primary">{model.name}</div>
                        <div className="text-xs text-text-muted">{model.id}</div>
                      </td>
                      <td className="px-4 py-2 text-text-muted">{formatContext(model.context_length)}</td>
                      <td className={`px-4 py-2 ${model.is_free ? 'text-accent' : 'text-text-muted'}`}>
                        {formatPrice(model)}
                      </td>
                      {active && (
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
    </>
  )
}

function LmStudioModelsSection() {
  const queryClient = useQueryClient()
  const [manualModel, setManualModel] = useState('')

  const modelsQuery = useQuery({
    queryKey: ['lmstudio-models'],
    queryFn: async () => {
      const { data } = await api.GET('/debug/lmstudio-models')
      return data
    },
  })

  // Only fetched to name the active provider in the read-only banner below
  // — not needed at all once settings.llm_provider is lmstudio, since the
  // catalog response above already says so directly (`active`). Same
  // queryKey the page shell's tab bar uses, so this doesn't add a request.
  const providerQuery = useActiveProviderQuery()

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
  const active = modelsQuery.data?.active ?? false
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
        {active ? (
          <p className="mb-3 text-sm text-accent">
            LM Studio is the active provider
            {managementConfigured
              ? ' — click a model below to switch immediately, no restart needed.'
              : '.'}
            {configuredModel && <> Currently: {configuredModel}</>}
          </p>
        ) : (
          <p className="mb-3 text-sm text-text-muted">
            Read-only — the active provider is currently{' '}
            <span className="text-text-primary">{providerQuery.data?.provider ?? '…'}</span>, not
            lmstudio, so switching is disabled here. Switch to it from the{' '}
            <Link to="/settings" className="text-accent hover:underline">
              Settings page's LLM Provider card
            </Link>{' '}
            (immediate, no restart), then pick a model here afterward.
          </p>
        )}
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
                    {active && <th className="px-4 py-2 font-medium" />}
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
                        {active && (
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
