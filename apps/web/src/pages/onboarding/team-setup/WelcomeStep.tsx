interface WelcomeStepProps {
  onStart: () => void
}

export function WelcomeStep({ onStart }: WelcomeStepProps) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      textAlign: 'center',
      padding: '48px 32px 40px',
      gap: 0,
    }}>
      {/* Logo */}
      <div style={{
        width: 56,
        height: 56,
        borderRadius: 14,
        background: '#1a1d23',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 20,
        flexShrink: 0,
      }}>
        <span style={{
          color: '#ffffff',
          fontFamily: 'var(--font-sans)',
          fontWeight: 800,
          fontSize: 24,
          letterSpacing: '-0.02em',
        }}>O</span>
      </div>

      {/* Account created badge */}
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        background: '#e8f5ee',
        color: 'var(--color-success)',
        border: '1px solid #b7dfcb',
        borderRadius: 20,
        padding: '3px 10px',
        fontSize: 'var(--text-xs)',
        fontFamily: 'var(--font-sans)',
        fontWeight: 600,
        marginBottom: 20,
      }}>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M2 6L5 9L10 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Account created
      </span>

      {/* H1 */}
      <h1 style={{
        fontSize: 28,
        fontWeight: 800,
        color: 'var(--color-text-primary)',
        fontFamily: 'var(--font-sans)',
        margin: '0 0 12px',
        letterSpacing: '-0.02em',
        lineHeight: 1.2,
      }}>
        Let&rsquo;s set up your team
      </h1>

      {/* Subtitle */}
      <p style={{
        fontSize: 'var(--text-base)',
        color: 'var(--color-text-secondary)',
        fontFamily: 'var(--font-sans)',
        margin: '0 0 32px',
        lineHeight: 1.6,
        maxWidth: 400,
      }}>
        Before connecting Jira, tell us about your team. This powers Sprint Brain&rsquo;s assignment and capacity recommendations.
      </p>

      {/* Step preview */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr auto 1fr auto 1fr',
        gap: 0,
        width: '100%',
        maxWidth: 480,
        marginBottom: 36,
      }}>
        {[
          { num: '01', label: 'Team profile', desc: 'Name, size & workflow' },
          null,
          { num: '02', label: 'Member profiles', desc: 'Roles & strengths' },
          null,
          { num: '03', label: 'Connect Jira', desc: 'Board & history' },
        ].map((item, i) => {
          if (item === null) {
            return (
              <div key={i} style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                <div style={{ width: 1, height: 40, background: 'var(--color-border)' }} />
              </div>
            )
          }
          return (
            <div key={i} style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 4,
              padding: '0 8px',
            }}>
              <span style={{
                fontSize: 11,
                fontWeight: 700,
                color: 'var(--color-accent)',
                fontFamily: 'var(--font-sans)',
                letterSpacing: '0.04em',
              }}>{item.num}</span>
              <span style={{
                fontSize: 'var(--text-sm)',
                fontWeight: 600,
                color: 'var(--color-text-primary)',
                fontFamily: 'var(--font-sans)',
              }}>{item.label}</span>
              <span style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--color-text-muted)',
                fontFamily: 'var(--font-sans)',
              }}>{item.desc}</span>
            </div>
          )
        })}
      </div>

      {/* CTA */}
      <button
        type="button"
        onClick={onStart}
        style={{
          padding: '12px 28px',
          fontSize: 'var(--text-base)',
          fontFamily: 'var(--font-sans)',
          fontWeight: 600,
          border: 'none',
          borderRadius: 'var(--radius-md)',
          background: 'var(--color-accent)',
          color: '#ffffff',
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          marginBottom: 14,
          transition: 'opacity 0.12s',
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.opacity = '0.9' }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.opacity = '1' }}
      >
        Set up your team
        <span style={{ fontSize: 16 }}>→</span>
      </button>

      <span style={{
        fontSize: 'var(--text-xs)',
        color: 'var(--color-text-muted)',
        fontFamily: 'var(--font-sans)',
      }}>
        Takes about 3 minutes
      </span>
    </div>
  )
}
