import { CSSProperties, useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Avatar } from '../ui/Avatar'
import { laneVars } from '../../lib/laneColors'
import type { RoadmapMember, RoadmapTaskStatus } from '../../types/roadmap'
import type { FlatTask } from '../../pages/planner/usePlannerData'
import type { TaskPatch } from '../../pages/planner/usePlannerMutations'

const DURATION_PRESETS = [15, 30, 45, 60, 90, 120, 240]

const STATUSES: { value: RoadmapTaskStatus; label: string }[] = [
  { value: 'todo', label: 'To do' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'done', label: 'Done' },
]

interface TaskDetailModalProps {
  task: FlatTask | null
  members: RoadmapMember[]
  onClose: () => void
  onSave: (patch: TaskPatch) => void
  onDelete: () => void
}

/**
 * Edit everything about a task in one place, saved as a single PATCH.
 *
 * Local draft state rather than live-patching per keystroke: the planner's
 * optimistic updates rewrite the whole roadmap object, so a per-keystroke save
 * would fight the user's cursor.
 */
export function TaskDetailModal({ task, members, onClose, onSave, onDelete }: TaskDetailModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<RoadmapTaskStatus>('todo')
  const [assigneeId, setAssigneeId] = useState<string | null>(null)
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const [duration, setDuration] = useState<number | null>(null)

  useEffect(() => {
    if (!task) return
    setTitle(task.title)
    setDescription(task.description ?? '')
    setStatus(task.status)
    setAssigneeId(task.assigneeId)
    setDate(task.scheduledDate ?? '')
    setTime(task.scheduledTime ?? '')
    setDuration(task.durationMinutes)
  }, [task])

  if (!task) return null

  const save = () => {
    const trimmed = title.trim()
    if (!trimmed) return
    onSave({
      title: trimmed,
      description: description.trim() || null,
      status,
      assigneeId,
      // Empty inputs mean "clear" — null is meaningful here, not a no-op.
      scheduledDate: date || null,
      scheduledTime: time || null,
      durationMinutes: duration,
    })
    onClose()
  }

  return (
    <Modal open onClose={onClose} title="Task details" width={560}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        <Field label="Title">
          <Input value={title} onChange={e => setTitle(e.target.value)} autoFocus />
        </Field>

        <Field label="Description">
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={4}
            style={{
              width: '100%',
              resize: 'vertical',
              padding: '6px 8px',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg-primary)',
              color: 'var(--color-text-primary)',
              fontFamily: 'var(--font-sans)',
              fontSize: 'var(--text-sm)',
              lineHeight: 1.5,
            }}
          />
        </Field>

        <Field label="Assignee">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <AssigneeChip
              name="Unassigned"
              colorIndex={null}
              selected={assigneeId === null}
              onClick={() => setAssigneeId(null)}
            />
            {members.map(m => (
              <AssigneeChip
                key={m.id}
                name={m.name}
                colorIndex={m.colorIndex}
                avatarUrl={m.avatarUrl}
                initials={m.initials}
                selected={assigneeId === m.id}
                onClick={() => setAssigneeId(m.id)}
              />
            ))}
          </div>
        </Field>

        <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <Field label="Date" style={{ flex: '1 1 150px' }}>
            <Input type="date" value={date} onChange={e => setDate(e.target.value)} />
          </Field>
          <Field label="Start time" style={{ flex: '1 1 120px' }}>
            <Input type="time" value={time} onChange={e => setTime(e.target.value)} />
          </Field>
        </div>

        <Field label="Duration">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <Chip selected={duration === null} onClick={() => setDuration(null)}>
              None
            </Chip>
            {DURATION_PRESETS.map(d => (
              <Chip key={d} selected={duration === d} onClick={() => setDuration(d)}>
                {d < 60 ? `${d}m` : d % 60 === 0 ? `${d / 60}h` : `${Math.floor(d / 60)}h ${d % 60}m`}
              </Chip>
            ))}
          </div>
        </Field>

        <Field label="Status">
          <div style={{ display: 'flex', gap: 6 }}>
            {STATUSES.map(s => (
              <Chip key={s.value} selected={status === s.value} onClick={() => setStatus(s.value)}>
                {s.label}
              </Chip>
            ))}
          </div>
        </Field>

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: 'var(--space-2)',
            paddingTop: 'var(--space-2)',
            borderTop: '1px solid var(--color-border-subtle)',
          }}
        >
          <Button
            variant="danger"
            onClick={() => {
              onDelete()
              onClose()
            }}
          >
            <Trash2 size={14} /> Delete
          </Button>
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" onClick={save} disabled={!title.trim()}>
              Save
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  )
}

function Field({
  label,
  children,
  style,
}: {
  label: string
  children: React.ReactNode
  style?: CSSProperties
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 5, ...style }}>
      <span
        style={{
          fontSize: 'var(--text-xs)',
          fontWeight: 600,
          color: 'var(--color-text-secondary)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}
      >
        {label}
      </span>
      {children}
    </label>
  )
}

function Chip({
  selected,
  onClick,
  children,
}: {
  selected: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      style={{
        padding: '4px 10px',
        borderRadius: 999,
        cursor: 'pointer',
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--text-xs)',
        border: `1px solid ${selected ? 'var(--color-accent)' : 'var(--color-border)'}`,
        background: selected ? 'var(--color-accent-subtle)' : 'var(--color-bg-primary)',
        color: selected ? 'var(--color-accent)' : 'var(--color-text-secondary)',
      }}
    >
      {children}
    </button>
  )
}

/** Assignee option rendered in that person's own lane color. */
function AssigneeChip({
  name,
  colorIndex,
  avatarUrl,
  initials,
  selected,
  onClick,
}: {
  name: string
  colorIndex: number | null
  avatarUrl?: string | null
  initials?: string | null
  selected: boolean
  onClick: () => void
}) {
  const lane = laneVars(colorIndex)
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 10px 3px 3px',
        borderRadius: 999,
        cursor: 'pointer',
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--text-xs)',
        border: `1px solid ${selected ? lane.solid : 'var(--color-border)'}`,
        background: selected ? lane.bg : 'var(--color-bg-primary)',
        color: selected ? lane.text : 'var(--color-text-secondary)',
      }}
    >
      <Avatar name={name} colorIndex={colorIndex} avatarUrl={avatarUrl} initials={initials} size="xs" />
      {name}
    </button>
  )
}
