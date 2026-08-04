/**
 * Shared design tokens + presentational atoms for the onboarding v2 UI.
 *
 * Values are ported verbatim from the legacy OnboardingPage.tsx so the two
 * flows read as the same product. This module is purely presentational — it
 * never touches the onboarding hooks or the network. Step components compose
 * these atoms and wire them to the headless layer in `features/onboarding-v2`.
 */
import type React from 'react'

// ─── Design tokens ────────────────────────────────────────────────────────────
export const C = {
  bg0:          '#ffffff',
  bg1:          '#f7f8fa',
  bg2:          '#ffffff',
  bg3:          '#f0f2f5',
  accent:       '#1a1d23',
  accentSubtle: '#eef0f3',
  accentBorder: '#1a1d23',
  border:       '#e3e6eb',
  borderStrong: '#c9cfd8',
  borderSubtle: '#edeff3',
  t1: '#1a1d23',
  t2: '#5b6470',
  t3: '#8a93a0',
  success:   '#1f7a4d',
  successBg: '#e8f5ee',
  danger:    '#dc2626',
  dangerBg:  '#fef2f2',
  dangerBd:  '#fca5a5',
}

export const WARM = {
  surface:  '#fcfbf9',
  accent:   'oklch(0.56 0.11 45)',
  accentBg: 'oklch(0.96 0.032 62)',
  accentBd: 'oklch(0.89 0.055 58)',
}

// ─── Buttons ──────────────────────────────────────────────────────────────────
export function Btn({
  children,
  variant = 'primary',
  size = 'md',
  type = 'button',
  onClick,
  disabled,
  style,
}: {
  children: React.ReactNode
  variant?: 'primary' | 'secondary' | 'ghost' | 'outline'
  size?: 'sm' | 'md' | 'lg'
  type?: 'button' | 'submit'
  onClick?: () => void
  disabled?: boolean
  style?: React.CSSProperties
}) {
  const varMap = {
    primary:   { background: C.accent, color: '#fff', border: 'none' },
    secondary: { background: C.bg2, color: C.t1, border: `1px solid ${C.border}` },
    ghost:     { background: 'transparent', color: C.t2, border: 'none' },
    outline:   { background: 'transparent', color: C.accent, border: `1px solid ${C.accent}` },
  }
  const sizeMap = {
    sm: { fontSize: 12, padding: '5px 12px' },
    md: { fontSize: 13, padding: '7px 16px' },
    lg: { fontSize: 15, padding: '11px 26px' },
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        borderRadius: 6, fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1, transition: 'opacity 0.12s, background 0.12s',
        ...varMap[variant], ...sizeMap[size], ...style,
      }}
    >
      {children}
    </button>
  )
}

// ─── Field label ──────────────────────────────────────────────────────────────
export function FieldLabel({ children, note }: { children: React.ReactNode; note?: string }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 600, color: C.t3, letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
      {children}
      {note && <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: C.t3 }}>{note}</span>}
    </div>
  )
}

// ─── Spinner ──────────────────────────────────────────────────────────────────
export function Spinner({ size = 16, color = C.accent }: { size?: number; color?: string }) {
  return (
    <span
      style={{
        width: size, height: size, flexShrink: 0, display: 'inline-block',
        border: `2px solid ${color}`, borderTopColor: 'transparent', borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
      }}
    />
  )
}

// ─── ProgressBar ──────────────────────────────────────────────────────────────
export function ProgressBar({ progress }: { progress: number }) {
  return (
    <div style={{ width: '100%', height: 4, borderRadius: 2, background: C.bg3, overflow: 'hidden' }}>
      <div
        style={{
          width: `${progress}%`, height: '100%', background: C.accent, borderRadius: 2,
          transition: 'width 0.4s ease',
        }}
      />
    </div>
  )
}

// ─── Alert ────────────────────────────────────────────────────────────────────
export function Alert({ children }: { children: React.ReactNode }) {
  return (
    <div role="alert" style={{ background: C.dangerBg, border: `1px solid ${C.dangerBd}`, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: C.danger }}>
      {children}
    </div>
  )
}

// ─── Brand marks ──────────────────────────────────────────────────────────────
export function OmadaMark({ size = 34 }: { size?: number }) {
  return (
    <div style={{ width: size, height: size, borderRadius: size * 0.26, background: C.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: size * 0.5, fontWeight: 800, color: '#fff', letterSpacing: '-1px' }}>O</div>
  )
}

export function GithubMark({ size = 34 }: { size?: number }) {
  return (
    <div style={{ width: size, height: size, borderRadius: size * 0.26, background: 'linear-gradient(160deg, #3a3f47, #1a1d23)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 2px 6px rgba(26,29,35,0.28)' }}>
      <svg width={size * 0.6} height={size * 0.6} viewBox="0 0 24 24" fill="#fff" aria-hidden="true">
        <path d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.1.68-.22.68-.49 0-.24-.01-.87-.01-1.71-2.78.62-3.37-1.37-3.37-1.37-.45-1.18-1.11-1.5-1.11-1.5-.91-.63.07-.62.07-.62 1 .07 1.53 1.06 1.53 1.06.9 1.56 2.36 1.11 2.93.85.09-.66.35-1.11.63-1.37-2.22-.26-4.55-1.14-4.55-5.06 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.28 2.75 1.05a9.36 9.36 0 0 1 5 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.93-2.34 4.79-4.57 5.05.36.32.68.94.68 1.9 0 1.37-.01 2.48-.01 2.82 0 .27.18.6.69.49A10.02 10.02 0 0 0 22 12.25C22 6.58 17.52 2 12 2Z" />
      </svg>
    </div>
  )
}
