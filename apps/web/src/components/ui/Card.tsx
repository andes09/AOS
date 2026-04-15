import { CSSProperties, ReactNode, HTMLAttributes } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  style?: CSSProperties
}

export function Card({ children, style, ...rest }: CardProps) {
  return (
    <div
      style={{
        background: 'var(--color-bg-elevated)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-sm)',
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  )
}

interface CardHeaderProps {
  children: ReactNode
  style?: CSSProperties
}

export function CardHeader({ children, style }: CardHeaderProps) {
  return (
    <div
      style={{
        padding: '12px 16px',
        borderBottom: '1px solid var(--color-border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

interface CardBodyProps {
  children: ReactNode
  style?: CSSProperties
}

export function CardBody({ children, style }: CardBodyProps) {
  return (
    <div style={{ padding: '12px 16px', ...style }}>
      {children}
    </div>
  )
}
