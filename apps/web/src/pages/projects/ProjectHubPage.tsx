// The Project Hub — the new /app index route. Lists every project the org
// has, grouped Active / Finished / Archived, with an entry point to create
// another one (see docs/plans/2026-07-20-project-hub.md).

import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { Alert } from '../../components/ui/Alert'
import { EmptyState } from '../../components/ui/EmptyState'
import { useProjects, useProjectMutations } from '../../features/projects/hooks/useProjects'
import type { ProjectStatus, ProjectSummary } from '../../features/projects/types'
import { ProjectCard } from './ProjectCard'
import { ApiError } from '../../lib/api'

const SECTIONS: { status: ProjectStatus; title: string }[] = [
  { status: 'active', title: 'Active' },
  { status: 'finished', title: 'Finished' },
  { status: 'archived', title: 'Archived' },
]

export function ProjectHubPage() {
  const navigate = useNavigate()
  const { data: projects, isLoading, error } = useProjects()
  const { setStatus } = useProjectMutations()

  if (isLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4rem 0', justifyContent: 'center' }}>
        <Spinner /> Loading your projects…
      </div>
    )
  }

  const byStatus = new Map<ProjectStatus, ProjectSummary[]>()
  for (const p of projects ?? []) {
    const list = byStatus.get(p.status) ?? []
    list.push(p)
    byStatus.set(p.status, list)
  }

  const isEmpty = (projects?.length ?? 0) === 0

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700, margin: 0 }}>Projects</h1>
        <Button variant="primary" onClick={() => navigate('/app/projects/new')}>
          <Plus size={16} /> New Project
        </Button>
      </div>

      {error && (
        <Alert variant="danger">
          {error instanceof ApiError
            ? error.message === 'project_limit_reached'
              ? "You've reached your organization's project limit."
              : error.message
            : 'Could not load your projects.'}
        </Alert>
      )}

      {isEmpty ? (
        <EmptyState
          title="No projects yet"
          description="Create your first project to get a day-by-day plan for your team."
          action={{ label: 'New Project', onClick: () => navigate('/app/projects/new') }}
        />
      ) : (
        SECTIONS.map(({ status, title }) => {
          const list = byStatus.get(status) ?? []
          if (list.length === 0) return null
          return (
            <section key={status} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              <h2
                style={{
                  fontSize: 'var(--text-sm)',
                  fontWeight: 600,
                  color: 'var(--color-text-secondary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  margin: 0,
                }}
              >
                {title} ({list.length})
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 'var(--space-3)' }}>
                {list.map(project => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    isUpdating={setStatus.isPending && setStatus.variables?.id === project.id}
                    onSetStatus={newStatus => setStatus.mutate({ id: project.id, status: newStatus })}
                  />
                ))}
              </div>
            </section>
          )
        })
      )}
    </div>
  )
}
