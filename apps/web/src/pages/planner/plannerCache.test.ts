import { describe, it, expect } from 'vitest'
import { addTask, mapTask, mapTasks, removeTask } from './plannerCache'
import type { Roadmap, RoadmapTask } from '../../types/roadmap'

const task = (id: string, over: Partial<RoadmapTask> = {}): RoadmapTask => ({
  id,
  title: `Task ${id}`,
  description: null,
  status: 'todo',
  sortOrder: 0,
  scheduledDate: null,
  scheduledTime: null,
  durationMinutes: null,
  parallel: false,
  assigneeId: null,
  feedback: null,
  ...over,
})

const roadmap = (): Roadmap => ({
  id: 'r1',
  name: 'Plan',
  summary: null,
  purpose: null,
  milestones: [
    { id: 'm1', title: 'M1', description: null, sortOrder: 0, tasks: [task('a'), task('b')] },
    { id: 'm2', title: 'M2', description: null, sortOrder: 1, tasks: [task('c')] },
  ],
})

const find = (rm: Roadmap, id: string) =>
  rm.milestones.flatMap(m => m.tasks).find(t => t.id === id)

describe('mapTask', () => {
  it('updates the matching task', () => {
    const next = mapTask(roadmap(), 'b', t => ({ ...t, status: 'done' }))
    expect(find(next, 'b')!.status).toBe('done')
  })

  it('leaves other tasks untouched', () => {
    const next = mapTask(roadmap(), 'b', t => ({ ...t, status: 'done' }))
    expect(find(next, 'a')!.status).toBe('todo')
    expect(find(next, 'c')!.status).toBe('todo')
  })

  it('does not mutate the input', () => {
    const rm = roadmap()
    mapTask(rm, 'b', t => ({ ...t, status: 'done' }))
    expect(find(rm, 'b')!.status).toBe('todo')
  })

  it('is a no-op for an unknown id', () => {
    const next = mapTask(roadmap(), 'nope', t => ({ ...t, status: 'done' }))
    expect(next.milestones.flatMap(m => m.tasks).every(t => t.status === 'todo')).toBe(true)
  })
})

describe('removeTask', () => {
  it('drops only the named task', () => {
    const next = removeTask(roadmap(), 'a')
    expect(next.milestones[0].tasks.map(t => t.id)).toEqual(['b'])
    expect(next.milestones[1].tasks.map(t => t.id)).toEqual(['c'])
  })

  it('does not mutate the input', () => {
    const rm = roadmap()
    removeTask(rm, 'a')
    expect(rm.milestones[0].tasks).toHaveLength(2)
  })
})

describe('mapTasks', () => {
  it('applies several updates in one pass', () => {
    const next = mapTasks(roadmap(), [
      { id: 'a', scheduledDate: '2026-03-02' },
      { id: 'c', assigneeId: 'dev-1' },
    ])
    expect(find(next, 'a')!.scheduledDate).toBe('2026-03-02')
    expect(find(next, 'c')!.assigneeId).toBe('dev-1')
  })

  it('treats an omitted key as "leave alone"', () => {
    const rm = roadmap()
    rm.milestones[0].tasks[0] = task('a', { scheduledTime: '09:30', assigneeId: 'dev-1' })
    // Only the date is present, so time and assignee must survive.
    const next = mapTasks(rm, [{ id: 'a', scheduledDate: '2026-03-02' }])
    expect(find(next, 'a')!.scheduledTime).toBe('09:30')
    expect(find(next, 'a')!.assigneeId).toBe('dev-1')
  })

  it('treats an explicit null as "clear"', () => {
    const rm = roadmap()
    rm.milestones[0].tasks[0] = task('a', { scheduledTime: '09:30', assigneeId: 'dev-1' })
    const next = mapTasks(rm, [{ id: 'a', scheduledTime: null, assigneeId: null }])
    expect(find(next, 'a')!.scheduledTime).toBeNull()
    expect(find(next, 'a')!.assigneeId).toBeNull()
  })

  it('returns the same reference for an empty batch', () => {
    const rm = roadmap()
    expect(mapTasks(rm, [])).toBe(rm)
  })

  it('ignores unknown ids', () => {
    const next = mapTasks(roadmap(), [{ id: 'nope', scheduledDate: '2026-03-02' }])
    expect(next.milestones.flatMap(m => m.tasks)).toHaveLength(3)
  })
})

describe('addTask', () => {
  it('appends to the named milestone', () => {
    const next = addTask(roadmap(), task('d'), 'm1')
    expect(next.milestones[0].tasks.map(t => t.id)).toEqual(['a', 'b', 'd'])
  })

  it('falls back to the last milestone by sortOrder, matching the server', () => {
    const next = addTask(roadmap(), task('d'))
    expect(next.milestones[1].tasks.map(t => t.id)).toEqual(['c', 'd'])
  })

  it('uses sortOrder rather than array position for the fallback', () => {
    const rm = roadmap()
    // Highest sortOrder is now the FIRST array element.
    rm.milestones[0].sortOrder = 5
    const next = addTask(rm, task('d'))
    expect(next.milestones[0].tasks.map(t => t.id)).toEqual(['a', 'b', 'd'])
  })

  it('is a no-op when there are no milestones', () => {
    const empty: Roadmap = { ...roadmap(), milestones: [] }
    expect(addTask(empty, task('d'))).toBe(empty)
  })
})
