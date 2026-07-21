import { CSSProperties, useEffect, useRef, useState } from 'react'
import { Sparkles, Trash2 } from 'lucide-react'
import { Avatar } from '../ui/Avatar'
import { IconButton } from '../ui/IconButton'
import { laneVars } from '../../lib/laneColors'
import { endTimeOf, formatDuration, formatTime12h, MONTHS, parseISO, WEEKDAY_LABELS } from '../../lib/date'
import type { RoadmapMember, RoadmapTaskStatus } from '../../types/roadmap'
import type { FlatTask } from '../../pages/planner/usePlannerData'

const STATUSES: { value: RoadmapTaskStatus; label: string }[] = [
  { value: 'todo', label: 'To do' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'done', label: 'Done' },
]

interface DayAgendaProps {
  iso: string
  tasks: FlatTask[]
  membersById: Map<string, RoadmapMember>
  colorOf: (task: FlatTask) => number | null
  onStatus: (task: FlatTask, status: RoadmapTaskStatus) => void
  onFeedback: (task: FlatTask, feedback: string) => void
  onDelete: (task: FlatTask) => void
  onOpen: (task: FlatTask) => void
  onAdjust: () => void
  isAdjusting: boolean
  adjustError: string | null
}

/**
 * A single day as its own page: a vertical, chronological agenda. Each task
 * shows its time, full description, a 3-state status, and a feedback box the
 * user fills in as they go. "Update my plan" sends that feedback to Groq, which
 * re-plans upcoming tasks while leaving completed work alone.
 */
export function DayAgenda({
  iso,
  tasks,
  membersById,
  colorOf,
  onStatus,
  onFeedback,
  onDelete,
  onOpen,
  onAdjust,
  isAdjusting,
  adjustError,
}: DayAgendaProps) {
  const d = parseISO(iso)
  const heading = `${WEEKDAY_LABELS[(d.getDay() + 6) % 7]}, ${MONTHS[d.getMonth()]} ${d.getDate()}`

  return (
    <div style={{ maxWidth: 720 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
        <h2 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          {heading}
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
          <button onClick={onAdjust} disabled={isAdjusting} style={adjustBtnStyle}>
            <Sparkles size={14} />
            {isAdjusting ? 'Updating your plan…' : 'Update my plan from feedback'}
          </button>
          <span style={{ fontSize: 10, color: adjustError ? 'var(--color-danger)' : 'var(--color-text-muted)' }}>
            {adjustError ?? 'Re-plans upcoming tasks; completed work is kept.'}
          </span>
        </div>
      </div>

      {tasks.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', lineHeight: 1.5 }}>
          Nothing scheduled for this day. Use the arrows to check another day, or update your plan
          from feedback to re-balance the week.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {tasks.map(task => (
            <AgendaRow
              key={task.id}
              task={task}
              colorIndex={colorOf(task)}
              member={task.assigneeId ? membersById.get(task.assigneeId) ?? null : null}
              onStatus={s => onStatus(task, s)}
              onFeedback={fb => onFeedback(task, fb)}
              onDelete={() => onDelete(task)}
              onOpen={() => onOpen(task)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function AgendaRow({
  task,
  colorIndex,
  member,
  onStatus,
  onFeedback,
  onDelete,
  onOpen,
}: {
  task: FlatTask
  colorIndex: number | null
  member: RoadmapMember | null
  onStatus: (s: RoadmapTaskStatus) => void
  onFeedback: (fb: string) => void
  onDelete: () => void
  onOpen: () => void
}) {
  const lane = laneVars(colorIndex)
  const done = task.status === 'done'
  const start = formatTime12h(task.scheduledTime)
  const end = endTimeOf(task.scheduledTime, task.durationMinutes)
  const timeLabel = start ? (end ? `${start} – ${formatTime12h(end)}` : start) : 'Anytime'

  // Local draft so typing is smooth; persist on blur only when it changed.
  const [draft, setDraft] = useState(task.feedback ?? '')
  const lastSaved = useRef(task.feedback ?? '')
  // Keep in sync if the task's feedback changes underneath us (e.g. a re-plan).
  useEffect(() => {
    setDraft(task.feedback ?? '')
    lastSaved.current = task.feedback ?? ''
  }, [task.id, task.feedback])

  const saveFeedback = () => {
    if (draft !== lastSaved.current) {
      lastSaved.current = draft
      onFeedback(draft)
    }
  }

  return (
    <div
      className="pl-task-card"
      style={{
        display: 'flex',
        gap: 'var(--space-3)',
        padding: 'var(--space-3)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--color-border-subtle)',
        borderLeft: `3px solid ${lane.solid}`,
        background: done ? 'var(--color-bg-secondary)' : 'var(--color-bg-elevated)',
        opacity: done ? 0.72 : 1,
      }}
    >
      {/* Time rail */}
      <div style={{ width: 92, flexShrink: 0, textAlign: 'right', paddingTop: 2 }}>
        <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: lane.text }}>{start || '—'}</div>
        {end && <div style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>{formatTime12h(end)}</div>}
        {task.durationMinutes ? (
          <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>{formatDuration(task.durationMinutes)}</div>
        ) : (
          <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>{start ? '' : timeLabel}</div>
        )}
      </div>

      {/* Body */}
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 'var(--space-2)' }}>
          <button onClick={onOpen} style={titleBtnStyle}>
            <span style={{ textDecoration: done ? 'line-through' : 'none', fontWeight: 600, fontSize: 'var(--text-base)', color: 'var(--color-text-primary)' }}>
              {task.title}
            </span>
          </button>
          <div className="pl-task-actions" style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            {member && <Avatar name={member.name} colorIndex={member.colorIndex} avatarUrl={member.avatarUrl} initials={member.initials} size="xs" />}
            <IconButton label="Delete task" size={18} onClick={onDelete}>
              <Trash2 size={12} />
            </IconButton>
          </div>
        </div>

        {task.description && (
          <p style={{ margin: '4px 0 0', fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
            {task.description}
          </p>
        )}
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {task.milestoneTitle}
        </div>

        {/* Status */}
        <div role="radiogroup" aria-label="Status" style={{ display: 'flex', gap: 6, marginTop: 'var(--space-2)' }}>
          {STATUSES.map(s => {
            const active = task.status === s.value
            return (
              <button
                key={s.value}
                role="radio"
                aria-checked={active}
                onClick={() => onStatus(s.value)}
                style={{
                  padding: '3px 9px',
                  borderRadius: 999,
                  cursor: 'pointer',
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--text-xs)',
                  border: `1px solid ${active ? (s.value === 'done' ? 'var(--color-success)' : 'var(--color-accent)') : 'var(--color-border)'}`,
                  background: active ? (s.value === 'done' ? 'var(--color-success-bg)' : 'var(--color-accent-subtle)') : 'var(--color-bg-primary)',
                  color: active ? (s.value === 'done' ? 'var(--color-success)' : 'var(--color-accent)') : 'var(--color-text-secondary)',
                }}
              >
                {s.label}
              </button>
            )
          })}
        </div>

        {/* Feedback box */}
        <textarea
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={saveFeedback}
          placeholder="How did this go? Note blockers, what changed, how long it took…"
          rows={2}
          style={feedbackStyle}
        />
      </div>
    </div>
  )
}

const adjustBtnStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '6px 12px',
  borderRadius: 'var(--radius-md)',
  cursor: 'pointer',
  border: '1px solid var(--color-accent)',
  background: 'var(--color-accent-subtle)',
  color: 'var(--color-accent)',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  fontWeight: 'var(--font-weight-medium)' as CSSProperties['fontWeight'],
  whiteSpace: 'nowrap',
}

const titleBtnStyle: CSSProperties = {
  padding: 0,
  border: 'none',
  background: 'transparent',
  cursor: 'pointer',
  textAlign: 'left',
  minWidth: 0,
}

const feedbackStyle: CSSProperties = {
  width: '100%',
  marginTop: 'var(--space-2)',
  resize: 'vertical',
  padding: '7px 9px',
  borderRadius: 'var(--radius-md)',
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg-primary)',
  color: 'var(--color-text-primary)',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  lineHeight: 1.45,
}
