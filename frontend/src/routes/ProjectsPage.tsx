import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import Card from '../components/Card'

interface ProjectSummary {
  name: string
  noteCount: number
  updated: string
}

export default function ProjectsPage() {
  const navigate = useNavigate()

  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: async () => {
      const { data } = await api.GET('/projects')
      return data?.projects ?? []
    },
  })

  const notesQuery = useQuery({
    queryKey: ['vault', 'notes'],
    queryFn: async () => {
      const { data } = await api.GET('/vault/notes')
      return data?.notes ?? []
    },
  })

  const projects: ProjectSummary[] = useMemo(() => {
    const names = projectsQuery.data ?? []
    const notes = notesQuery.data ?? []
    return names
      .map((name) => {
        const projectNotes = notes.filter((n) => n.project === name)
        const updated = projectNotes.reduce(
          (latest, n) => (n.updated > latest ? n.updated : latest),
          '',
        )
        return { name, noteCount: projectNotes.length, updated }
      })
      .sort((a, b) => b.updated.localeCompare(a.updated))
  }, [projectsQuery.data, notesQuery.data])

  const isPending = projectsQuery.isPending || notesQuery.isPending

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Projects</h2>
        <p className="text-sm text-text-muted">
          Notes, images, and a scoped chat for each ongoing project. General notes still live in
          Vault — this view is just for the project-folder notes.
        </p>
      </Card>

      {isPending ? (
        <p className="text-sm text-text-muted">Loading...</p>
      ) : projects.length === 0 ? (
        <p className="text-sm text-text-muted">
          No projects yet — ask the assistant to start one, or create a folder in the vault.
        </p>
      ) : (
        projects.map((project) => (
          <Card
            key={project.name}
            className="cursor-pointer"
            onClick={() => navigate(`/projects/${encodeURIComponent(project.name)}`)}
          >
            <h2 className="mb-1 text-lg font-semibold">{project.name}</h2>
            <p className="text-sm text-text-muted">
              {project.noteCount} note{project.noteCount === 1 ? '' : 's'}
            </p>
          </Card>
        ))
      )}
    </div>
  )
}
