import { CSSProperties, ReactNode } from 'react'

export interface SegmentedOption<T extends string> {
  value: T
  /** Visible text. Omit when using `icon` alone, but then supply `label`. */
  content?: ReactNode
  icon?: ReactNode
  /** Accessible name — required when there is no text content. */
  label: string
}

interface SegmentedControlProps<T extends string> {
  options: readonly SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  size?: 'sm' | 'md'
  style?: CSSProperties
  /** Accessible name for the group as a whole, e.g. "Calendar view". */
  ariaLabel: string
}

/**
 * A row of mutually exclusive options rendered as one connected control —
 * the planner's day/week/list/board switcher, and general enough for any
 * small either/or choice.
 *
 * Uses `role="radiogroup"` rather than a row of buttons so screen readers
 * announce it as a single choice with a current selection, which is what it
 * actually is.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
  style,
  ariaLabel,
}: SegmentedControlProps<T>) {
  const height = size === 'sm' ? 26 : 32
  const pad = size === 'sm' ? '0 8px' : '0 12px'

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 2,
        padding: 2,
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
        ...style,
      }}
    >
      {options.map(opt => {
        const selected = opt.value === value
        return (
          <button
            key={opt.value}
            role="radio"
            aria-checked={selected}
            aria-label={opt.label}
            title={opt.label}
            onClick={() => onChange(opt.value)}
            className="pl-icon-btn"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              height,
              padding: pad,
              border: 'none',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              fontFamily: 'var(--font-sans)',
              fontSize: size === 'sm' ? 'var(--text-xs)' : 'var(--text-sm)',
              fontWeight: 'var(--font-weight-medium)' as CSSProperties['fontWeight'],
              lineHeight: 1,
              whiteSpace: 'nowrap',
              background: selected ? 'var(--color-bg-elevated)' : 'transparent',
              color: selected ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              boxShadow: selected ? 'var(--shadow-sm)' : 'none',
            }}
          >
            {opt.icon}
            {opt.content}
          </button>
        )
      })}
    </div>
  )
}
