interface WelcomeStepProps {
  onStart: () => void
}

function OmadaMark({ size = 52 }: { size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: size * 0.26,
      background: '#1a1d23', flexShrink: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.5, fontWeight: 800, color: '#fff', letterSpacing: '-1px',
    }}>O</div>
  )
}

function JiraMark({ size = 52 }: { size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: size * 0.26,
      background: 'linear-gradient(160deg, #2684FF, #0052CC)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexShrink: 0, boxShadow: '0 2px 6px rgba(0,82,204,0.3)',
    }}>
      <svg width={size * 0.56} height={size * 0.56} viewBox="0 0 24 24" fill="none">
        <path d="M11.5 2 L20 10.5 a2 2 0 0 1 0 3 L11.5 22 L7 17.5 a2 2 0 0 1 0-3 L11.5 10 L8.5 7 a2 2 0 0 1 0-3 Z" fill="#fff" opacity="0.95" />
      </svg>
    </div>
  )
}

export function WelcomeStep({ onStart }: WelcomeStepProps) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      textAlign: 'center', padding: '40px 32px 36px', gap: 0,
    }}>
      {/* Omada ··· Jira */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, marginBottom: 28 }}>
        <OmadaMark size={52} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {[0, 1, 2].map(i => (
            <span key={i} style={{ width: 5, height: 5, borderRadius: '50%', background: '#c9cfd8', display: 'block' }} />
          ))}
        </div>
        <JiraMark size={52} />
      </div>

      {/* Account created badge */}
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        background: '#e8f5ee', color: '#1f7a4d',
        border: '1px solid #1f7a4d', borderRadius: 20,
        padding: '3px 10px', fontSize: 11, fontWeight: 600, marginBottom: 16,
      }}>
        <svg width="10" height="10" viewBox="0 0 8 8" fill="none">
          <path d="M1 4 L3 6 L7 1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Account created
      </span>

      <h1 style={{
        fontSize: 28, fontWeight: 700, color: '#1a1d23',
        margin: '0 0 12px', letterSpacing: '-0.5px', lineHeight: 1.2,
      }}>
        Import your team from Jira
      </h1>

      <p style={{
        fontSize: 15, color: '#5b6470', lineHeight: 1.65,
        maxWidth: 420, margin: '0 0 36px',
      }}>
        Connect the board your team already works in — Omada pulls in your roster, sprint cadence, and setup automatically. No forms to fill in.
      </p>

      {/* 3-step preview */}
      <div style={{
        display: 'flex', justifyContent: 'center',
        maxWidth: 460, width: '100%', marginBottom: 40,
      }}>
        {[
          { step: '01', title: 'Connect Jira', desc: 'Secure, read-only' },
          { step: '02', title: 'Confirm team', desc: 'Auto-imported roster' },
          { step: '03', title: 'Start tracking', desc: 'Cadence & capacity' },
        ].map((item, i) => (
          <div key={i} style={{
            flex: 1, textAlign: 'center', padding: '0 12px',
            borderRight: i < 2 ? '1px solid #e3e6eb' : 'none',
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#1a1d23', letterSpacing: '0.1em', marginBottom: 4 }}>{item.step}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#1a1d23', marginBottom: 2 }}>{item.title}</div>
            <div style={{ fontSize: 12, color: '#8a93a0' }}>{item.desc}</div>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={onStart}
        style={{
          padding: '12px 28px', fontSize: 15, fontWeight: 600,
          border: 'none', borderRadius: 8,
          background: '#1a1d23', color: '#fff', cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', gap: 8,
          marginBottom: 14, transition: 'opacity 0.12s',
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.opacity = '0.85' }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.opacity = '1' }}
      >
        Connect Jira →
      </button>

      <span style={{ fontSize: 12, color: '#8a93a0' }}>
        Takes about a minute · Read-only access
      </span>
    </div>
  )
}
