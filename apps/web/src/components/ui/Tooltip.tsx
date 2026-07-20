import { CSSProperties, ReactNode, useId, useState } from 'react'

interface TooltipProps {
  /** Tooltip text. When empty, the trigger renders bare. */
  content: ReactNode
  children: ReactNode
  placement?: 'top' | 'bottom'
  style?: CSSProperties
}

/**
 * Lightweight hover/focus tooltip.
 *
 * Deliberately CSS-positioned rather than portalled: the planner's tooltips
 * are short labels on dense controls, and a portal + positioning engine would
 * be far more machinery than that needs. If a tooltip ever has to escape an
 * `overflow: hidden` ancestor, that is the moment to reach for a portal — not
 * before.
 *
 * Shows on focus as well as hover so it is reachable by keyboard, and is wired
 * up with `aria-describedby` so the text is actually announced.
 */
export function Tooltip({ content, children, placement = 'top', style }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const id = useId()

  if (!content) return <>{children}</>

  return (
    <span
      style={{ position: 'relative', display: 'inline-flex', ...style }}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      <span aria-describedby={visible ? id : undefined} style={{ display: 'inline-flex' }}>
        {children}
      </span>
      {visible && (
        <span
          role="tooltip"
          id={id}
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            [placement === 'top' ? 'bottom' : 'top']: 'calc(100% + 6px)',
            zIndex: 'var(--z-dropdown)' as never,
            padding: '4px 8px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--color-text-primary)',
            color: 'var(--color-bg-primary)',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-xs)',
            lineHeight: 1.4,
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            boxShadow: 'var(--shadow-md)',
          }}
        >
          {content}
        </span>
      )}
    </span>
  )
}
