import { useNavigate } from 'react-router-dom'
import { Card, CardBody } from '../../components/ui/Card'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import type { ProjectStatus, ProjectSummary } from '../../features/projects/types'

/** Every legal next status for a project, keyed by its current one — keeps
 * the card from ever offering a transition the backend would reject
 * (see docs/plans/2026-07-20-project-hub.md's status-transition rules). */
const NEXT_ACTIONS: Record<ProjectStatus, { label: string; status: ProjectStatus }[]> = {
  active: [
    { label: 'Mark finished', status: 'finished' },
    { label: 'Archive', status: 'archived' },
  ],
  finished: [
    { label: 'Reopen', status: 'active' },
    { label: 'Archive', status: 'archived' },
  ],
  archived: [{ label: 'Restore', status: 'active' }],
}

export function ProjectCard({
  project,
  onSetStatus,
  isUpdating,
}: {
  project: ProjectSummary
  onSetStatus: (status: ProjectStatus) => void
  isUpdating: boolean
}) {
  const navigate = useNavigate()

  return (
    <Card style={{ cursor: 'pointer' }} onClick={() => navigate(`/app/projects/${project.id}`)}>
      <CardBody style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 'var(--text-base)' }}>{project.name}</span>
          {!project.hasRoadmap && <Badge variant="info">Draft</Badge>}
        </div>
        {project.summary && (
          <p
            style={{
              margin: 0,
              color: 'var(--color-text-secondary)',
              fontSize: 'var(--text-sm)',
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {project.summary}
          </p>
        )}
        <div
          style={{ display: 'flex', gap: 8, marginTop: 4 }}
          onClick={e => e.stopPropagation()}
        >
          {NEXT_ACTIONS[project.status].map(action => (
            <Button
              key={action.status}
              variant="ghost"
              size="sm"
              disabled={isUpdating}
              onClick={() => onSetStatus(action.status)}
            >
              {action.label}
            </Button>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}
