import { CSSProperties } from 'react'
import { laneVars, initialsOf } from '../../lib/laneColors'

export type AvatarSize = 'xs' | 'sm' | 'md' | 'lg'

interface AvatarProps {
  name: string
  /** Assignee color index. `null` renders the neutral unassigned treatment. */
  colorIndex?: number | null
  avatarUrl?: string | null
  size?: AvatarSize
  /** Precomputed initials from the API. Falls back to deriving from `name`. */
  initials?: string | null
  style?: CSSProperties
  title?: string
}

const sizePx: Record<AvatarSize, number> = { xs: 18, sm: 22, md: 28, lg: 36 }
const fontPx: Record<AvatarSize, number> = { xs: 8, sm: 9, md: 11, lg: 13 }

/**
 * Circular identity chip, tinted with the person's lane color so the sidebar,
 * task cards, and assignee pickers all agree on who is which color.
 *
 * The initials fallback prefers the API-supplied value so it stays identical
 * across surfaces, and only derives locally when none was provided.
 */
export function Avatar({
  name,
  colorIndex = null,
  avatarUrl,
  size = 'sm',
  initials,
  style,
  title,
}: AvatarProps) {
  const px = sizePx[size]
  const lane = laneVars(colorIndex)
  const label = initials?.trim() || initialsOf(name)

  const base: CSSProperties = {
    width: px,
    height: px,
    flexShrink: 0,
    borderRadius: '50%',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    fontFamily: 'var(--font-sans)',
    fontSize: fontPx[size],
    fontWeight: 'var(--font-weight-semibold)' as CSSProperties['fontWeight'],
    lineHeight: 1,
    userSelect: 'none',
    ...style,
  }

  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={name}
        title={title ?? name}
        style={{ ...base, objectFit: 'cover', boxShadow: `0 0 0 1.5px ${lane.solid}` }}
      />
    )
  }

  return (
    <span
      aria-hidden="true"
      title={title ?? name}
      style={{ ...base, background: lane.bg, color: lane.text, boxShadow: `0 0 0 1.5px ${lane.solid}` }}
    >
      {label}
    </span>
  )
}
