// apps/web/src/lib/laneColors.ts
//
// The single source of truth for assignee color in the planner.
//
// Color is strictly a function of who owns a task — there is no per-task
// override. Routing every color decision through `laneVars` is what enforces
// that at the type level rather than by convention: a caller cannot supply a
// color, only an identity, and identities that resolve to nobody get grey.
//
// The database stores a `colorIndex` (identity: "you are person 3"); this
// module owns appearance ("person 3 is violet"). Retuning the palette for
// contrast is therefore a CSS change in tokens.css, never a data migration.

/** Number of distinct hues defined as `--lane-N-*` in tokens.css. */
export const LANE_COLOR_COUNT = 10

export interface LaneVars {
  /** Dot, left border, avatar tint. Carries ≥3:1 against the page. */
  solid: string
  /** Card fill. Pale in light mode, hue-tinted near-black in dark. */
  bg: string
  /** Label sitting on `bg`. Carries ≥4.5:1 against it. */
  text: string
}

/**
 * Resolve an assignee's `colorIndex` to CSS custom-property references.
 *
 * `null` (unassigned) resolves to the neutral grey set, which is deliberately
 * desaturated so that owned work is what reads as colored on the board.
 *
 * Out-of-range and negative indices wrap rather than throwing — a team can
 * outgrow the palette, and duplicated color on person 11 is a far better
 * failure than a crashed planner.
 */
export function laneVars(colorIndex: number | null | undefined): LaneVars {
  if (colorIndex === null || colorIndex === undefined || !Number.isFinite(colorIndex)) {
    return {
      solid: 'var(--lane-none-solid)',
      bg: 'var(--lane-none-bg)',
      text: 'var(--lane-none-text)',
    }
  }
  const i = normalizeLaneIndex(colorIndex)
  return {
    solid: `var(--lane-${i}-solid)`,
    bg: `var(--lane-${i}-bg)`,
    text: `var(--lane-${i}-text)`,
  }
}

/**
 * Wrap an arbitrary integer into `[0, LANE_COLOR_COUNT)`.
 *
 * Uses a double-modulo so negatives map into range too: JS `%` keeps the
 * sign of the dividend, so a bare `-1 % 10` is `-1` and would produce
 * `var(--lane--1-solid)`, which silently renders as no color at all.
 */
export function normalizeLaneIndex(colorIndex: number): number {
  const n = Math.trunc(colorIndex)
  return ((n % LANE_COLOR_COUNT) + LANE_COLOR_COUNT) % LANE_COLOR_COUNT
}

/** Every lane index, for palette previews and color pickers. */
export const ALL_LANE_INDICES: readonly number[] = Array.from(
  { length: LANE_COLOR_COUNT },
  (_, i) => i,
)

/**
 * Initials fallback for avatars, used when the API has not supplied them
 * (it computes them server-side so they stay consistent across surfaces).
 * Takes the first letter of the first and last whitespace-separated parts.
 */
export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
