import { CSSProperties, useEffect, useRef, useState } from 'react'
import { Check, Map } from 'lucide-react'
import { Avatar } from '../ui/Avatar'
import { laneVars } from '../../lib/laneColors'
import type { RoadmapMember } from '../../types/roadmap'
import type { FlatTask } from '../../pages/planner/usePlannerData'

interface DayAgendaProps {
  /** The whole plan's not-done tasks, in plan order — this is a single
   *  continuous queue, not scoped to any particular calendar day. */
  tasks: FlatTask[]
  /** Every task in the plan (unfiltered) by id, for resolving `dependsOn`. */
  tasksById: Map<string, FlatTask>
  membersById: Map<string, RoadmapMember>
  colorOf: (task: FlatTask) => number | null
  /** Plan-wide progress, for the "Up next" subtitle. */
  done: number
  total: number
  currentMilestoneTitle: string | null
  onToggleDone: (task: FlatTask) => void
  onFeedback: (task: FlatTask, feedback: string) => void
  onOpen: (task: FlatTask) => void
  /** Feedback auto-updates the plan; these just surface that background work. */
  isAdjusting: boolean
  adjustError: string | null
  onOpenPlanMap: () => void
}

/** How many upcoming tasks to surface at once; the rest reveal as these are
 *  checked off, keeping the focus on what's immediately next. */
const VISIBLE_COUNT = 3

/** A task's derived state within the queue, computed from `dependsOn` + order. */
interface Row {
  task: FlatTask
  /** Blocked by an unmet dependency (some `dependsOn` task isn't `done`). */
  waiting: boolean
  /** Ready now, and not simply the single next thing in the queue — i.e. an
   *  additional, independently-startable track alongside whatever's first. */
  isParallel: boolean
  /** Card opacity — waiting tasks fade progressively so the eye lands on the
   *  work that's actually actionable now. */
  opacity: number
}

/**
 * "Up next": one continuous queue of clean, tappable task cards in plan
 * order, with no day boundaries — checking a task off reveals the next one
 * already generated for the plan, so the queue never dead-ends. A task that
 * still "waits its turn" (a sequential task gated by earlier unfinished
 * work) renders faded. Feedback boxes stay, and writing feedback
 * auto-updates the plan in the background.
 */
export function DayAgenda({
  tasks,
  tasksById,
  membersById,
  colorOf,
  done,
  total,
  currentMilestoneTitle,
  onToggleDone,
  onFeedback,
  onOpen,
  isAdjusting,
  adjustError,
  onOpenPlanMap,
}: DayAgendaProps) {
  // "Up next" is a queue of what's left: completed tasks drop out, and
  // checking a task off clears it, letting the next one in plan order show.
  const upNext = tasks.filter(t => t.status !== 'done')

  // Every card fades a little more than the one above it, so the eye lands on
  // the most immediate task and later work recedes down the queue. The fade is
  // purely positional (independent of the waiting logic below), which is what
  // the design calls for. `waiting` is a real dependency-graph check: a task
  // waits if any of its `dependsOn` tasks isn't `done` yet. `isParallel` tags
  // every ready task except the first one encountered — "workable right now,
  // and not simply the one thing you'd do next."
  const rows: Row[] = []
  let firstReadySeen = false
  upNext.forEach((task, i) => {
    const waiting = task.dependsOn.some(id => tasksById.get(id)?.status !== 'done')
    const isParallel = !waiting && firstReadySeen
    const opacity = Math.max(0.4, 1 - i * 0.18)
    rows.push({ task, waiting, isParallel, opacity })
    if (!waiting) firstReadySeen = true
  })

  return (
    <div style={{ maxWidth: 680, margin: '0 auto' }}>
      <div style={{ marginBottom: 'var(--space-4)' }}>
        <h2 style={{ margin: 0, fontSize: 'var(--text-2xl)', fontWeight: 800, letterSpacing: '-0.02em', color: 'var(--color-text-primary)' }}>
          Up next
        </h2>
        <div style={{ marginTop: 4, fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
          {done} of {total} done
          {currentMilestoneTitle && <> · {currentMilestoneTitle}</>}
        </div>
        {(isAdjusting || adjustError) && (
          <div style={{ marginTop: 6, fontSize: 'var(--text-xs)', color: adjustError ? 'var(--color-danger)' : 'var(--color-accent)' }}>
            {adjustError ?? 'Updating your plan from your feedback…'}
          </div>
        )}
      </div>

      {upNext.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', lineHeight: 1.5 }}>
          You're all caught up 🎉 — nothing left in the plan right now.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          {rows.slice(0, VISIBLE_COUNT).map(({ task, waiting, isParallel, opacity }) => (
            <TaskRow
              key={task.id}
              task={task}
              waiting={waiting}
              isParallel={isParallel}
              opacity={opacity}
              colorIndex={colorOf(task)}
              member={task.assigneeId ? membersById.get(task.assigneeId) ?? null : null}
              onToggle={waiting ? undefined : () => onToggleDone(task)}
              onFeedback={fb => onFeedback(task, fb)}
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

      <div style={planMapWrapStyle}>
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
  isParallel,
  opacity,
  colorIndex,
  member,
  onToggle,
  onFeedback,
  onOpen,
}: {
  task: FlatTask
  waiting: boolean
  isParallel: boolean
  opacity: number
  colorIndex: number | null
  member: RoadmapMember | null
  /** Undefined while `waiting` — a task can't be checked off out of order. */
  onToggle: (() => void) | undefined
  onFeedback: (fb: string) => void
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
          {isParallel && <span style={parallelTagStyle}>PARALLEL</span>}
          {waiting && <span style={waitingTagStyle}>waits its turn</span>}
          <span style={{ flex: 1 }} />
          {member && <Avatar name={member.name} colorIndex={member.colorIndex} avatarUrl={member.avatarUrl} initials={member.initials} size="xs" />}
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

// Fixed in the lower fifth of the viewport rather than flowing after the
// task list, so it stays reachable at a consistent spot regardless of queue
// length or scroll position.
const planMapWrapStyle: CSSProperties = {
  position: 'fixed',
  left: '50%',
  bottom: '10vh',
  transform: 'translateX(-50%)',
  zIndex: 10,
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
