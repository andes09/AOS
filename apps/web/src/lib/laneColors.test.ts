import { describe, it, expect } from 'vitest'
import {
  laneVars,
  normalizeLaneIndex,
  initialsOf,
  LANE_COLOR_COUNT,
  ALL_LANE_INDICES,
} from './laneColors'

describe('normalizeLaneIndex', () => {
  it('passes through in-range indices', () => {
    expect(normalizeLaneIndex(0)).toBe(0)
    expect(normalizeLaneIndex(9)).toBe(9)
  })

  it('wraps beyond the palette size', () => {
    expect(normalizeLaneIndex(10)).toBe(0)
    expect(normalizeLaneIndex(13)).toBe(3)
  })

  it('wraps negatives into range', () => {
    // JS `%` keeps the dividend's sign, so a bare `-1 % 10` is -1 and would
    // produce `var(--lane--1-solid)` — a token that does not exist and renders
    // as no color at all.
    expect(normalizeLaneIndex(-1)).toBe(9)
    expect(normalizeLaneIndex(-10)).toBe(0)
    expect(normalizeLaneIndex(-13)).toBe(7)
  })

  it('truncates fractional input', () => {
    expect(normalizeLaneIndex(3.7)).toBe(3)
  })
})

describe('laneVars', () => {
  it('resolves an index to its three tokens', () => {
    expect(laneVars(3)).toEqual({
      solid: 'var(--lane-3-solid)',
      bg: 'var(--lane-3-bg)',
      text: 'var(--lane-3-text)',
    })
  })

  it('resolves unassigned to the neutral set', () => {
    const expected = {
      solid: 'var(--lane-none-solid)',
      bg: 'var(--lane-none-bg)',
      text: 'var(--lane-none-text)',
    }
    expect(laneVars(null)).toEqual(expected)
    expect(laneVars(undefined)).toEqual(expected)
  })

  it('falls back to neutral rather than emitting a NaN token', () => {
    expect(laneVars(NaN).solid).toBe('var(--lane-none-solid)')
    expect(laneVars(Infinity).solid).toBe('var(--lane-none-solid)')
  })

  it('wraps out-of-range indices instead of throwing', () => {
    // A team can outgrow the palette; duplicated color on person 11 is a much
    // better failure than a crashed planner.
    expect(laneVars(10).solid).toBe('var(--lane-0-solid)')
    expect(laneVars(-1).solid).toBe('var(--lane-9-solid)')
  })

  it('never emits a malformed token for any index in range', () => {
    for (const i of ALL_LANE_INDICES) {
      const vars = laneVars(i)
      expect(vars.solid).toMatch(/^var\(--lane-\d-solid\)$/)
      expect(vars.bg).toMatch(/^var\(--lane-\d-bg\)$/)
      expect(vars.text).toMatch(/^var\(--lane-\d-text\)$/)
    }
  })

  it('gives every palette index a distinct token triple', () => {
    const seen = new Set(ALL_LANE_INDICES.map(i => laneVars(i).solid))
    expect(seen.size).toBe(LANE_COLOR_COUNT)
  })
})

describe('initialsOf', () => {
  it('takes first and last initials', () => {
    expect(initialsOf('Ada Lovelace')).toBe('AL')
  })

  it('skips middle names', () => {
    expect(initialsOf('Ada King Lovelace')).toBe('AL')
  })

  it('uses two letters for a single name', () => {
    expect(initialsOf('Ada')).toBe('AD')
  })

  it('handles extra whitespace', () => {
    expect(initialsOf('  Ada   Lovelace  ')).toBe('AL')
  })

  it('falls back to ? for an empty name', () => {
    expect(initialsOf('')).toBe('?')
    expect(initialsOf('   ')).toBe('?')
  })

  it('uppercases lowercase input', () => {
    expect(initialsOf('ada lovelace')).toBe('AL')
  })
})
