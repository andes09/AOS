import { useState } from 'react'
import './App.css'
import { supabase } from './lib/supabase'

const WAITLIST_COUNT = 2847

const MARQUEE_ITEMS = [
  'AGILE OS', '·', 'SPRINT INTELLIGENCE', '·', 'SCOPE COP', '·',
  'SPRINT BRAIN', '·', 'DEPENDENCY RADAR', '·', 'VELOCITY MIRROR', '·',
  'RETROSPECTIVE AI', '·', 'JIRA INTEGRATION', '·', 'BETA NOW OPEN', '·',
]

const MODULES = [
  {
    num: '01',
    name: 'Scope Cop',
    tag: 'Ticket Quality Enforcer',
    phase: 'Before Sprint Planning',
    desc: 'Every ticket analysed before planning begins. Flags vague requirements, estimation mismatches, and scope that historically causes overruns. Bad tickets stopped before they ruin a sprint.',
  },
  {
    num: '02',
    name: 'Sprint Brain',
    tag: 'Sprint Planner',
    phase: 'Sprint Planning',
    desc: "Builds sprint plans matched to each developer's actual delivery history — not team averages. Recommends assignments with evidence. Shows you exactly why a sprint will succeed or fail before it starts.",
  },
  {
    num: '03',
    name: 'Dependency Radar',
    tag: 'Supplier & Dependency Tracker',
    phase: 'Pre-Sprint & Planning',
    desc: 'Every external dependency tracked with a reliability score. Surfaces the risk at planning time: "This supplier delivered on time 2 of the last 6 sprints. Your plan has 40% of capacity blocked on them."',
  },
  {
    num: '04',
    name: 'Velocity Mirror',
    tag: 'Live Sprint Dashboard',
    phase: 'During Execution',
    desc: "Sprint failures become visible days before they're inevitable. Real-time monitoring catches stalled tickets, over-capacity developers, and blocked dependencies — with recommended interventions ranked by impact.",
  },
  {
    num: '05',
    name: 'Retrospective AI',
    tag: 'Sprint Learning Engine',
    phase: 'After Every Sprint',
    desc: 'Automated retrospective reports generated at sprint close — no manual effort. Identifies patterns across sprints. Tracks action items. Closes the loop between identified problem and verified fix.',
  },
]

const LOOP_STEPS = [
  { step: '01', event: 'Ticket Created',   module: 'Scope Cop',                    desc: 'Quality enforced at the source' },
  { step: '02', event: 'Sprint Planning',  module: 'Sprint Brain + Dependency Radar', desc: 'Plans built on evidence, not optimism' },
  { step: '03', event: 'Sprint Execution', module: 'Velocity Mirror',               desc: "Failures caught before they're inevitable" },
  { step: '04', event: 'Sprint Close',     module: 'Retrospective AI',              desc: 'Learnings captured and tracked automatically' },
  { step: '05', event: 'Next Sprint',      module: 'System gets smarter',           desc: 'Historical data compounds into intelligence' },
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
          <span className="nav-logo">AOS</span>
          <span className="nav-divider" aria-hidden="true" />
          <span className="nav-full-name">Agile OS</span>
        </div>
        <div className="nav-links">
          <a href="#modules" className="nav-link">Features</a>
          <a href="#waitlist" className="nav-cta">Request Access</a>
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
            <h1 className="hero-title animate-2" aria-label="Agile OS">AOS</h1>
            <p className="hero-tagline animate-3">The Operating System for Engineering Teams</p>
            <p className="hero-sub animate-4">
              The planning and intelligence platform that helps engineering teams<br />
              <em>stop repeating the same sprint failures.</em>
            </p>
            <div className="hero-actions animate-5">
              <a href="#waitlist" className="btn-primary">
                <span>Request Early Access</span>
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
              Your tools record what happened.<br />
              <em>None of them learn from it.</em>
            </h2>
            <p className="problem-body">
              Jira, Linear, GitHub Projects — they track tickets and sprint state. They do not connect
              planning to execution to retrospective in a way that generates improvement over time.
              Teams fail predictably, for the same reasons, sprint after sprint.
            </p>
            <p className="problem-body">
              Agile OS is the intelligence layer that sits across every stage of the sprint lifecycle —
              continuously learning from a team's patterns and making the next sprint smarter than the last.
            </p>
            <div className="problem-callout">
              <p>The longer a team uses it, the smarter it becomes.</p>
            </div>
          </div>
        </section>

        {/* The Loop */}
        <section className="loop-section" aria-labelledby="loop-heading">
          <div className="section-label" id="loop-heading">
            <span className="label-line" aria-hidden="true" />
            <span>The closed loop</span>
            <span className="label-line" aria-hidden="true" />
          </div>
          <div className="loop-track">
            {LOOP_STEPS.map((s, i) => (
              <div key={s.step} className="loop-step">
                <div className="loop-step-inner">
                  <span className="loop-num">{s.step}</span>
                  <div className="loop-content">
                    <span className="loop-event">{s.event}</span>
                    <span className="loop-module">{s.module}</span>
                    <span className="loop-desc">{s.desc}</span>
                  </div>
                </div>
                {i < LOOP_STEPS.length - 1 && (
                  <span className="loop-arrow" aria-hidden="true">
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
                      <path d="M4 10h12M12 5l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </span>
                )}
                {i === LOOP_STEPS.length - 1 && (
                  <span className="loop-cycle" aria-hidden="true">↺</span>
                )}
              </div>
            ))}
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
                  <span className="module-tag">{m.tag}</span>
                </div>
                <p className="module-desc">{m.desc}</p>
              </article>
            ))}
          </div>
        </section>

        {/* Integrations callout */}
        <section className="integrations-section" aria-label="Integrations">
          <div className="integrations-inner">
            <p className="integrations-label">Works on top of your existing stack</p>
            <div className="integrations-list">
              {['Jira', 'Linear', 'GitHub Projects'].map((tool) => (
                <span key={tool} className="integration-chip">{tool}</span>
              ))}
            </div>
            <p className="integrations-note">
              No migration required. Agile OS reads and writes to your existing tools — it doesn't replace them.
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
                We're onboarding beta teams now. Join the waitlist to get early access,
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
                  <p className="form-header">Get early access to Agile OS</p>
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
                        <span>Join the Waitlist</span>
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
          <span className="footer-logo">AOS</span>
          <span className="footer-tagline">Agile OS — The Operating System for Engineering Teams</span>
        </div>
        <p className="footer-copy">© {new Date().getFullYear()} Agile OS. All rights reserved.</p>
      </footer>
    </>
  )
}

export default App
