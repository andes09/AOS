import { CSSProperties, ReactNode } from 'react'

export type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info'

interface BadgeProps {
  variant?: BadgeVariant
  children: ReactNode
  style?: CSSProperties
}

const variantStyles: Record<BadgeVariant, CSSProperties> = {
  default: {
    background: 'var(--color-bg-tertiary)',
    color: 'var(--color-text-secondary)',
    border: '1px solid var(--color-border)',
  },
  success: {
    background: 'var(--color-success-bg)',
    color: 'var(--color-success)',
    border: '1px solid transparent',
  },
  warning: {
    background: 'var(--color-warning-bg)',
    color: 'var(--color-warning)',
    border: '1px solid transparent',
  },
  danger: {
    background: 'var(--color-danger-subtle)',
    color: 'var(--color-danger)',
    border: '1px solid transparent',
  },
  info: {
    background: 'var(--color-accent-subtle)',
    color: 'var(--color-accent)',
    border: '1px solid transparent',
  },
}

export function Badge({ variant = 'default', children, style }: BadgeProps) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--text-xs)',
        fontWeight: 'var(--font-weight-medium)' as CSSProperties['fontWeight'],
        lineHeight: 1,
        padding: '2px 7px',
        borderRadius: 9999,
        whiteSpace: 'nowrap',
        ...variantStyles[variant],
        ...style,
      }}
    >
      {children}
    </span>
  )
}
