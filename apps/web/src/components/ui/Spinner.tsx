import { CSSProperties } from 'react'

interface SpinnerProps {
  size?: number
  color?: string
  style?: CSSProperties
}

const keyframes = `
@keyframes aos-spin {
  to { transform: rotate(360deg); }
}
`

let injected = false
function injectKeyframes() {
  if (injected || typeof document === 'undefined') return
  const style = document.createElement('style')
  style.textContent = keyframes
  document.head.appendChild(style)
  injected = true
}

export function Spinner({ size = 16, color, style }: SpinnerProps) {
  injectKeyframes()
  return (
    <span
      role="status"
      aria-label="Loading"
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        border: `2px solid var(--color-border)`,
        borderTopColor: color ?? 'var(--color-accent)',
        borderRadius: '50%',
        animation: 'aos-spin 0.65s linear infinite',
        flexShrink: 0,
        ...style,
      }}
    />
  )
}
