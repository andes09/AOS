import { CSSProperties, ButtonHTMLAttributes, ReactNode } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  children: ReactNode
}

const variantStyles: Record<ButtonVariant, CSSProperties> = {
  primary: {
    background: 'var(--color-accent)',
    color: '#ffffff',
    border: '1px solid transparent',
  },
  secondary: {
    background: 'var(--color-bg-secondary)',
    color: 'var(--color-text-primary)',
    border: '1px solid var(--color-border)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--color-text-secondary)',
    border: '1px solid transparent',
  },
  danger: {
    background: 'var(--color-danger-subtle)',
    color: 'var(--color-danger)',
    border: '1px solid transparent',
  },
}

const sizeStyles: Record<ButtonSize, CSSProperties> = {
  sm: { fontSize: 'var(--text-xs)', padding: '3px 8px', height: 24 },
  md: { fontSize: 'var(--text-sm)', padding: '5px 12px', height: 32 },
  lg: { fontSize: 'var(--text-base)', padding: '7px 16px', height: 40 },
}

export function Button({
  variant = 'secondary',
  size = 'md',
  children,
  style,
  disabled,
  ...rest
}: ButtonProps) {
  const base: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    fontFamily: 'var(--font-sans)',
    fontWeight: 'var(--font-weight-medium)' as CSSProperties['fontWeight'],
    borderRadius: 'var(--radius-md)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    lineHeight: 1,
    whiteSpace: 'nowrap',
    transition: 'background 0.12s, opacity 0.12s',
    textDecoration: 'none',
    ...variantStyles[variant],
    ...sizeStyles[size],
    ...style,
  }

  return (
    <button disabled={disabled} style={base} {...rest}>
      {children}
    </button>
  )
}
