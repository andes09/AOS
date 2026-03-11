// apps/web/src/layouts/OnboardingLayout.tsx

interface OnboardingLayoutProps {
  children: React.ReactNode
}

export function OnboardingLayout({ children }: OnboardingLayoutProps) {
  return (
    <div style={{
      minHeight: '100vh',
      background: '#0f1117',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '1.5rem',
      fontFamily: 'system-ui, sans-serif',
    }}>
      <div style={{
        width: '100%',
        maxWidth: 480,
        background: '#1e2030',
        borderRadius: 12,
        padding: '2rem',
        border: '1px solid #6366f1',
      }}>
        {children}
      </div>
    </div>
  )
}
