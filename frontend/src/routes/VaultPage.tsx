import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import Card from '../components/Card'

function formatDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export default function VaultPage() {
  const [search, setSearch] = useState('')
  const [projectFilter, setProjectFilter] = useState('')
  const [openNoteId, setOpenNoteId] = useState<string | null>(null)

  const notesQuery = useQuery({
    queryKey: ['vault', 'notes'],
    queryFn: async () => {
      const { data } = await api.GET('/vault/notes')
      return data?.notes ?? []
    },
  })

  const noteQuery = useQuery({
    queryKey: ['vault', 'notes', openNoteId],
    queryFn: async () => {
      const { data } = await api.GET('/vault/notes/{note_id}', {
        params: { path: { note_id: openNoteId! } },
      })
      return data
    },
    enabled: !!openNoteId,
  })

  const notes = notesQuery.data ?? []

  const projects = useMemo(
    () => [...new Set(notes.map((n) => n.project).filter((p): p is string => !!p))].sort(),
    [notes],
  )

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    return notes.filter((note) => {
      if (projectFilter && note.project !== projectFilter) return false
      if (!query) return true
      const haystack = `${note.title} ${note.tags.join(' ')} ${note.excerpt}`.toLowerCase()
      return haystack.includes(query)
    })
  }, [notes, search, projectFilter])

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Vault</h2>
        <p className="mb-4 text-sm text-text-muted">
          Read-only browse of the notes vault — everything the assistant has accumulated, without
          opening Obsidian. Inbox items aren't shown here; they're unprocessed until reconciled
          into a real note.
        </p>
        <div className="mb-3 flex flex-col gap-1">
          <label htmlFor="searchInput" className="text-sm text-text-muted">
            Search
          </label>
          <input
            id="searchInput"
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Title, tag, or excerpt..."
            className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
          />
        </div>
        <select
          value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
          className="rounded border border-border bg-card-alt px-3 py-2 text-sm text-text-primary"
        >
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </Card>

      {openNoteId && (
        <Card>
          <button
            type="button"
            onClick={() => setOpenNoteId(null)}
            className="float-right rounded border border-border bg-card-alt px-3 py-1.5 text-sm hover:border-accent"
          >
            Close
          </button>
          {!noteQuery.data ? (
            <p>Loading...</p>
          ) : (
            <>
              <h2 className="mb-1 text-lg font-semibold">{noteQuery.data.title}</h2>
              <p className="mb-3 text-sm text-text-muted">
                {[
                  noteQuery.data.project ? `project: ${noteQuery.data.project}` : null,
                  noteQuery.data.tags.length > 0 ? `tags: ${noteQuery.data.tags.join(', ')}` : null,
                  `created ${formatDate(noteQuery.data.created)}`,
                  `updated ${formatDate(noteQuery.data.updated)}`,
                ]
                  .filter(Boolean)
                  .join('  ·  ')}
              </p>
              <pre className="whitespace-pre-wrap break-words rounded-lg border border-[#2a2a2a] bg-header p-3 text-sm">
                {noteQuery.data.body}
              </pre>
            </>
          )}
        </Card>
      )}

      {filtered.length === 0 ? (
        <p className="text-sm text-text-muted">
          {notesQuery.isPending ? 'Loading...' : 'No notes match.'}
        </p>
      ) : (
        filtered.map((note) => (
          <Card
            key={note.id}
            className="cursor-pointer"
            onClick={() => setOpenNoteId(note.id)}
          >
            <h2 className="mb-1 text-lg font-semibold">{note.title}</h2>
            <p className="mb-2 text-xs text-text-muted">
              {[
                note.project ? `project: ${note.project}` : null,
                note.tags.length > 0 ? `tags: ${note.tags.join(', ')}` : null,
                `updated ${formatDate(note.updated)}`,
              ]
                .filter(Boolean)
                .join('  ·  ')}
            </p>
            {note.excerpt && <p className="text-sm text-text-muted">{note.excerpt}</p>}
          </Card>
        ))
      )}
    </div>
  )
}
