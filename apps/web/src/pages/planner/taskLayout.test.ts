import { describe, it, expect } from 'vitest'
import { layoutDay, nowOffset, DEFAULT_DURATION_MINUTES, MIN_BLOCK_HEIGHT } from './taskLayout'

const t = (id: string, scheduledTime: string | null, durationMinutes: number | null = 60) => ({
  id,
  scheduledTime,
  durationMinutes,
})

describe('layoutDay', () => {
  it('positions a task relative to the grid start, not midnight', () => {
    // 09:00 in a grid starting at 07:00 is 120px down, not 540.
    const [box] = layoutDay([t('a', '09:00')], 7 * 60)
    expect(box.top).toBe(120)
    expect(box.height).toBe(60)
  })

  it('gives a non-overlapping task the full column width', () => {
    const [box] = layoutDay([t('a', '09:00')], 7 * 60)
    expect(box.widthPct).toBe(1)
    expect(box.leftPct).toBe(0)
  })

  it('skips untimed tasks — they belong in the all-day strip', () => {
    expect(layoutDay([t('a', null)], 7 * 60)).toEqual([])
  })

  it('splits two overlapping tasks side by side', () => {
    const boxes = layoutDay([t('a', '09:00'), t('b', '09:30')], 7 * 60)
    expect(boxes.map(b => b.widthPct)).toEqual([0.5, 0.5])
    expect(boxes.map(b => b.leftPct).sort()).toEqual([0, 0.5])
  })

  it('splits three-way pileups into thirds', () => {
    const boxes = layoutDay([t('a', '09:00'), t('b', '09:15'), t('c', '09:30')], 7 * 60)
    expect(boxes.every(b => Math.abs(b.widthPct - 1 / 3) < 1e-9)).toBe(true)
  })

  it('keeps sequential tasks full width', () => {
    // 09:00-10:00 then 10:00-11:00 touch but do not overlap.
    const boxes = layoutDay([t('a', '09:00'), t('b', '10:00')], 7 * 60)
    expect(boxes.map(b => b.widthPct)).toEqual([1, 1])
  })

  it('does not let one pileup shrink an unrelated later task', () => {
    // The 14:00 task is its own cluster and must stay full width.
    const boxes = layoutDay([t('a', '09:00'), t('b', '09:30'), t('c', '14:00')], 7 * 60)
    const byId = new Map(boxes.map(b => [b.id, b]))
    expect(byId.get('a')!.widthPct).toBe(0.5)
    expect(byId.get('b')!.widthPct).toBe(0.5)
    expect(byId.get('c')!.widthPct).toBe(1)
  })

  it('reuses a freed column within one cluster', () => {
    // a: 9-11 (long). b: 9:30-10 and c: 10-10:30 both fit beside it, in the
    // same column, because b ends before c starts.
    const boxes = layoutDay(
      [t('a', '09:00', 120), t('b', '09:30', 30), t('c', '10:00', 30)],
      7 * 60,
    )
    const byId = new Map(boxes.map(b => [b.id, b]))
    expect(byId.get('b')!.leftPct).toBe(byId.get('c')!.leftPct)
    expect(boxes.every(b => b.widthPct === 0.5)).toBe(true)
  })

  it('enforces a minimum height so short tasks stay clickable', () => {
    const [box] = layoutDay([t('a', '09:00', 5)], 7 * 60)
    expect(box.height).toBe(MIN_BLOCK_HEIGHT)
  })

  it('treats a missing duration as the default for overlap purposes', () => {
    const [box] = layoutDay([t('a', '09:00', null)], 7 * 60)
    expect(box.height).toBe(DEFAULT_DURATION_MINUTES)
  })

  it('is not sensitive to input order', () => {
    const forward = layoutDay([t('a', '09:00'), t('b', '09:30')], 7 * 60)
    const reversed = layoutDay([t('b', '09:30'), t('a', '09:00')], 7 * 60)
    expect(new Map(reversed.map(b => [b.id, b.top]))).toEqual(
      new Map(forward.map(b => [b.id, b.top])),
    )
  })
})

describe('nowOffset', () => {
  it('returns an offset when now is inside the window', () => {
    expect(nowOffset(7, 20, new Date(2026, 6, 19, 9, 30))).toBe(150)
  })

  it('returns null outside the window', () => {
    expect(nowOffset(7, 20, new Date(2026, 6, 19, 6, 0))).toBeNull()
    expect(nowOffset(7, 20, new Date(2026, 6, 19, 21, 0))).toBeNull()
  })
})
