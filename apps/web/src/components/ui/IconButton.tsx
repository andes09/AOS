import { ButtonHTMLAttributes, CSSProperties, ReactNode } from 'react'

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required — the button has no text, so it needs an accessible name. */
  label: string
  children: ReactNode
  size?: number
}

/**
 * Square, borderless button for a single icon. Hover and focus-visible styling
 * comes from `.pl-icon-btn` in styles/planner.css, since inline styles cannot
 * express pseudo-selectors.
 */
export function IconButton({ label, children, size = 24, style, className, ...rest }: IconButtonProps) {
  const base: CSSProperties = {
    width: size,
    height: size,
    flexShrink: 0,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 0,
    background: 'transparent',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    color: 'var(--color-text-muted)',
    cursor: rest.disabled ? 'not-allowed' : 'pointer',
    opacity: rest.disabled ? 0.5 : 1,
    ...style,
  }

  return (
    <button
      aria-label={label}
      title={label}
      className={className ? `pl-icon-btn ${className}` : 'pl-icon-btn'}
      style={base}
      {...rest}
    >
      {children}
    </button>
  )
}
