import { SelectHTMLAttributes, CSSProperties, ReactNode, useId } from 'react'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode
  helperText?: string
  error?: string
  containerStyle?: CSSProperties
}

export function Select({
  label,
  helperText,
  error,
  containerStyle,
  style,
  id: providedId,
  children,
  ...rest
}: SelectProps) {
  const generatedId = useId()
  const id = providedId ?? generatedId

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, ...containerStyle }}>
      {label && (
        <label
          htmlFor={id}
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-sm)',
            fontWeight: 'var(--font-weight-medium)' as CSSProperties['fontWeight'],
            color: 'var(--color-text-primary)',
          }}
        >
          {label}
        </label>
      )}
      <select
        id={id}
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-sm)',
          color: 'var(--color-text-primary)',
          background: 'var(--color-bg-tertiary)',
          border: `1px solid ${error ? 'var(--color-danger)' : 'var(--color-border)'}`,
          borderRadius: 'var(--radius-md)',
          padding: '5px 28px 5px 10px',
          height: 32,
          outline: 'none',
          width: '100%',
          boxSizing: 'border-box',
          cursor: 'pointer',
          appearance: 'none',
          backgroundImage: `url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%238b949e' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")`,
          backgroundRepeat: 'no-repeat',
          backgroundPosition: 'right 10px center',
          transition: 'border-color 0.12s',
          ...style,
        }}
        {...rest}
      >
        {children}
      </select>
      {(error || helperText) && (
        <span
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-xs)',
            color: error ? 'var(--color-danger)' : 'var(--color-text-muted)',
          }}
        >
          {error ?? helperText}
        </span>
      )}
    </div>
  )
}
