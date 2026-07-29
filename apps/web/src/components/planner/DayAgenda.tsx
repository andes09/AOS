import { CSSProperties, useEffect, useRef, useState } from 'react'
import { Check, Map, Sparkles, Trash2 } from 'lucide-react'
import { Avatar } from '../ui/Avatar'
import { IconButton } from '../ui/IconButton'
import { laneVars } from '../../lib/laneColors'
import { MONTHS, parseISO, WEEKDAY_LABELS } from '../../lib/date'
import type { RoadmapMember } from '../../types/roadmap'
import type { FlatTask } from '../../pages/planner/usePlannerData'

interface DayAgendaProps {
  iso: string
  /** Chronologically sorted (untimed first); order is preserved, times hidden. */
  tasks: FlatTask[]
  membersById: Map<string, RoadmapMember>
  colorOf: (task: FlatTask) => number | null
  /** Plan-wide progress, for the "Up next" subtitle. */
  done: number
  total: number
  currentMilestoneTitle: string | null
  onToggleDone: (task: FlatTask) => void
  onFeedback: (task: FlatTask, feedback: string) => void
  onDelete: (task: FlatTask) => void
  onOpen: (task: FlatTask) => void
  /** Feedback auto-updates the plan; these just surface that background work. */
  isAdjusting: boolean
  adjustError: string | null
  onExtendDay: () => void
  isExtending: boolean
  extendError: string | null
  onOpenPlanMap: () => void
}

/** How many upcoming tasks to surface at once; the rest reveal as these are
 *  checked off, keeping the focus on what's immediately next. */
const VISIBLE_COUNT = 3

/** A task's derived state within the day, computed from `parallel` + order. */
interface Row {
  task: FlatTask
  /** A non-parallel task blocked by an earlier unfinished non-parallel task. */
  waiting: boolean
  /** Card opacity — waiting tasks fade progressively so the eye lands on the
   *  work that's actually actionable now. */
  opacity: number
}

/**
 * The day as an "Up next" list: clean, tappable task cards in chronological
 * order, with no timestamps. Only unfinished work is shown — checking a task
 * off (or topping the day up with the AI) clears it from the queue. A task that
 * still "waits its turn" (a sequential task gated by earlier unfinished work)
 * renders faded. Feedback boxes stay, and writing feedback auto-updates the
 * plan in the background; when the whole day is cleared, the AI can top it up.
 */
export function DayAgenda({
  iso,
  tasks,
  membersById,
  colorOf,
  done,
  total,
  currentMilestoneTitle,
  onToggleDone,
  onFeedback,
  onDelete,
  onOpen,
  isAdjusting,
  adjustError,
  onExtendDay,
  isExtending,
  extendError,
  onOpenPlanMap,
}: DayAgendaProps) {
  const d = parseISO(iso)
  const dateLabel = `${WEEKDAY_LABELS[(d.getDay() + 6) % 7]}, ${MONTHS[d.getMonth()]} ${d.getDate()}`

  // "Up next" is a queue of what's left: completed tasks drop out (so a fresh
  // top-up shows only the new work, and checking a task off clears it).
  const upNext = tasks.filter(t => t.status !== 'done')

  // Every card fades a little more than the one above it, so the eye lands on
  // the most immediate task and later work recedes down the queue. The fade is
  // purely positional (independent of the parallel/waiting logic below), which
  // is what the design calls for. `waiting` still drives the "waits its turn"
  // tag: the first sequential task gates later sequential ones; parallel tasks
  // are never blocked.
  const rows: Row[] = []
  let gated = false
  upNext.forEach((task, i) => {
    const waiting = !task.parallel && gated
    const opacity = Math.max(0.4, 1 - i * 0.18)
    rows.push({ task, waiting, opacity })
    if (!task.parallel) gated = true
  })

  const allDone = tasks.length > 0 && upNext.length === 0

  return (
    <div style={{ maxWidth: 680, margin: '0 auto' }}>
      <div style={{ marginBottom: 'var(--space-4)' }}>
        <h2 style={{ margin: 0, fontSize: 'var(--text-2xl)', fontWeight: 800, letterSpacing: '-0.02em', color: 'var(--color-text-primary)' }}>
          Up next
        </h2>
        <div style={{ marginTop: 4, fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
          {done} of {total} done
          {currentMilestoneTitle && <> · {currentMilestoneTitle}</>}
          <span style={{ color: 'var(--color-text-subtle, var(--color-text-muted))' }}> · {dateLabel}</span>
        </div>
        {(isAdjusting || adjustError) && (
          <div style={{ marginTop: 6, fontSize: 'var(--text-xs)', color: adjustError ? 'var(--color-danger)' : 'var(--color-accent)' }}>
            {adjustError ?? 'Updating your plan from your feedback…'}
          </div>
        )}
      </div>

      {allDone ? null : upNext.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', lineHeight: 1.5 }}>
          Nothing scheduled for this day. Use the arrows to check another day.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          {rows.slice(0, VISIBLE_COUNT).map(({ task, waiting, opacity }) => (
            <TaskRow
              key={task.id}
              task={task}
              waiting={waiting}
              opacity={opacity}
              colorIndex={colorOf(task)}
              member={task.assigneeId ? membersById.get(task.assigneeId) ?? null : null}
              onToggle={waiting ? undefined : () => onToggleDone(task)}
              onFeedback={fb => onFeedback(task, fb)}
              onDelete={() => onDelete(task)}
              onOpen={() => onOpen(task)}
            />
          ))}
          {rows.length > VISIBLE_COUNT && (
            <div style={{ marginTop: 4, paddingLeft: 18, fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
              {rows.length - VISIBLE_COUNT} more — they'll appear as you check these off.
            </div>
          )}
        </div>
      )}

      {allDone && (
        <div style={donepanelStyle}>
          <div style={{ fontSize: 'var(--text-lg)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            You're done for today 🎉
          </div>
          <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
            Everything scheduled for {dateLabel} is checked off. Want to keep the momentum going?
          </p>
          <button onClick={onExtendDay} disabled={isExtending} style={extendBtnStyle}>
            <Sparkles size={15} />
            {isExtending ? 'Planning more tasks…' : 'Plan more for today'}
          </button>
          {extendError && (
            <span style={{ fontSize: 11, color: 'var(--color-danger)' }}>{extendError}</span>
          )}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'center', marginTop: 'var(--space-5)' }}>
        <button onClick={onOpenPlanMap} style={planMapBtnStyle}>
          <Map size={14} />
          Plan map
        </button>
      </div>
    </div>
  )
}

function TaskRow({
  task,
  waiting,
  opacity,
  colorIndex,
  member,
  onToggle,
  onFeedback,
  onDelete,
  onOpen,
}: {
  task: FlatTask
  waiting: boolean
  opacity: number
  colorIndex: number | null
  member: RoadmapMember | null
  /** Undefined while `waiting` — a task can't be checked off out of order. */
  onToggle: (() => void) | undefined
  onFeedback: (fb: string) => void
  onDelete: () => void
  onOpen: () => void
}) {
  const lane = laneVars(colorIndex)
  const done = task.status === 'done'

  // Local draft so typing is smooth; persist on blur only when it changed.
  const [draft, setDraft] = useState(task.feedback ?? '')
  const lastSaved = useRef(task.feedback ?? '')
  // Feedback is tucked away until asked for, so cards stay compact. Open
  // automatically when a note already exists.
  const [noteOpen, setNoteOpen] = useState(Boolean(task.feedback?.trim()))
  useEffect(() => {
    setDraft(task.feedback ?? '')
    lastSaved.current = task.feedback ?? ''
    if (task.feedback?.trim()) setNoteOpen(true)
  }, [task.id, task.feedback])

  const saveFeedback = () => {
    if (draft !== lastSaved.current) {
      lastSaved.current = draft
      onFeedback(draft)
    }
  }

  const checkbox = (size: number) => (
    <button
      onClick={onToggle}
      disabled={waiting}
      aria-label={done ? 'Mark as not done' : waiting ? 'Waiting on an earlier task' : 'Mark as done'}
      aria-pressed={done}
      style={{
        flexShrink: 0,
        width: size,
        height: size,
        marginTop: 2,
        padding: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: '50%',
        cursor: waiting ? 'not-allowed' : 'pointer',
        border: `2px solid ${done ? 'var(--color-success)' : waiting ? 'var(--color-border-subtle)' : lane.solid}`,
        background: done ? 'var(--color-success)' : 'transparent',
        opacity: waiting ? 0.5 : 1,
        transition: 'background 0.15s, border-color 0.15s',
      }}
    >
      {done && <Check size={Math.round(size * 0.6)} color="#fff" strokeWidth={3} />}
    </button>
  )

  return (
    <div
      className="pl-task-card"
      style={{
        display: 'flex',
        gap: 'var(--space-3)',
        padding: '16px 18px',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--color-border-subtle)',
        background: 'var(--color-bg-elevated)',
        boxShadow: 'var(--shadow-sm)',
        // Waiting tasks fade progressively (see `opacity` in DayAgenda) — the
        // detail is still there, just dimmed until it's their turn.
        opacity: done ? 0.65 : opacity,
      }}
    >
      {checkbox(20)}

      {/* Body */}
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={onOpen} style={titleBtnStyle}>
            <span style={{ textDecoration: done ? 'line-through' : 'none', fontWeight: 700, fontSize: 'var(--text-base)', color: 'var(--color-text-primary)' }}>
              {task.title}
            </span>
          </button>
          {task.parallel && <span style={parallelTagStyle}>PARALLEL</span>}
          {waiting && <span style={waitingTagStyle}>waits its turn</span>}
          <span style={{ flex: 1 }} />
          <div className="pl-task-actions" style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            {member && <Avatar name={member.name} colorIndex={member.colorIndex} avatarUrl={member.avatarUrl} initials={member.initials} size="xs" />}
            <IconButton label="Delete task" size={18} onClick={onDelete}>
              <Trash2 size={12} />
            </IconButton>
          </div>
        </div>

        {/* Milestone as a quiet caption under the title (matches the mockup) */}
        <div style={{ marginTop: 3, fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
          {task.milestoneTitle}
        </div>

        {task.description && (
          <p
            style={{
              margin: '8px 0 0',
              fontSize: 'var(--text-sm)',
              color: 'var(--color-text-secondary)',
              lineHeight: 1.55,
              // Trim long descriptions to three lines; the full text is in the
              // task detail modal (click the title).
              display: '-webkit-box',
              WebkitLineClamp: 3,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {task.description}
          </p>
        )}

        {noteOpen ? (
          <textarea
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onBlur={saveFeedback}
            placeholder="How did this go? Note blockers, what changed, how long it took…"
            rows={2}
            autoFocus={!task.feedback?.trim()}
            style={feedbackStyle}
          />
        ) : (
          <button onClick={() => setNoteOpen(true)} style={addNoteBtnStyle}>
            + Add a note
          </button>
        )}
      </div>
    </div>
  )
}

const titleBtnStyle: CSSProperties = {
  padding: 0,
  border: 'none',
  background: 'transparent',
  cursor: 'pointer',
  textAlign: 'left',
  minWidth: 0,
}

const parallelTagStyle: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '0.05em',
  color: 'var(--color-success)',
  background: 'var(--color-success-bg)',
  borderRadius: 999,
  padding: '2px 8px',
  whiteSpace: 'nowrap',
}

const waitingTagStyle: CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  fontStyle: 'italic',
  color: 'var(--color-text-muted)',
  whiteSpace: 'nowrap',
}

const feedbackStyle: CSSProperties = {
  width: '100%',
  marginTop: 8,
  resize: 'vertical',
  padding: '7px 9px',
  borderRadius: 'var(--radius-md)',
  border: '1px solid var(--color-border-subtle)',
  background: 'var(--color-bg-secondary)',
  color: 'var(--color-text-primary)',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  lineHeight: 1.45,
}

const addNoteBtnStyle: CSSProperties = {
  marginTop: 8,
  padding: 0,
  border: 'none',
  background: 'transparent',
  cursor: 'pointer',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-xs)',
  color: 'var(--color-text-muted)',
}

const donepanelStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'flex-start',
  gap: 'var(--space-3)',
  marginTop: 'var(--space-4)',
  padding: 'var(--space-4)',
  borderRadius: 'var(--radius-lg)',
  border: '1px solid var(--color-border-subtle)',
  background: 'var(--color-bg-secondary)',
}

const extendBtnStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  padding: '9px 16px',
  borderRadius: 'var(--radius-md)',
  cursor: 'pointer',
  border: 'none',
  background: 'var(--color-accent)',
  color: '#fff',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  fontWeight: 'var(--font-weight-semibold)' as CSSProperties['fontWeight'],
}

const planMapBtnStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  padding: '10px 22px',
  borderRadius: 999,
  cursor: 'pointer',
  border: 'none',
  // Solid, high-contrast pill like the mockup's "Plan map" button.
  background: 'var(--color-text-primary)',
  color: 'var(--color-bg-elevated)',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  fontWeight: 'var(--font-weight-semibold)' as CSSProperties['fontWeight'],
  boxShadow: 'var(--shadow-sm)',
}
