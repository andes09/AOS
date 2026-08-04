import { describe, it, expect } from 'vitest'
import { computeDagLayout, type DagTaskInput } from './dependencyLayout'

const t = (id: string, dependsOn: string[] = [], milestoneIndex = 0, sortOrder = 0): DagTaskInput => ({
  id,
  dependsOn,
  milestoneIndex,
  sortOrder,
})

const rankOf = (layout: ReturnType<typeof computeDagLayout>, id: string) =>
  layout.nodes.find(n => n.id === id)?.rank

describe('computeDagLayout', () => {
  it('returns an empty layout for no tasks', () => {
    const layout = computeDagLayout([])
    expect(layout.nodes).toEqual([])
    expect(layout.edges).toEqual([])
    expect(layout.width).toBe(0)
    expect(layout.height).toBe(0)
  })

  it('places a single task with no deps at rank 0 with no edges', () => {
    const layout = computeDagLayout([t('a')])
    expect(layout.nodes).toHaveLength(1)
    expect(layout.nodes[0]).toMatchObject({ id: 'a', rank: 0, order: 0 })
    expect(layout.edges).toEqual([])
  })

  it('ranks a linear chain in order', () => {
    const layout = computeDagLayout([t('a'), t('b', ['a']), t('c', ['b'])])
    expect(rankOf(layout, 'a')).toBe(0)
    expect(rankOf(layout, 'b')).toBe(1)
    expect(rankOf(layout, 'c')).toBe(2)
    expect(layout.edges).toEqual(
      expect.arrayContaining([
        { from: 'a', to: 'b' },
        { from: 'b', to: 'c' },
      ]),
    )
  })

  it('ranks a diamond by the longest incoming path, not double-counted', () => {
    // a -> b -> d, a -> c -> d
    const layout = computeDagLayout([t('a'), t('b', ['a']), t('c', ['a']), t('d', ['b', 'c'])])
    expect(rankOf(layout, 'a')).toBe(0)
    expect(rankOf(layout, 'b')).toBe(1)
    expect(rankOf(layout, 'c')).toBe(1)
    expect(rankOf(layout, 'd')).toBe(2)
  })

  it('orders independent chains within a shared rank column by milestoneIndex then sortOrder', () => {
    const layout = computeDagLayout([
      t('later', [], 1, 0),
      t('earlier', [], 0, 0),
      t('middle', [], 0, 1),
    ])
    const rank0 = layout.nodes.filter(n => n.rank === 0).sort((a, b) => a.order - b.order)
    expect(rank0.map(n => n.id)).toEqual(['earlier', 'middle', 'later'])
  })

  it('ignores a dangling dependsOn id — no edge, no crash, correct rank', () => {
    const layout = computeDagLayout([t('a', ['ghost'])])
    expect(rankOf(layout, 'a')).toBe(0)
    expect(layout.edges).toEqual([])
  })

  it('does not infinite-loop on a self-referential dependsOn', () => {
    const layout = computeDagLayout([t('a', ['a'])])
    expect(rankOf(layout, 'a')).toBe(0)
    expect(layout.edges).toEqual([])
  })

  it('does not infinite-loop on a two-node cycle and resolves finite ranks', () => {
    const layout = computeDagLayout([t('a', ['b']), t('b', ['a'])])
    expect(Number.isFinite(rankOf(layout, 'a'))).toBe(true)
    expect(Number.isFinite(rankOf(layout, 'b'))).toBe(true)
  })

  it('produces the same layout regardless of input order', () => {
    const tasks = [t('a'), t('b', ['a']), t('c', ['a']), t('d', ['b', 'c'])]
    const shuffled = [tasks[3], tasks[1], tasks[2], tasks[0]]
    const a = computeDagLayout(tasks)
    const b = computeDagLayout(shuffled)
    const norm = (l: ReturnType<typeof computeDagLayout>) =>
      [...l.nodes].sort((x, y) => x.id.localeCompare(y.id)).map(n => ({ id: n.id, rank: n.rank, order: n.order }))
    expect(norm(a)).toEqual(norm(b))
  })
})
