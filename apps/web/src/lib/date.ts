// apps/web/src/lib/date.ts
//
// Date and time helpers for the planner. Moved out of PlannerCalendarPage so
// they can be shared and unit-tested.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE ONE RULE: planner dates and times are WALL-CLOCK, never instants.
//
// "The 9:30am standup" is a fact about a clock face, not a point on a timeline.
// The API stores a naive DATE and a naive TIME to match, and nothing in this
// file may convert between the two.
//
// Concretely, that means:
//   • Never `new Date(isoString)` on a date-only string. The ES spec parses a
//     bare "2026-07-19" as UTC midnight, which renders as the 18th anywhere
//     west of Greenwich. Always use the local-fields constructor, as parseISO
//     does below.
//   • Never `.toISOString()` to serialize a planner date. It converts to UTC
//     and reintroduces exactly the shift parseISO exists to avoid. Use toISO.
//
// A team spanning timezones therefore sees the same label everywhere, which is
// the correct product behaviour for planned work.
// ─────────────────────────────────────────────────────────────────────────────

// ─── Dates ──────────────────────────────────────────────────────────────────

/** Parse `YYYY-MM-DD` into a local-midnight Date. Never UTC — see header. */
export function parseISO(d: string): Date {
  const [y, m, day] = d.split('-').map(Number)
  return new Date(y, m - 1, day)
}

/** Serialize a Date to `YYYY-MM-DD` using its local fields. */
export function toISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function addDays(d: Date, n: number): Date {
  const c = new Date(d)
  c.setDate(c.getDate() + n)
  return c
}

/** Monday of the week containing `d`. */
export function mondayOf(d: Date): Date {
  const c = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const dow = (c.getDay() + 6) % 7 // 0 = Monday
  return addDays(c, -dow)
}

/** Today as `YYYY-MM-DD`, local. */
export function todayISO(): string {
  return toISO(new Date())
}

export function isSameISODate(a: Date, b: Date): boolean {
  return toISO(a) === toISO(b)
}

export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const

// ─── Times ──────────────────────────────────────────────────────────────────
//
// Times are `HH:MM` strings (24-hour, zero-padded) end to end — the same shape
// the API emits via strftime('%H:%M'). They are deliberately NOT Date objects:
// a Date would force a date and a timezone onto a value that has neither.

/** Minutes since local midnight for an `HH:MM` string, or null if unparseable. */
export function parseTime(t: string | null | undefined): number | null {
  if (!t) return null
  const m = /^(\d{1,2}):(\d{2})/.exec(t)
  if (!m) return null
  const h = Number(m[1])
  const min = Number(m[2])
  if (h < 0 || h > 23 || min < 0 || min > 59) return null
  return h * 60 + min
}

/** Inverse of parseTime: minutes-since-midnight to `HH:MM`. Wraps past 24h. */
export function toTimeStr(minutes: number): string {
  const wrapped = ((Math.trunc(minutes) % 1440) + 1440) % 1440
  const h = Math.floor(wrapped / 60)
  const m = wrapped % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/**
 * Human time label: "9:30am", "12:00pm", "12:00am".
 *
 * Note the two midday/midnight edges, which are the classic off-by-twelve:
 * hour 0 displays as 12am and hour 12 displays as 12pm, so neither can be a
 * plain `h % 12`.
 */
export function formatTime12h(t: string | null | undefined): string {
  const mins = parseTime(t)
  if (mins === null) return ''
  const h24 = Math.floor(mins / 60)
  const m = mins % 60
  const suffix = h24 < 12 ? 'am' : 'pm'
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12
  return `${h12}:${String(m).padStart(2, '0')}${suffix}`
}

/** Minutes since midnight, for positioning a task against the time axis. */
export function minutesFromMidnight(t: string | null | undefined): number | null {
  return parseTime(t)
}

/** Shift an `HH:MM` by a signed number of minutes. Returns null if unparseable. */
export function addMinutesToTime(t: string, delta: number): string | null {
  const mins = parseTime(t)
  if (mins === null) return null
  return toTimeStr(mins + delta)
}

/** End time of a task, or null when it has no start or no duration. */
export function endTimeOf(start: string | null | undefined, durationMinutes: number | null | undefined): string | null {
  const mins = parseTime(start)
  if (mins === null || !durationMinutes) return null
  return toTimeStr(mins + durationMinutes)
}

/** "45m", "1h", "1h 30m" — compact duration label for cards. */
export function formatDuration(minutes: number | null | undefined): string {
  if (!minutes || minutes <= 0) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m}m`
  if (m === 0) return `${h}h`
  return `${h}h ${m}m`
}

/**
 * Chronological comparator for tasks within a day.
 *
 * Untimed tasks sort before timed ones so they read as an "all day" band at
 * the top of a column rather than being scattered through the hours.
 */
export function compareByTime(a: string | null | undefined, b: string | null | undefined): number {
  const ta = parseTime(a)
  const tb = parseTime(b)
  if (ta === null && tb === null) return 0
  if (ta === null) return -1
  if (tb === null) return 1
  return ta - tb
}
