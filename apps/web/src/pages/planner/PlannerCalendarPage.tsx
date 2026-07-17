// apps/web/src/pages/planner/PlannerCalendarPage.tsx
//
// The Planner is a personal, day-by-day calendar of the tasks in the roadmap
// generated from onboarding (GET /api/roadmap). Tasks can be checked off
// (PATCH status) or deleted (DELETE). If no roadmap exists yet, the page offers
// a one-click "Generate my plan" (POST /api/roadmap/generate).

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, Sparkles, Trash2 } from 'lucide-react'
import { useApi, ApiError } from '../../lib/api'
import { Button } from '../../components/ui/Button'
import { Alert } from '../../components/ui/Alert'
import type { Roadmap, RoadmapTask } from '../../types/roadmap'

const ROADMAP_KEY = ['roadmap']

// ─── date helpers (local, no timezone shift) ────────────────────────────────────
function parseISO(d: string): Date {
  const [y, m, day] = d.split('-').map(Number)
  return new Date(y, m - 1, day)
}
function toISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function addDays(d: Date, n: number): Date {
  const c = new Date(d)
  c.setDate(c.getDate() + n)
  return c
}
/** Monday of the week containing `d`. */
function mondayOf(d: Date): Date {
  const c = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const dow = (c.getDay() + 6) % 7 // 0 = Monday
  return addDays(c, -dow)
}
const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// ─── immutable roadmap transforms (for optimistic cache updates) ────────────────
function mapTask(rm: Roadmap, taskId: string, fn: (t: RoadmapTask) => RoadmapTask): Roadmap {
  return {
    ...rm,
    milestones: rm.milestones.map(m => ({
      ...m,
      tasks: m.tasks.map(t => (t.id === taskId ? fn(t) : t)),
    })),
  }
}
function removeTask(rm: Roadmap, taskId: string): Roadmap {
  return {
    ...rm,
    milestones: rm.milestones.map(m => ({ ...m, tasks: m.tasks.filter(t => t.id !== taskId) })),
  }
}

interface FlatTask extends RoadmapTask {
  milestoneTitle: string
  milestoneIndex: number
}

export function PlannerCalendarPage() {
  const { get, post, patch, del } = useApi()
  const qc = useQueryClient()

  const roadmapQuery = useQuery({
    queryKey: ROADMAP_KEY,
    queryFn: () => get<Roadmap | null>('/api/roadmap'),
  })
  const roadmap = roadmapQuery.data ?? null

  const generate = useMutation({
    mutationFn: () => post<Roadmap>('/api/roadmap/generate', {}),
    onSuccess: data => qc.setQueryData(ROADMAP_KEY, data),
  })

  const toggleTask = useMutation({
    mutationFn: ({ id, status }: { id: string; status: RoadmapTask['status'] }) =>
      patch<RoadmapTask>(`/api/roadmap/tasks/${id}`, { status }),
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: ROADMAP_KEY })
      const prev = qc.getQueryData<Roadmap | null>(ROADMAP_KEY)
      if (prev) qc.setQueryData(ROADMAP_KEY, mapTask(prev, id, t => ({ ...t, status })))
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev !== undefined) qc.setQueryData(ROADMAP_KEY, ctx.prev)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ROADMAP_KEY }),
  })

  const deleteTask = useMutation({
    mutationFn: (id: string) => del<void>(`/api/roadmap/tasks/${id}`),
    onMutate: async (id: string) => {
      await qc.cancelQueries({ queryKey: ROADMAP_KEY })
      const prev = qc.getQueryData<Roadmap | null>(ROADMAP_KEY)
      if (prev) qc.setQueryData(ROADMAP_KEY, removeTask(prev, id))
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev !== undefined) qc.setQueryData(ROADMAP_KEY, ctx.prev)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ROADMAP_KEY }),
  })

  // Flatten tasks and index them by scheduled day.
  const { byDate, unscheduled, total, done, firstDate } = useMemo(() => {
    const byDate = new Map<string, FlatTask[]>()
    const unscheduled: FlatTask[] = []
    let total = 0
    let done = 0
    let firstDate: string | null = null
    ;(roadmap?.milestones ?? []).forEach((m, mi) => {
      for (const t of m.tasks) {
        total += 1
        if (t.status === 'done') done += 1
        const flat: FlatTask = { ...t, milestoneTitle: m.title, milestoneIndex: mi }
        if (t.scheduledDate) {
          if (!byDate.has(t.scheduledDate)) byDate.set(t.scheduledDate, [])
          byDate.get(t.scheduledDate)!.push(flat)
          if (!firstDate || t.scheduledDate < firstDate) firstDate = t.scheduledDate
        } else {
          unscheduled.push(flat)
        }
      }
    })
    for (const list of byDate.values()) {
      list.sort((a, b) => a.milestoneIndex - b.milestoneIndex || a.sortOrder - b.sortOrder)
    }
    return { byDate, unscheduled, total, done, firstDate }
  }, [roadmap])

  // Viewed week anchor (Monday). Starts at the first scheduled task's week.
  const [weekStart, setWeekStart] = useState<Date | null>(null)
  const anchor = weekStart ?? mondayOf(firstDate ? parseISO(firstDate) : new Date())
  const weekDays = WEEKDAY_LABELS.map((_, i) => addDays(anchor, i))
  const weekEnd = addDays(anchor, 4)
  const todayISO = toISO(new Date())

  // ─── loading / error / empty states ──────────────────────────────────────────
  if (roadmapQuery.isLoading) {
    return <PageShell><div style={muted}>Loading your plan…</div></PageShell>
  }

  if (!roadmap) {
    const err = generate.error
    const notOnboarded = err instanceof ApiError && err.status === 409
    return (
      <PageShell>
        <div style={{ textAlign: 'center', padding: '4rem 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
          <div style={{ fontSize: 30, color: 'var(--color-text-muted)' }}>🗓️</div>
          <div style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-base)', maxWidth: 420, lineHeight: 1.5 }}>
            Turn your project idea into a day-by-day plan. We'll break it into milestones and lay the tasks out on your calendar.
          </div>
          {notOnboarded ? (
            <Alert variant="warning" style={{ maxWidth: 440 }}>
              {err.message}
            </Alert>
          ) : generate.isError ? (
            <Alert variant="danger" style={{ maxWidth: 440 }}>
              {err instanceof Error ? err.message : 'Could not generate your plan. Please try again.'}
            </Alert>
          ) : null}
          <Button variant="primary" size="lg" onClick={() => generate.mutate()} disabled={generate.isPending}>
            <Sparkles size={16} /> {generate.isPending ? 'Building your plan…' : 'Generate my plan'}
          </Button>
        </div>
      </PageShell>
    )
  }

  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  return (
    <PageShell>
      {/* Header: project + progress */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700, color: 'var(--color-text-primary)', margin: 0 }}>{roadmap.name}</h1>
          {roadmap.summary && (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', margin: '4px 0 0', maxWidth: 620, lineHeight: 1.5 }}>{roadmap.summary}</p>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>{done}/{total} done</div>
          <div style={{ width: 120, height: 6, borderRadius: 999, background: 'var(--color-bg-tertiary, var(--color-border))', overflow: 'hidden' }}>
            <div style={{ width: `${pct}%`, height: '100%', background: 'var(--color-success)', transition: 'width 0.2s' }} />
          </div>
        </div>
      </div>

      {/* Week navigation */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <Button variant="ghost" size="sm" onClick={() => setWeekStart(addDays(anchor, -7))} aria-label="Previous week">
          <ChevronLeft size={16} />
        </Button>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)' as never, color: 'var(--color-text-primary)', minWidth: 190, textAlign: 'center' }}>
          {MONTHS[anchor.getMonth()]} {anchor.getDate()} – {MONTHS[weekEnd.getMonth()]} {weekEnd.getDate()}
        </div>
        <Button variant="ghost" size="sm" onClick={() => setWeekStart(addDays(anchor, 7))} aria-label="Next week">
          <ChevronRight size={16} />
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setWeekStart(mondayOf(new Date()))}>Today</Button>
      </div>

      {/* Week grid: Mon–Fri */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 10, alignItems: 'start' }}>
        {weekDays.map((day, i) => {
          const iso = toISO(day)
          const tasks = byDate.get(iso) ?? []
          const isToday = iso === todayISO
          return (
            <div key={iso} style={{
              border: `1px solid ${isToday ? 'var(--color-accent)' : 'var(--color-border)'}`,
              borderRadius: 'var(--radius-lg)',
              background: 'var(--color-bg-elevated)',
              minHeight: 180,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}>
              <div style={{
                padding: '8px 10px',
                borderBottom: '1px solid var(--color-border-subtle)',
                display: 'flex', alignItems: 'baseline', gap: 6,
                background: isToday ? 'var(--color-accent-subtle)' : 'transparent',
              }}>
                <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: isToday ? 'var(--color-accent)' : 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{WEEKDAY_LABELS[i]}</span>
                <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--color-text-primary)' }}>{day.getDate()}</span>
              </div>
              <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                {tasks.length === 0 ? (
                  <div style={{ ...muted, fontSize: 'var(--text-xs)', padding: '4px 2px' }}>—</div>
                ) : (
                  tasks.map(t => (
                    <TaskCard
                      key={t.id}
                      task={t}
                      onToggle={() => toggleTask.mutate({ id: t.id, status: t.status === 'done' ? 'todo' : 'done' })}
                      onDelete={() => deleteTask.mutate(t.id)}
                    />
                  ))
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Unscheduled fallback (rare) */}
      {unscheduled.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Unscheduled</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {unscheduled.map(t => (
              <div key={t.id} style={{ width: 220 }}>
                <TaskCard
                  task={t}
                  onToggle={() => toggleTask.mutate({ id: t.id, status: t.status === 'done' ? 'todo' : 'done' })}
                  onDelete={() => deleteTask.mutate(t.id)}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </PageShell>
  )
}

function TaskCard({ task, onToggle, onDelete }: { task: FlatTask; onToggle: () => void; onDelete: () => void }) {
  const done = task.status === 'done'
  return (
    <div style={{
      position: 'relative',
      border: '1px solid var(--color-border-subtle)',
      borderRadius: 'var(--radius-md)',
      background: done ? 'var(--color-bg-secondary)' : 'var(--color-bg-primary)',
      padding: '7px 8px',
      display: 'flex',
      gap: 7,
      opacity: done ? 0.7 : 1,
    }}>
      <button
        onClick={onToggle}
        aria-label={done ? 'Mark as not done' : 'Mark as done'}
        aria-pressed={done}
        style={{
          flexShrink: 0, width: 16, height: 16, marginTop: 1, cursor: 'pointer',
          borderRadius: 4, border: `1.5px solid ${done ? 'var(--color-success)' : 'var(--color-border-strong, var(--color-border))'}`,
          background: done ? 'var(--color-success)' : 'transparent',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0,
        }}
      >
        {done && <Check size={11} color="#fff" strokeWidth={3} />}
      </button>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{
          fontSize: 'var(--text-sm)', color: 'var(--color-text-primary)', lineHeight: 1.35,
          textDecoration: done ? 'line-through' : 'none',
          fontFamily: 'var(--font-sans)',
        }}>
          {task.title}
        </div>
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {task.milestoneTitle}
        </div>
      </div>
      <button
        onClick={onDelete}
        aria-label="Delete task"
        style={{
          flexShrink: 0, background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--color-text-muted)', padding: 2, height: 20, display: 'flex', alignItems: 'center',
        }}
      >
        <Trash2 size={13} />
      </button>
    </div>
  )
}

function PageShell({ children }: { children: React.ReactNode }) {
  return <div style={{ fontFamily: 'var(--font-sans)', minHeight: '100%' }}>{children}</div>
}

const muted: React.CSSProperties = {
  color: 'var(--color-text-muted)',
  fontSize: 'var(--text-sm)',
}
