// apps/web/src/pages/planner/PlannerPage.tsx
//
// The planner: team-member lanes down the left, time-blocked days on the right.
// Replaces the original PlannerCalendarPage (a bare Mon–Fri checkbox grid).
//
// Task color comes strictly from the assignee — see lib/laneColors.ts.

import { useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { Search, Sparkles } from 'lucide-react'
import { ApiError } from '../../lib/api'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Modal } from '../../components/ui/Modal'
import { addDays, mondayOf, parseISO, toISO } from '../../lib/date'
import { PlannerSidebar } from '../../components/planner/PlannerSidebar'
import { PlannerToolbar } from '../../components/planner/PlannerToolbar'
import type { PlannerOutletContext } from '../../components/planner/plannerViews'
import { CalendarGrid } from '../../components/planner/CalendarGrid'
import { DayAgenda } from '../../components/planner/DayAgenda'
import { ListView } from '../../components/planner/ListView'
import { BoardView } from '../../components/planner/BoardView'
import { UnscheduledTray } from '../../components/planner/UnscheduledTray'
import { TaskCard } from '../../components/planner/TaskCard'
import { TaskDetailModal } from '../../components/planner/TaskDetailModal'
import { AssistantChat } from '../../components/planner/AssistantChat'
import { usePlannerData, type FlatTask } from './usePlannerData'
import { usePlannerMutations, type TaskPatch } from './usePlannerMutations'
import { EMPTY_FILTERS, toggleInSet, UNASSIGNED, type PlannerFilters } from './plannerFilters'

/** Visible window of the timed grid. Outside these hours nothing renders. */
const START_HOUR = 7
const END_HOUR = 20

/** Persisted collapse state for the member-lane panel. '0' = collapsed. */
const LANES_KEY = 'aos_planner_lanes'

export function PlannerPage() {
  // `view` lives in the layout so the top-bar switcher and this page share it.
  // The page only reads it; the top bar owns the setter.
  const { view } = useOutletContext<PlannerOutletContext>()

  const [filters, setFilters] = useState<PlannerFilters>(EMPTY_FILTERS)
  const [anchorOverride, setAnchorOverride] = useState<Date | null>(null)
  const [collapsedLanes, setCollapsedLanes] = useState<Set<string>>(new Set())
  const [lanesHidden, setLanesHidden] = useState(() => localStorage.getItem(LANES_KEY) === '0')
  const [trayCollapsed, setTrayCollapsed] = useState(false)
  const [openTaskId, setOpenTaskId] = useState<string | null>(null)
  const [draggingTask, setDraggingTask] = useState<FlatTask | null>(null)
  // Ask right away when there's no plan yet (fresh out of onboarding), rather
  // than leaving generation as a button the user has to notice on their own.
  const [askOpen, setAskOpen] = useState(true)

  const toggleLanesPanel = () =>
    setLanesHidden(prev => {
      const next = !prev
      localStorage.setItem(LANES_KEY, next ? '0' : '1')
      return next
    })

  const data = usePlannerData(filters)
  // `rescheduleTasks` is intentionally not destructured here — a single drag is
  // one task, so it goes through updateTask. The bulk endpoint is wired up in
  // the hook and waits for multi-select.
  const { generate, regenerate, adjust, updateTask, deleteTask, createTask, toggleDone } =
    usePlannerMutations()

  // Require a real drag before starting one, or the checkbox and delete button
  // on each card stop being clickable.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  const anchor = useMemo(() => {
    if (anchorOverride) return anchorOverride
    const base = data.firstDate ? parseISO(data.firstDate) : new Date()
    return view === 'day' ? base : mondayOf(base)
  }, [anchorOverride, data.firstDate, view])

  const dayCount = view === 'day' ? 1 : 5
  const rangeEnd = addDays(anchor, dayCount - 1)

  const colorOf = (task: FlatTask) =>
    task.assigneeId ? data.membersById.get(task.assigneeId)?.colorIndex ?? null : null

  const openTask = openTaskId ? data.allTasks.find(t => t.id === openTaskId) ?? null : null

  // ─── handlers ────────────────────────────────────────────────────────────
  const handleDragStart = (e: DragStartEvent) => {
    setDraggingTask((e.active.data.current?.task as FlatTask) ?? null)
  }

  const handleDragEnd = (e: DragEndEvent) => {
    setDraggingTask(null)
    const task = e.active.data.current?.task as FlatTask | undefined
    const over = e.over?.data.current as
      | { type: 'slot'; iso: string; time: string }
      | { type: 'day'; iso: string }
      | { type: 'lane'; assigneeId: string | null }
      | { type: 'unscheduled' }
      | undefined
    if (!task || !over) return

    // Each drop target translates to the smallest patch that expresses it, so
    // dropping onto a lane never disturbs a task's schedule and vice versa.
    let patch: TaskPatch
    switch (over.type) {
      case 'slot':
        patch = { scheduledDate: over.iso, scheduledTime: over.time }
        break
      case 'day':
        patch = { scheduledDate: over.iso, scheduledTime: null }
        break
      case 'lane':
        if (task.assigneeId === over.assigneeId) return
        patch = { assigneeId: over.assigneeId }
        break
      case 'unscheduled':
        patch = { scheduledDate: null, scheduledTime: null }
        break
      default:
        return
    }
    updateTask.mutate({ id: task.id, patch })
  }

  const handleAddTask = (assigneeId: string | null) => {
    createTask.mutate({ title: 'New task', assigneeId })
  }

  const toggleLane = (key: string) => setCollapsedLanes(s => toggleInSet(s, key))
  const selectLane = (key: string) =>
    setFilters(f => ({ ...f, assigneeIds: toggleInSet(f.assigneeIds, key) }))

  // ─── loading / empty ─────────────────────────────────────────────────────
  if (data.isLoading) {
    return <Shell><p style={mutedText}>Loading your plan…</p></Shell>
  }

  if (!data.roadmap) {
    const err = generate.error
    const notOnboarded = err instanceof ApiError && err.status === 409
    const errorAlert = notOnboarded ? (
      <Alert variant="warning" style={{ maxWidth: 440 }}>{err.message}</Alert>
    ) : generate.isError ? (
      <Alert variant="danger" style={{ maxWidth: 440 }}>
        {err instanceof Error ? err.message : 'Could not generate your plan. Please try again.'}
      </Alert>
    ) : null

    return (
      <Shell>
        <div style={emptyStateStyle}>
          <div style={{ fontSize: 30 }}>🗓️</div>
          <p style={{ color: 'var(--color-text-secondary)', maxWidth: 420, lineHeight: 1.5, margin: 0 }}>
            Turn your project idea into a day-by-day plan. We'll break it into milestones and lay the
            tasks out across your team's week.
          </p>
          {errorAlert}
          <Button variant="primary" size="lg" onClick={() => generate.mutate()} disabled={generate.isPending}>
            <Sparkles size={16} /> {generate.isPending ? 'Building your plan…' : 'Generate my plan'}
          </Button>
        </div>

        <Modal open={askOpen} onClose={() => setAskOpen(false)} title="Ready to build your plan?" width={440}>
          <p style={{ color: 'var(--color-text-secondary)', lineHeight: 1.5, marginTop: 0 }}>
            Turn your project idea into a day-by-day plan — we'll break it into milestones and lay
            tasks out across your team's week.
          </p>
          {errorAlert}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 20 }}>
            <Button variant="secondary" onClick={() => setAskOpen(false)}>
              Not now
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                generate.mutate()
                setAskOpen(false)
              }}
              disabled={generate.isPending}
            >
              <Sparkles size={16} /> Generate my plan
            </Button>
          </div>
        </Modal>
      </Shell>
    )
  }

  const isCalendar = view === 'week' || view === 'day'

  return (
    <Shell>
      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <PlannerToolbar
          rangeStart={anchor}
          rangeEnd={rangeEnd}
          onPrev={() => setAnchorOverride(addDays(anchor, -dayCount))}
          onNext={() => setAnchorOverride(addDays(anchor, dayCount))}
          onToday={() => setAnchorOverride(view === 'day' ? new Date() : mondayOf(new Date()))}
          done={data.stats.done}
          total={data.stats.total}
          pct={data.stats.pct}
          showDateNav={isCalendar}
          lanesCollapsed={lanesHidden}
          onToggleLanes={toggleLanesPanel}
        />

        <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'flex-start' }}>
          {!lanesHidden && (
            <PlannerSidebar
              members={data.members}
              byAssignee={data.byAssignee}
              collapsedIds={collapsedLanes}
              selectedIds={filters.assigneeIds}
              onToggleCollapse={toggleLane}
              onToggleSelect={selectLane}
              onCollapsePanel={toggleLanesPanel}
              onAddTask={handleAddTask}
              renderTask={t => (
                <TaskCard
                  key={t.id}
                  task={t}
                  colorIndex={colorOf(t)}
                  showMilestone={false}
                  onToggle={() => toggleDone(t)}
                  onDelete={() => deleteTask.mutate(t.id)}
                  onOpen={() => setOpenTaskId(t.id)}
                />
              )}
            />
          )}

          <main style={{ flex: 1, minWidth: 0 }}>
            <div style={{ marginBottom: 'var(--space-3)', maxWidth: 280, position: 'relative' }}>
              <Search
                size={13}
                style={{
                  position: 'absolute',
                  left: 8,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--color-text-muted)',
                  pointerEvents: 'none',
                }}
              />
              <Input
                value={filters.search}
                onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
                placeholder="Search tasks…"
                aria-label="Search tasks"
                style={{ paddingLeft: 26 }}
              />
            </div>

            {view === 'day' && (
              <DayAgenda
                iso={toISO(anchor)}
                tasks={data.byDate.get(toISO(anchor)) ?? []}
                membersById={data.membersById}
                colorOf={colorOf}
                onStatus={(t, status) => updateTask.mutate({ id: t.id, patch: { status } })}
                onFeedback={(t, feedback) => updateTask.mutate({ id: t.id, patch: { feedback } })}
                onDelete={t => deleteTask.mutate(t.id)}
                onOpen={t => setOpenTaskId(t.id)}
                onAdjust={() => adjust.mutate()}
                isAdjusting={adjust.isPending}
                adjustError={
                  adjust.isError
                    ? adjust.error instanceof Error
                      ? adjust.error.message
                      : 'Could not update the plan.'
                    : null
                }
              />
            )}
            {view === 'week' && (
              <CalendarGrid
                anchor={anchor}
                dayCount={dayCount}
                byDate={data.byDate}
                startHour={START_HOUR}
                endHour={END_HOUR}
                colorOf={colorOf}
                onToggle={toggleDone}
                onDelete={t => deleteTask.mutate(t.id)}
                onOpen={t => setOpenTaskId(t.id)}
              />
            )}
            {view === 'list' && (
              <ListView
                tasks={data.allTasks}
                colorOf={colorOf}
                onToggle={toggleDone}
                onDelete={t => deleteTask.mutate(t.id)}
                onOpen={t => setOpenTaskId(t.id)}
              />
            )}
            {view === 'board' && (
              <BoardView
                tasks={data.allTasks}
                colorOf={colorOf}
                onToggle={toggleDone}
                onDelete={t => deleteTask.mutate(t.id)}
                onOpen={t => setOpenTaskId(t.id)}
              />
            )}

            {isCalendar && (
              <UnscheduledTray
                tasks={data.unscheduled}
                collapsed={trayCollapsed}
                onToggleCollapse={() => setTrayCollapsed(c => !c)}
                colorOf={colorOf}
                onToggle={toggleDone}
                onDelete={t => deleteTask.mutate(t.id)}
                onOpen={t => setOpenTaskId(t.id)}
              />
            )}
          </main>
        </div>

        {/* Rendered in an overlay rather than transformed in place: an
            absolutely-positioned card inside an overflow:hidden day column
            would be clipped mid-drag. */}
        <DragOverlay dropAnimation={null} style={{ zIndex: 'var(--z-drag-overlay)' as never }}>
          {draggingTask && (
            <div style={{ width: 200, opacity: 0.95 }}>
              <TaskCard
                task={draggingTask}
                colorIndex={colorOf(draggingTask)}
                draggable={false}
                onToggle={() => {}}
                onDelete={() => {}}
              />
            </div>
          )}
        </DragOverlay>
      </DndContext>

      <TaskDetailModal
        task={openTask}
        members={data.members}
        onClose={() => setOpenTaskId(null)}
        onSave={patch => openTask && updateTask.mutate({ id: openTask.id, patch })}
        onDelete={() => openTask && deleteTask.mutate(openTask.id)}
      />

      <AssistantChat
        onRegenerate={() => regenerate.mutate()}
        isRegenerating={regenerate.isPending}
        regenerateError={
          regenerate.isError
            ? regenerate.error instanceof Error
              ? regenerate.error.message
              : 'Could not rebuild the plan.'
            : null
        }
      />
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div style={{ fontFamily: 'var(--font-sans)', minHeight: '100%' }}>{children}</div>
}

const mutedText = { color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' } as const

const emptyStateStyle = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: 16,
  padding: '4rem 0',
  textAlign: 'center',
} as const

// Re-exported so the sidebar's sentinel stays in one place.
export { UNASSIGNED }
