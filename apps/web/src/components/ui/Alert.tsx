import { CSSProperties, ReactNode } from 'react'

export type AlertVariant = 'info' | 'success' | 'warning' | 'danger'

interface AlertProps {
  variant?: AlertVariant
  title?: ReactNode
  children: ReactNode
  style?: CSSProperties
}

const variantStyles: Record<AlertVariant, { border: string; bg: string; titleColor: string; textColor: string }> = {
  info: {
    border: 'var(--color-accent)',
    bg: 'var(--color-accent-subtle)',
    titleColor: 'var(--color-accent)',
    textColor: 'var(--color-text-primary)',
  },
  success: {
    border: 'var(--color-success)',
    bg: 'var(--color-success-bg)',
    titleColor: 'var(--color-success)',
    textColor: 'var(--color-text-primary)',
  },
  warning: {
    border: 'var(--color-warning)',
    bg: 'var(--color-warning-bg)',
    titleColor: 'var(--color-warning)',
    textColor: 'var(--color-text-primary)',
  },
  danger: {
    border: 'var(--color-danger)',
    bg: 'var(--color-danger-subtle)',
    titleColor: 'var(--color-danger)',
    textColor: 'var(--color-text-primary)',
  },
}

export function Alert({ variant = 'info', title, children, style }: AlertProps) {
  const v = variantStyles[variant]
  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: '10px 14px',
        borderRadius: 'var(--radius-md)',
        borderLeft: `3px solid ${v.border}`,
        background: v.bg,
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--text-sm)',
        ...style,
      }}
    >
      {title && (
        <span
          style={{
            fontWeight: 'var(--font-weight-semibold)' as CSSProperties['fontWeight'],
            color: v.titleColor,
          }}
        >
          {title}
        </span>
      )}
      <span style={{ color: v.textColor, lineHeight: 1.5 }}>{children}</span>
    </div>
  )
}
