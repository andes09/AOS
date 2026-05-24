import { useState } from 'react'
import './App.css'
import { supabase } from './lib/supabase'

const WAITLIST_COUNT = 2847

const MARQUEE_ITEMS = [
  'OMADA', '·', 'SPRINT INTELLIGENCE', '·', 'SCOPE CHECK', '·',
  'SPRINT PLANNING', '·', 'DEPENDENCY RADAR', '·', 'SPRINT PULSE', '·',
  'RETRO PREP', '·', 'JIRA INTEGRATION', '·', 'BETA NOW OPEN', '·',
]

const PROBLEMS = [
  {
    title: 'The sprint that slips, slips the next one too',
    body: 'One blown sprint cascades into the next. Tickets roll over. Commitments miss. The team learns nothing from it.',
  },
  {
    title: 'Retros that never change anything',
    body: '60 retros in, the same problems keep surfacing. Action items get written down and forgotten. The same sprint failure happens again next month.',
  },
  {
    title: 'Dependencies that break silently',
    body: "Jira links are just labels. You don't know a supplier's unreliable until 40% of your sprint is blocked on them. Again.",
  },
]

const PROOF_STATS = [
  {
    num: '+5%',
    label: 'sprint completion on small teams',
    context: 'Omada-planned sprints vs the rule-based planning baseline',
  },
  {
    num: '100%',
    label: 'plan-to-Jira integrity',
    context: 'Plans that pushed end-to-end without a hand-fix. Rules-only baseline: 0%.',
  },
  {
    num: '0 → 18%',
    label: 'recovery on struggling teams',
    context: 'Where rule-based planning stalled at zero completion, Omada moved the team forward.',
  },
]

const MODULES = [
  {
    num: '01',
    name: 'Sprint Planning',
    phase: 'Before Sprint Starts',
    outcome: "Plans based on your team's actual delivery history, not averages.",
    detail: "Each developer's effective capacity accounts for meetings, PTO, and past performance on similar tickets.",
  },
  {
    num: '02',
    name: 'Scope Check',
    phase: 'Before Sprint Planning',
    outcome: 'Surfaces vague or oversized tickets before they become sprint risks.',
    detail: 'Flags ambiguous acceptance criteria and tickets likely to exceed their estimate based on historical patterns.',
  },
  {
    num: '03',
    name: 'Dependency Radar',
    phase: 'Pre-Sprint & Planning',
    outcome: 'Tracks which dependencies are actually reliable.',
    detail: "This supplier has delivered on time 2 of the last 6 sprints. You've planned 40% of capacity around them.",
  },
  {
    num: '04',
    name: 'Sprint Pulse',
    phase: 'During Execution',
    outcome: "Real-time sprint health — know you're going to miss on day 3, not day 13.",
    detail: 'Live burndown prediction, stalled ticket alerts, and capacity warnings throughout the sprint.',
  },
  {
    num: '05',
    name: 'Retro Prep',
    phase: 'After Every Sprint',
    outcome: 'Gives your team the data to run a better retrospective conversation.',
    detail: 'Sprint summary, pattern detection across sprints, and action item tracking. Your team runs the retro — Omada prepares them for it.',
  },
]

const NOT_POINTS = [
  {
    title: 'Not an AI scrum master.',
    body: 'Omada is a data layer. Your humans still run the ceremonies.',
  },
  {
    title: 'Not a replacement for Jira.',
    body: 'Omada connects on top. No migration, no admin burden, no plugin stacking.',
  },
  {
    title: 'Not surveillance.',
    body: 'Individual velocity data is private to each developer by default. Leads see team-level trends, not performance reviews.',
  },
]

const INTEGRATIONS = [
  { name: 'Jira', soon: false },
  { name: 'Slack', soon: false },
  { name: 'Google Calendar', soon: false },
  { name: 'Microsoft Teams', soon: false },
  { name: 'Linear', soon: true },
  { name: 'GitHub', soon: true },
]


const ArrowIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

function App() {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setErrorMsg('Please enter a valid email address.')
      setStatus('error')
      return
    }
    setStatus('loading')
    try {
const { error } = await supabase
        .from('waitlist')
        .insert({ email: email.toLowerCase().trim() })
      if (error) throw error
      setStatus('success')
      // Fire-and-forget confirmation email — failure doesn't affect signup
      supabase.functions.invoke('waitlist-signup', { body: { email } }).catch(() => {})
    } catch (err) {
      const msg = err?.message ?? ''
      const code = err?.code ?? ''
      if (msg.includes('duplicate') || msg.includes('already') || code === '23505') {
        setStatus('success')
      } else {
        setErrorMsg('Something went wrong. Please try again.')
        setStatus('error')
      }
    }
  }

  return (
    <>
      {/* Grain texture overlay */}
      <svg className="grain-overlay" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
        <filter id="grain-filter">
          <feTurbulence type="fractalNoise" baseFrequency="0.72" numOctaves="4" stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain-filter)" />
      </svg>

      <div className="bg-glow" aria-hidden="true" />

      {/* Navigation */}
      <nav className="nav" role="navigation" aria-label="Main navigation">
        <div className="nav-brand">
          <span
            className="nav-logo"
            style={{
              fontFamily: '"DM Sans", sans-serif',
              fontWeight: 600,
              fontSize: 20,
              letterSpacing: '-0.02em',
            }}
          >
            Omada
          </span>
        </div>
        <div className="nav-links">
          <a href="#modules" className="nav-link">Features</a>
          <a href="#waitlist" className="nav-cta">Join the Beta</a>
        </div>
      </nav>

      <main>
        {/* Hero */}
        <section className="hero">
          <div className="hero-content">
            <div className="hero-badge animate-1">
              <span className="hero-badge-dot" aria-hidden="true" />
              <span>Now in Beta — Limited Access</span>
            </div>
            <h1
              className="hero-title animate-2"
              style={{
                fontFamily: '"DM Sans", sans-serif',
                fontWeight: 500,
                fontSize: 'clamp(2.5rem, 6vw, 4.5rem)',
                lineHeight: 1.1,
                letterSpacing: '-0.02em',
                maxWidth: '18ch',
              }}
            >
              Your sprint tools record what happened. <em style={{ fontStyle: 'italic' }}>Omada learns from it.</em>
            </h1>
            <p className="hero-sub animate-4">
              Sprint planning intelligence that connects to your existing Jira.<br />
              No migration. No plugin stack. Works on top of what you already use.
            </p>
            <div className="hero-actions animate-5">
              <a href="#waitlist" className="btn-primary">
                <span>Join the Beta</span>
                <ArrowIcon />
              </a>
              <a href="#modules" className="btn-ghost">
                <span>See how it works</span>
              </a>
            </div>
          </div>
          <div className="hero-scroll" aria-hidden="true">
            <span className="scroll-line" />
            <span>scroll</span>
          </div>
        </section>

        {/* Marquee */}
        <div className="marquee-strip" aria-hidden="true">
          <div className="marquee-track">
            {[...MARQUEE_ITEMS, ...MARQUEE_ITEMS].map((item, i) => (
              <span key={i} className={item === '·' ? 'marquee-sep' : 'marquee-word'}>
                {item}
              </span>
            ))}
          </div>
        </div>

        {/* Problem */}
        <section className="problem-section">
          <div className="problem-inner">
            <div className="section-label left">
              <span className="label-line" aria-hidden="true" />
              <span>The problem</span>
            </div>
            <h2 className="problem-title">
              Sprint tools record what happened.<br />
              <em>None of them learn from it.</em>
            </h2>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                gap: 1,
                background: 'var(--border)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                overflow: 'hidden',
                marginTop: '2.5rem',
              }}
            >
              {PROBLEMS.map((p) => (
                <article
                  key={p.title}
                  style={{
                    background: 'var(--bg-card)',
                    padding: '2rem 1.75rem',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.85rem',
                  }}
                >
                  <h3
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: '1.35rem',
                      fontWeight: 500,
                      lineHeight: 1.25,
                      letterSpacing: '0.005em',
                      margin: 0,
                      color: 'var(--text-primary)',
                    }}
                  >
                    {p.title}
                  </h3>
                  <p
                    style={{
                      fontSize: '0.92rem',
                      color: 'var(--text-secondary)',
                      lineHeight: 1.7,
                      margin: 0,
                    }}
                  >
                    {p.body}
                  </p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* Proof — simulation evidence */}
        <section className="proof-section" aria-labelledby="proof-heading">
          <div className="proof-inner">
            <div className="section-label left">
              <span className="label-line" aria-hidden="true" />
              <span>Evidence</span>
            </div>
            <h2 className="proof-title" id="proof-heading">
              Tested across 60 simulated sprints.<br />
              Built to work <em>alongside your team.</em>
            </h2>
            <p className="proof-intro">
              We put Omada's Sprint Brain head-to-head against rule-based planning baselines
              across five team archetypes. The result: planning that matches expert-led rigor
              on healthy teams, recovers struggling ones, and — for the first time — produces
              sprint plans that actually integrate end-to-end with the tools you already use.
            </p>

            <div className="proof-stats-grid">
              {PROOF_STATS.map((s) => (
                <article key={s.label} className="proof-stat-card">
                  <span className="proof-stat-num">{s.num}</span>
                  <span className="proof-stat-label">{s.label}</span>
                  <span className="proof-stat-context">{s.context}</span>
                </article>
              ))}
            </div>

            <p className="proof-closer">
              Your scrum master runs the conversation.<br />
              <strong>Omada runs the math.</strong> Same partnership, sharper signals.
            </p>
          </div>
        </section>

        {/* Modules */}
        <section className="modules-section" id="modules" aria-labelledby="modules-heading">
          <div className="modules-header">
            <div className="section-label" id="modules-heading">
              <span className="label-line" aria-hidden="true" />
              <span>Five modules. One system.</span>
              <span className="label-line" aria-hidden="true" />
            </div>
            <p className="modules-intro">
              Each module addresses one stage of the sprint lifecycle.
              Together, they form a closed system where every sprint makes the next one smarter.
            </p>
          </div>
          <div className="modules-grid">
            {MODULES.map((m) => (
              <article key={m.num} className="module-card">
                <div className="module-card-top">
                  <span className="module-num">{m.num}</span>
                  <span className="module-phase">{m.phase}</span>
                </div>
                <div className="module-header-row">
                  <h3 className="module-name">{m.name}</h3>
                </div>
                <p className="module-desc">{m.outcome}</p>
                <p
                  style={{
                    fontSize: '0.82rem',
                    color: 'var(--text-muted)',
                    lineHeight: 1.7,
                    margin: 0,
                    paddingTop: '0.5rem',
                    borderTop: '1px solid var(--border)',
                    fontStyle: 'italic',
                  }}
                >
                  {m.detail}
                </p>
              </article>
            ))}
          </div>
        </section>

        {/* Positioning — "What Omada is not" */}
        <section
          style={{
            padding: '7rem 2rem',
            borderBottom: '1px solid var(--border)',
          }}
          aria-labelledby="positioning-heading"
        >
          <div style={{ maxWidth: 'var(--max-w)', margin: '0 auto' }}>
            <div className="section-label left">
              <span className="label-line" aria-hidden="true" />
              <span>Positioning</span>
            </div>
            <h2
              id="positioning-heading"
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(2rem, 4.5vw, 3.25rem)',
                fontWeight: 400,
                letterSpacing: '-0.01em',
                lineHeight: 1.12,
                margin: '1.25rem 0 2.5rem',
                maxWidth: '20ch',
                color: 'var(--text-primary)',
              }}
            >
              What Omada <em style={{ fontStyle: 'italic' }}>is not.</em>
            </h2>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                gap: '1.5rem',
              }}
            >
              {NOT_POINTS.map((n) => (
                <div
                  key={n.title}
                  style={{
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    padding: '1.75rem 1.5rem',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.6rem',
                  }}
                >
                  <h3
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: '1.15rem',
                      fontWeight: 500,
                      margin: 0,
                      color: 'var(--text-primary)',
                      lineHeight: 1.3,
                    }}
                  >
                    {n.title}
                  </h3>
                  <p
                    style={{
                      fontSize: '0.9rem',
                      color: 'var(--text-secondary)',
                      lineHeight: 1.7,
                      margin: 0,
                    }}
                  >
                    {n.body}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Integrations callout */}
        <section className="integrations-section" aria-label="Integrations">
          <div className="integrations-inner">
            <p className="integrations-label">Connects to the tools you already use</p>
            <div className="integrations-list">
              {INTEGRATIONS.map((tool) => (
                <span
                  key={tool.name}
                  className="integration-chip"
                  style={tool.soon ? { opacity: 0.65 } : undefined}
                >
                  {tool.name}
                  {tool.soon && (
                    <span
                      style={{
                        marginLeft: 6,
                        fontSize: '0.62rem',
                        fontWeight: 700,
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        color: 'var(--gold)',
                      }}
                    >
                      Coming soon
                    </span>
                  )}
                </span>
              ))}
            </div>
            <p className="integrations-note">
              No migration required. Omada reads and writes to your existing tools — it doesn't replace them.
            </p>
          </div>
        </section>

        {/* Waitlist */}
        <section className="waitlist" id="waitlist" aria-labelledby="waitlist-heading">
          <div className="waitlist-inner">
            <div className="waitlist-text">
              <div className="section-label left">
                <span className="label-line" aria-hidden="true" />
                <span>Early access</span>
              </div>
              <h2 className="waitlist-title" id="waitlist-heading">
                Stop losing sprints<br />
                <em>you could have won.</em>
              </h2>
              <p className="waitlist-desc">
                We're onboarding beta teams now. Join the beta to get early access,
                shape the product, and see your sprint spillover drop within 3 months.
              </p>
              <p className="waitlist-count">
                <span className="count-num">{WAITLIST_COUNT.toLocaleString()}</span>
                <span className="count-label">engineering teams already waiting</span>
              </p>
            </div>

            <div className="waitlist-form-wrap">
              {status === 'success' ? (
                <div className="success-state" role="status">
                  <div className="success-icon" aria-hidden="true">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                      <path d="M5 13l4 4L19 7" stroke="var(--gold)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <h3 className="success-title">You're on the list.</h3>
                  <p className="success-text">We'll be in touch when beta opens. Watch your inbox.</p>
                </div>
              ) : (
                <form className="waitlist-form" onSubmit={handleSubmit} noValidate>
                  <p className="form-header">Get early access to Omada</p>
                  <div className="form-field">
                    <label htmlFor="email-input" className="form-label">Work email</label>
                    <input
                      id="email-input"
                      type="email"
                      className={`form-input${status === 'error' ? ' input-error' : ''}`}
                      placeholder="you@company.com"
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value)
                        if (status === 'error') { setStatus('idle'); setErrorMsg('') }
                      }}
                      autoComplete="email"
                    />
                    {status === 'error' && <p className="error-msg" role="alert">{errorMsg}</p>}
                  </div>
                  <button type="submit" className="btn-submit" disabled={status === 'loading'}>
                    {status === 'loading' ? (
                      <span className="spinner" aria-label="Submitting…" />
                    ) : (
                      <>
                        <span>Join the Beta</span>
                        <ArrowIcon />
                      </>
                    )}
                  </button>
                  <p className="form-note">For engineering teams of 5–50 developers. No spam, ever.</p>
                </form>
              )}
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="footer">
        <div className="footer-brand">
          <span
            className="footer-logo"
            style={{
              fontFamily: '"DM Sans", sans-serif',
              fontWeight: 600,
              fontSize: 18,
              letterSpacing: '-0.02em',
            }}
          >
            Omada
          </span>
          <span className="footer-tagline">Sprint intelligence that learns from every sprint</span>
        </div>
        <p className="footer-copy">© {new Date().getFullYear()} Omada. All rights reserved.</p>
      </footer>
    </>
  )
}

export default App
