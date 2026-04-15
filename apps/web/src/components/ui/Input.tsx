import { InputHTMLAttributes, CSSProperties, ReactNode, useId } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode
  helperText?: string
  error?: string
  containerStyle?: CSSProperties
}

export function Input({
  label,
  helperText,
  error,
  containerStyle,
  style,
  id: providedId,
  ...rest
}: InputProps) {
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
      <input
        id={id}
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-sm)',
          color: 'var(--color-text-primary)',
          background: 'var(--color-bg-tertiary)',
          border: `1px solid ${error ? 'var(--color-danger)' : 'var(--color-border)'}`,
          borderRadius: 'var(--radius-md)',
          padding: '5px 10px',
          height: 32,
          outline: 'none',
          width: '100%',
          boxSizing: 'border-box',
          transition: 'border-color 0.12s, box-shadow 0.12s',
          ...style,
        }}
        onFocus={e => {
          e.currentTarget.style.borderColor = error ? 'var(--color-danger)' : 'var(--color-accent)'
          e.currentTarget.style.boxShadow = error
            ? '0 0 0 2px var(--color-danger-subtle)'
            : '0 0 0 2px var(--color-accent-subtle)'
        }}
        onBlur={e => {
          e.currentTarget.style.borderColor = error ? 'var(--color-danger)' : 'var(--color-border)'
          e.currentTarget.style.boxShadow = 'none'
        }}
        {...rest}
      />
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
