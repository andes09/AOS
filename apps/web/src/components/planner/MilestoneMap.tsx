import { CSSProperties, Fragment } from 'react'
import type { RoadmapMilestone } from '../../types/roadmap'

interface MilestoneMapProps {
  milestones: RoadmapMilestone[]
}

/**
 * "The plan" — a horizontal row of milestone progress rings connected by a
 * line, start to finish. Purely presentational: each ring's fill is that
 * milestone's done/total task ratio. Dark-theme friendly (accent ring on the
 * tertiary track), scrolls horizontally when a plan has many phases.
 */
export function MilestoneMap({ milestones }: MilestoneMapProps) {
  const ordered = [...milestones].sort((a, b) => a.sortOrder - b.sortOrder)

  if (ordered.length === 0) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: 0 }}>
        No milestones yet — generate a plan to see the roadmap here.
      </p>
    )
  }

  const totalTasks = ordered.reduce((n, m) => n + m.tasks.length, 0)
  const doneTasks = ordered.reduce((n, m) => n + m.tasks.filter(t => t.status === 'done').length, 0)

  return (
    <div>
      <p style={{ marginTop: 0, marginBottom: 'var(--space-4)', fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
        Start to finish, {ordered.length} milestone{ordered.length === 1 ? '' : 's'} · {doneTasks} of {totalTasks} tasks done.
      </p>

      <div style={{ display: 'flex', alignItems: 'flex-start', overflowX: 'auto', paddingBottom: 'var(--space-2)' }}>
        {ordered.map((m, i) => {
          const total = m.tasks.length
          const done = m.tasks.filter(t => t.status === 'done').length
          const pct = total > 0 ? Math.round((done / total) * 100) : 0
          return (
            <Fragment key={m.id}>
              {i > 0 && <div style={connectorStyle} />}
              <div style={nodeStyle}>
                <Ring pct={pct} />
                <div style={{ marginTop: 10, fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--color-text-primary)', lineHeight: 1.3 }}>
                  {m.title}
                </div>
                <div style={{ marginTop: 2, fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                  {done} of {total} task{total === 1 ? '' : 's'}
                </div>
              </div>
            </Fragment>
          )
        })}
      </div>
    </div>
  )
}

const RING_SIZE = 72
const STROKE = 6
const RADIUS = (RING_SIZE - STROKE) / 2
const CIRC = 2 * Math.PI * RADIUS

function Ring({ pct }: { pct: number }) {
  const complete = pct >= 100
  const color = complete ? 'var(--color-success)' : 'var(--color-accent)'
  const offset = CIRC * (1 - pct / 100)
  return (
    <div style={{ position: 'relative', width: RING_SIZE, height: RING_SIZE }}>
      <svg width={RING_SIZE} height={RING_SIZE} style={{ transform: 'rotate(-90deg)' }}>
        <circle
          cx={RING_SIZE / 2}
          cy={RING_SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="var(--color-bg-tertiary)"
          strokeWidth={STROKE}
        />
        <circle
          cx={RING_SIZE / 2}
          cy={RING_SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke={color}
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeDasharray={CIRC}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.3s ease' }}
        />
      </svg>
      <span
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 'var(--text-sm)',
          fontWeight: 700,
          color: 'var(--color-text-primary)',
        }}
      >
        {pct}%
      </span>
    </div>
  )
}

const nodeStyle: CSSProperties = {
  flexShrink: 0,
  width: 132,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  textAlign: 'center',
  padding: '0 var(--space-2)',
}

const connectorStyle: CSSProperties = {
  flexShrink: 0,
  minWidth: 24,
  flex: 1,
  height: 2,
  background: 'var(--color-border)',
  // Line up with the vertical center of the rings above the labels.
  marginTop: RING_SIZE / 2 - 1,
}
