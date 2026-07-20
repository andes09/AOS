import { describe, it, expect } from 'vitest'
import {
  parseISO,
  toISO,
  addDays,
  mondayOf,
  parseTime,
  toTimeStr,
  formatTime12h,
  addMinutesToTime,
  endTimeOf,
  formatDuration,
  compareByTime,
} from './date'

describe('parseISO / toISO', () => {
  it('round-trips without shifting the day', () => {
    expect(toISO(parseISO('2026-07-19'))).toBe('2026-07-19')
  })

  it('parses to LOCAL midnight, not UTC midnight', () => {
    // This is the whole point of the helper. `new Date("2026-07-19")` parses as
    // UTC midnight per spec, which is the 18th in any negative-offset zone.
    const d = parseISO('2026-07-19')
    expect(d.getFullYear()).toBe(2026)
    expect(d.getMonth()).toBe(6) // 0-indexed July
    expect(d.getDate()).toBe(19)
    expect(d.getHours()).toBe(0)
  })

  it('pads single-digit months and days', () => {
    expect(toISO(new Date(2026, 0, 5))).toBe('2026-01-05')
  })
})

describe('addDays', () => {
  it('crosses a month boundary', () => {
    expect(toISO(addDays(parseISO('2026-01-31'), 1))).toBe('2026-02-01')
  })

  it('crosses a year boundary', () => {
    expect(toISO(addDays(parseISO('2026-12-31'), 1))).toBe('2027-01-01')
  })

  it('handles a leap day', () => {
    expect(toISO(addDays(parseISO('2028-02-28'), 1))).toBe('2028-02-29')
  })

  it('goes backwards', () => {
    expect(toISO(addDays(parseISO('2026-03-01'), -1))).toBe('2026-02-28')
  })

  it('does not drift across a spring-forward DST boundary', () => {
    // US DST starts 2026-03-08. Adding a day across it must still land on the
    // 8th, not 23:00 on the 7th — which is what naive ms arithmetic produces.
    expect(toISO(addDays(parseISO('2026-03-07'), 1))).toBe('2026-03-08')
    expect(toISO(addDays(parseISO('2026-03-08'), 1))).toBe('2026-03-09')
  })

  it('does not drift across a fall-back DST boundary', () => {
    // US DST ends 2026-11-01.
    expect(toISO(addDays(parseISO('2026-10-31'), 1))).toBe('2026-11-01')
    expect(toISO(addDays(parseISO('2026-11-01'), 1))).toBe('2026-11-02')
  })

  it('does not mutate its argument', () => {
    const d = parseISO('2026-07-19')
    addDays(d, 5)
    expect(toISO(d)).toBe('2026-07-19')
  })
})

describe('mondayOf', () => {
  it('returns the same day when given a Monday', () => {
    expect(toISO(mondayOf(parseISO('2026-07-13')))).toBe('2026-07-13')
  })

  it('walks back from midweek', () => {
    expect(toISO(mondayOf(parseISO('2026-07-16')))).toBe('2026-07-13')
  })

  it('treats Sunday as the END of its week, not the start', () => {
    // getDay() is 0 for Sunday, so a naive implementation jumps forward a week.
    expect(toISO(mondayOf(parseISO('2026-07-19')))).toBe('2026-07-13')
  })
})

describe('parseTime', () => {
  it('parses to minutes since midnight', () => {
    expect(parseTime('00:00')).toBe(0)
    expect(parseTime('09:30')).toBe(570)
    expect(parseTime('23:59')).toBe(1439)
  })

  it('accepts an unpadded hour', () => {
    expect(parseTime('9:30')).toBe(570)
  })

  it('ignores trailing seconds', () => {
    expect(parseTime('09:30:00')).toBe(570)
  })

  it('returns null for empty and malformed input', () => {
    expect(parseTime(null)).toBeNull()
    expect(parseTime(undefined)).toBeNull()
    expect(parseTime('')).toBeNull()
    expect(parseTime('nope')).toBeNull()
  })

  it('rejects out-of-range values', () => {
    expect(parseTime('24:00')).toBeNull()
    expect(parseTime('09:60')).toBeNull()
  })
})

describe('toTimeStr', () => {
  it('formats zero-padded', () => {
    expect(toTimeStr(0)).toBe('00:00')
    expect(toTimeStr(570)).toBe('09:30')
    expect(toTimeStr(1439)).toBe('23:59')
  })

  it('wraps past midnight instead of producing hour 24+', () => {
    expect(toTimeStr(1440)).toBe('00:00')
    expect(toTimeStr(1500)).toBe('01:00')
  })

  it('wraps negatives forward', () => {
    expect(toTimeStr(-60)).toBe('23:00')
  })

  it('round-trips with parseTime', () => {
    for (const t of ['00:00', '07:15', '12:00', '18:45', '23:59']) {
      expect(toTimeStr(parseTime(t)!)).toBe(t)
    }
  })
})

describe('formatTime12h', () => {
  it('formats morning and afternoon', () => {
    expect(formatTime12h('09:30')).toBe('9:30am')
    expect(formatTime12h('13:45')).toBe('1:45pm')
  })

  it('handles noon as 12pm, not 0pm', () => {
    expect(formatTime12h('12:00')).toBe('12:00pm')
    expect(formatTime12h('12:30')).toBe('12:30pm')
  })

  it('handles midnight as 12am, not 0am', () => {
    expect(formatTime12h('00:00')).toBe('12:00am')
    expect(formatTime12h('00:15')).toBe('12:15am')
  })

  it('keeps 11:59pm on the pm side', () => {
    expect(formatTime12h('23:59')).toBe('11:59pm')
  })

  it('returns empty string for missing input', () => {
    expect(formatTime12h(null)).toBe('')
    expect(formatTime12h('garbage')).toBe('')
  })
})

describe('addMinutesToTime', () => {
  it('adds within the day', () => {
    expect(addMinutesToTime('09:30', 45)).toBe('10:15')
  })

  it('subtracts', () => {
    expect(addMinutesToTime('09:30', -45)).toBe('08:45')
  })

  it('wraps past midnight', () => {
    expect(addMinutesToTime('23:30', 60)).toBe('00:30')
  })

  it('returns null for unparseable input', () => {
    expect(addMinutesToTime('nope', 10)).toBeNull()
  })
})

describe('endTimeOf', () => {
  it('adds the duration', () => {
    expect(endTimeOf('09:30', 45)).toBe('10:15')
  })

  it('returns null without a start or a duration', () => {
    expect(endTimeOf(null, 45)).toBeNull()
    expect(endTimeOf('09:30', null)).toBeNull()
    expect(endTimeOf('09:30', 0)).toBeNull()
  })
})

describe('formatDuration', () => {
  it('formats minutes, hours, and both', () => {
    expect(formatDuration(45)).toBe('45m')
    expect(formatDuration(60)).toBe('1h')
    expect(formatDuration(90)).toBe('1h 30m')
    expect(formatDuration(120)).toBe('2h')
  })

  it('returns empty for absent or non-positive input', () => {
    expect(formatDuration(null)).toBe('')
    expect(formatDuration(0)).toBe('')
    expect(formatDuration(-30)).toBe('')
  })
})

describe('compareByTime', () => {
  it('orders chronologically', () => {
    expect(compareByTime('09:30', '13:00')).toBeLessThan(0)
    expect(compareByTime('13:00', '09:30')).toBeGreaterThan(0)
    expect(compareByTime('09:30', '09:30')).toBe(0)
  })

  it('sorts untimed tasks before timed ones', () => {
    // Untimed work reads as an all-day band at the top of a column.
    expect(compareByTime(null, '09:30')).toBeLessThan(0)
    expect(compareByTime('09:30', null)).toBeGreaterThan(0)
    expect(compareByTime(null, null)).toBe(0)
  })

  it('produces a stable sorted order', () => {
    const times = ['13:00', null, '09:30', '23:15', null, '00:05']
    expect([...times].sort(compareByTime)).toEqual([null, null, '00:05', '09:30', '13:00', '23:15'])
  })
})
