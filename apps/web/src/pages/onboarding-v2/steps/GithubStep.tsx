/**
 * Step 1 — connect GitHub (skippable). Wires the `useGithubConnect` hook:
 * `connect.mutate()` sends the browser to the GitHub App install flow, and
 * the install redirect result (?github=connected|error) is surfaced on mount.
 */
import { useGithubConnect } from '../../../features/onboarding-v2'
import { Btn, C, GithubMark, OmadaMark, Spinner, WARM } from '../theme'

const SCOPES: [string, string][] = [
  ['Read your repositories', 'So the roadmap AI can plan around the code you already have'],
  ['See languages & structure', 'To ground milestones in your real stack, not guesses'],
  ['Read-only access', 'Omada never writes to your repos, and you can revoke anytime'],
]

export function GithubStep({ onSkip, skipping, needsReconnect }: { onSkip: () => void; skipping: boolean; needsReconnect: boolean }) {
  const { connect, redirectResult } = useGithubConnect('/onboarding')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>
          {needsReconnect ? 'Reconnect your GitHub' : 'Connect your GitHub'}
        </h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>
          {needsReconnect
            ? 'Your GitHub connection was made before we switched to the more secure GitHub App install flow, and needs to be renewed — or skip it and reconnect later.'
            : 'Connecting GitHub lets the roadmap AI read your repos to plan around what already exists — or skip it and connect later.'}
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, padding: '26px 0', background: WARM.surface, border: `1px solid ${C.border}`, borderRadius: 12 }}>
        <OmadaMark size={46} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {[0, 1, 2].map(i => <span key={i} style={{ width: 5, height: 5, borderRadius: '50%', background: C.borderStrong }} />)}
        </div>
        <GithubMark size={46} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: C.t3, letterSpacing: '.07em', textTransform: 'uppercase', marginBottom: 8 }}>Omada will be able to</div>
        {SCOPES.map(([t, d]) => (
          <div key={t} style={{ display: 'flex', gap: 11, padding: '9px 0', borderBottom: `1px solid ${C.borderSubtle}` }}>
            <div style={{ width: 18, height: 18, borderRadius: '50%', background: C.successBg, border: `1px solid ${C.success}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1 }}>
              <svg width="9" height="9" viewBox="0 0 8 8"><path d="M1 4 L3 6 L7 1" stroke={C.success} strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: C.t1 }}>{t}</div>
              <div style={{ fontSize: 12.5, color: C.t3, lineHeight: 1.4 }}>{d}</div>
            </div>
          </div>
        ))}
      </div>

      {redirectResult?.outcome === 'error' && (
        <div role="alert" style={{ background: C.dangerBg, border: `1px solid ${C.dangerBd}`, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: C.danger }}>
          GitHub connection failed ({redirectResult.reason}). Please try again.
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Btn size="lg" onClick={() => connect.mutate()} disabled={connect.isPending} style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
          {connect.isPending ? <><Spinner size={14} color="rgba(255,255,255,0.85)" /> Redirecting…</> : <>{needsReconnect ? 'Reconnect GitHub →' : 'Connect GitHub →'}</>}
        </Btn>
        <Btn variant="ghost" onClick={onSkip} disabled={skipping}>
          {skipping ? 'Skipping…' : 'Skip for now'}
        </Btn>
      </div>
    </div>
  )
}
