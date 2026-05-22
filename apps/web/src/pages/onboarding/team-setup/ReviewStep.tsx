import { TeamDraft, MemberDraft } from './types'
import { MemberCard } from './MemberCard'

interface ReviewStepProps {
  team: TeamDraft
  members: MemberDraft[]
  onBack: () => void
  onDone: () => void
  saving: boolean
}

function StatItem({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{
        fontSize: 10,
        fontWeight: 600,
        color: 'var(--color-text-muted)',
        fontFamily: 'var(--font-sans)',
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
      }}>{label}</span>
      <span style={{
        fontSize: 'var(--text-sm)',
        fontWeight: 600,
        color: 'var(--color-text-primary)',
        fontFamily: 'var(--font-sans)',
      }}>{value}</span>
    </div>
  )
}

export function ReviewStep({ team, members, onBack, onDone, saving }: ReviewStepProps) {
  const totalCapacity = members.reduce((sum, m) => sum + m.capacity, 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div>
        <h2 style={{
          fontSize: 'var(--text-xl)',
          fontWeight: 700,
          color: 'var(--color-text-primary)',
          fontFamily: 'var(--font-sans)',
          margin: '0 0 4px',
          letterSpacing: '-0.01em',
        }}>
          Review your team
        </h2>
        <p style={{
          fontSize: 'var(--text-sm)',
          color: 'var(--color-text-muted)',
          fontFamily: 'var(--font-sans)',
          margin: 0,
        }}>
          Confirm everything looks right before connecting Jira.
        </p>
      </div>

      {/* Stats bar */}
      <div style={{
        background: '#f0f2f5',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-lg)',
        padding: '16px 20px',
        display: 'flex',
        flexWrap: 'wrap',
        gap: '16px 28px',
      }}>
        <StatItem label="Team" value={team.name} />
        <StatItem label="Size" value={team.size} />
        <StatItem label="Cadence" value={team.cadence} />
        <StatItem label="Method" value={team.methodology} />
        <StatItem label="Total capacity" value={`${totalCapacity} h/wk`} />
      </div>

      {/* Tech stack chips */}
      {team.techStack.length > 0 && (
        <div>
          <div style={{
            fontSize: 'var(--text-xs)',
            fontWeight: 600,
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            marginBottom: 8,
          }}>Tech stack</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {team.techStack.map(t => (
              <span key={t} style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--color-text-secondary)',
                background: '#ffffff',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: '3px 8px',
                fontFamily: 'var(--font-sans)',
              }}>
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Members */}
      <div>
        <div style={{
          fontSize: 'var(--text-xs)',
          fontWeight: 600,
          color: 'var(--color-text-muted)',
          fontFamily: 'var(--font-sans)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 10,
        }}>
          Members ({members.length})
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {members.map((m, i) => (
            <MemberCard key={i} member={m} index={i} readOnly />
          ))}
        </div>
      </div>

      {/* Privacy note */}
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        background: '#f0f2f5',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
        padding: '10px 12px',
      }}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ marginTop: 1, flexShrink: 0 }}>
          <rect x="2" y="6" width="10" height="7" rx="1.5" stroke="var(--color-text-muted)" strokeWidth="1.2" />
          <path d="M4.5 6V4a2.5 2.5 0 0 1 5 0v2" stroke="var(--color-text-muted)" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <span style={{
          fontSize: 'var(--text-xs)',
          color: 'var(--color-text-secondary)',
          fontFamily: 'var(--font-sans)',
          lineHeight: 1.5,
        }}>
          Privacy by default. Individual velocity data is visible only to each developer.
        </span>
      </div>

      {/* Footer nav */}
      <div style={{ display: 'flex', gap: 10 }}>
        <button
          type="button"
          onClick={onBack}
          disabled={saving}
          style={{
            padding: '8px 14px',
            fontSize: 'var(--text-sm)',
            fontFamily: 'var(--font-sans)',
            fontWeight: 500,
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            background: 'transparent',
            color: 'var(--color-text-secondary)',
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.6 : 1,
          }}
        >
          ← Back
        </button>
        <button
          type="button"
          onClick={onDone}
          disabled={saving}
          style={{
            padding: '8px 20px',
            fontSize: 'var(--text-sm)',
            fontFamily: 'var(--font-sans)',
            fontWeight: 600,
            border: 'none',
            borderRadius: 'var(--radius-md)',
            background: 'var(--color-accent)',
            color: '#ffffff',
            cursor: saving ? 'not-allowed' : 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            opacity: saving ? 0.8 : 1,
            transition: 'opacity 0.12s',
          }}
        >
          {saving && (
            <div style={{
              width: 14,
              height: 14,
              border: '2px solid rgba(255,255,255,0.3)',
              borderTopColor: '#ffffff',
              borderRadius: '50%',
              animation: 'spin 0.7s linear infinite',
              flexShrink: 0,
            }} />
          )}
          {saving ? 'Saving…' : 'Save & Connect Jira →'}
        </button>
      </div>
    </div>
  )
}
