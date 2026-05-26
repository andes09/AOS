import { useState, useEffect, Fragment } from 'react'
import './App.css'
import { supabase } from './lib/supabase'

// ─── Tokens ───────────────────────────────────────────────────────────────────
const C = {
  bg:        '#ffffff',
  bgSubtle:  '#f7f8fa',
  bgMuted:   '#f0f2f5',
  ink:       '#1a1d23',
  inkSoft:   '#2a2f37',
  t1:        '#1a1d23',
  t2:        '#5b6470',
  t3:        '#8a93a0',
  border:    '#e3e6eb',
  borderS:   '#edeff3',
  success:   '#1f7a4d',
  successBg: '#e8f5ee',
  warn:      '#9a5a06',
  warnBg:    '#fdf2dc',
}

const MAXW = 1180

// ─── Atoms ────────────────────────────────────────────────────────────────────
function Btn({ children, variant = 'primary', size = 'md', as = 'button', href, onClick, type, style, disabled }) {
  const sizes = {
    sm: { fontSize: 13, padding: '7px 14px', height: 32 },
    md: { fontSize: 14, padding: '10px 18px', height: 40 },
    lg: { fontSize: 15, padding: '13px 22px', height: 48 },
  }
  const variants = {
    primary:   { background: C.ink,         color: '#fff',  border: `1px solid ${C.ink}` },
    secondary: { background: C.bg,          color: C.ink,   border: `1px solid ${C.border}` },
    ghost:     { background: 'transparent', color: C.ink,   border: 'none' },
  }
  const base = {
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 7,
    borderRadius: 8, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap',
    transition: 'background 0.12s, transform 0.05s',
    opacity: disabled ? 0.5 : 1,
    ...sizes[size], ...variants[variant], ...style,
  }
  if (as === 'a') return <a href={href} style={base}>{children}</a>
  return <button type={type} onClick={onClick} disabled={disabled} style={base}>{children}</button>
}

function Logo({ size = 28, withText = true }) {
  return (
    <a href="#top" style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
      <div style={{
        width: size, height: size, borderRadius: 7,
        background: C.ink, color: '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: "'Fraunces', serif",
        fontSize: size * 0.55, fontWeight: 500, letterSpacing: '-0.04em',
      }}>O</div>
      {withText && <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>Omada</span>}
    </a>
  )
}

function Eyebrow({ children, color = C.t2 }) {
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 8,
      fontSize: 12, fontWeight: 600, color, letterSpacing: '0.08em',
      textTransform: 'uppercase',
    }}>{children}</div>
  )
}

// ─── Shared waitlist form (Supabase-backed) ──────────────────────────────────
function useWaitlist() {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState('idle') // idle | loading | success | error
  const [errorMsg, setErrorMsg] = useState('')

  async function submit(e) {
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

  function reset() { setStatus('idle'); setErrorMsg('') }

  return { email, setEmail, status, errorMsg, submit, reset }
}

function HeroForm() {
  const { email, setEmail, status, errorMsg, submit, reset } = useWaitlist()

  if (status === 'success') {
    return (
      <div style={{
        marginTop: 36, maxWidth: 440, marginInline: 'auto',
        background: C.successBg, border: `1px solid #c8e6d3`, borderRadius: 12,
        padding: '16px 18px', display: 'flex', alignItems: 'center', gap: 12,
      }} role="status">
        <span style={{
          flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
          background: C.success, color: '#fff',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, fontWeight: 600,
        }}>✓</span>
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.success }}>You're on the list.</div>
          <div style={{ fontSize: 12, color: C.t2, marginTop: 2 }}>We'll be in touch when beta opens.</div>
        </div>
      </div>
    )
  }

  return (
    <>
      <form onSubmit={submit} noValidate style={{
        marginTop: 36, display: 'flex', gap: 8, maxWidth: 440, marginInline: 'auto',
        background: C.bg, border: `1px solid ${status === 'error' ? '#d44b4b' : C.border}`, borderRadius: 12, padding: 6,
        boxShadow: '0 1px 2px rgba(15,18,25,0.04), 0 8px 24px rgba(15,18,25,0.04)',
      }}>
        <input
          id="waitlist"
          type="email"
          placeholder="you@company.com"
          required
          value={email}
          onChange={(e) => { setEmail(e.target.value); if (status === 'error') reset() }}
          autoComplete="email"
          style={{
            flex: 1, background: 'transparent', border: 'none',
            padding: '10px 14px', fontSize: 14, color: C.t1,
            outline: 'none',
          }}
        />
        <Btn variant="primary" size="md" type="submit" disabled={status === 'loading'}>
          {status === 'loading' ? <span className="spinner" /> : 'Request access →'}
        </Btn>
      </form>
      <div style={{ marginTop: 14, fontSize: 12, color: status === 'error' ? '#d44b4b' : C.t3, minHeight: 16 }}>
        {status === 'error' ? errorMsg : 'Free trial. Connect Jira in under 3 minutes.'}
      </div>
    </>
  )
}

function FinalCTAForm() {
  const { email, setEmail, status, errorMsg, submit, reset } = useWaitlist()

  if (status === 'success') {
    return (
      <div style={{
        marginTop: 32, maxWidth: 440, marginInline: 'auto',
        background: 'rgba(255,255,255,0.10)', border: '1px solid rgba(255,255,255,0.22)', borderRadius: 12,
        padding: '16px 18px', display: 'flex', alignItems: 'center', gap: 12,
      }} role="status">
        <span style={{
          flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
          background: '#fff', color: C.ink,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, fontWeight: 600,
        }}>✓</span>
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>You're on the list.</div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.65)', marginTop: 2 }}>We'll be in touch when beta opens.</div>
        </div>
      </div>
    )
  }

  return (
    <>
      <form onSubmit={submit} noValidate style={{
        marginTop: 32, display: 'flex', gap: 8, maxWidth: 440, marginInline: 'auto',
        background: 'rgba(255,255,255,0.08)',
        border: `1px solid ${status === 'error' ? '#ff8585' : 'rgba(255,255,255,0.15)'}`,
        borderRadius: 12, padding: 6,
      }}>
        <input
          type="email"
          placeholder="you@company.com"
          required
          value={email}
          onChange={(e) => { setEmail(e.target.value); if (status === 'error') reset() }}
          autoComplete="email"
          style={{
            flex: 1, background: 'transparent', border: 'none',
            padding: '10px 14px', fontSize: 14, color: '#fff',
            outline: 'none',
          }}
        />
        <button type="submit" disabled={status === 'loading'} style={{
          background: '#fff', color: C.ink, border: 'none',
          padding: '10px 18px', borderRadius: 8, fontSize: 14, fontWeight: 500,
          cursor: 'pointer', opacity: status === 'loading' ? 0.6 : 1,
          display: 'inline-flex', alignItems: 'center', gap: 7, minWidth: 130, justifyContent: 'center',
        }}>
          {status === 'loading' ? <span className="spinner spinner-dark" /> : 'Request access →'}
        </button>
      </form>
      {status === 'error' && (
        <div style={{ marginTop: 12, fontSize: 12, color: '#ff8585' }}>{errorMsg}</div>
      )}
    </>
  )
}

// ─── Top nav ──────────────────────────────────────────────────────────────────
function Nav() {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    function onScroll() { setScrolled(window.scrollY > 8) }
    window.addEventListener('scroll', onScroll)
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  return (
    <header style={{
      position: 'sticky', top: 0, zIndex: 50,
      background: scrolled ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.6)',
      backdropFilter: 'saturate(140%) blur(12px)',
      WebkitBackdropFilter: 'saturate(140%) blur(12px)',
      borderBottom: scrolled ? `1px solid ${C.border}` : '1px solid transparent',
      transition: 'border-color 0.2s, background 0.2s',
    }}>
      <div style={{ maxWidth: MAXW, margin: '0 auto', padding: '14px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24 }}>
        <Logo />
        <nav style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
          {[
            { label: 'Modules',      href: '#modules' },
            { label: 'How it works', href: '#how-it-works' },
            { label: 'Pricing',      href: '#pricing' },
          ].map(l => (
            <a key={l.label} href={l.href} style={{
              fontSize: 14, color: C.t2, fontWeight: 500,
            }}>{l.label}</a>
          ))}
        </nav>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Btn variant="ghost" size="sm" as="a" href="#waitlist">Sign in</Btn>
          <Btn variant="primary" size="sm" as="a" href="#waitlist">Join waitlist →</Btn>
        </div>
      </div>
    </header>
  )
}

// ─── Hero ─────────────────────────────────────────────────────────────────────
function Hero() {
  return (
    <section id="top" style={{ position: 'relative', overflow: 'hidden' }}>
      <div aria-hidden style={{
        position: 'absolute', inset: 0,
        backgroundImage:
          `linear-gradient(${C.borderS} 1px, transparent 1px),
           linear-gradient(90deg, ${C.borderS} 1px, transparent 1px)`,
        backgroundSize: '56px 56px',
        maskImage: 'radial-gradient(ellipse at top, #000 30%, transparent 70%)',
        WebkitMaskImage: 'radial-gradient(ellipse at top, #000 30%, transparent 70%)',
        opacity: 0.7,
      }} />

      <div style={{ position: 'relative', maxWidth: MAXW, margin: '0 auto', padding: '88px 28px 64px' }}>
        <div className="fade-up" style={{ maxWidth: 820, margin: '0 auto', textAlign: 'center' }}>
          <Eyebrow>
            <span style={{
              width: 6, height: 6, borderRadius: '50%', background: C.success,
              boxShadow: `0 0 0 4px ${C.successBg}`,
            }} className="blip" />
            Pre-beta · Now accepting early teams
          </Eyebrow>

          <h1 style={{
            fontFamily: "'Fraunces', serif",
            fontSize: 'clamp(40px, 6vw, 68px)',
            lineHeight: 1.05,
            letterSpacing: '-0.025em',
            fontWeight: 500,
            marginTop: 24,
          }}>
            Your tools record what happened. <em style={{ fontStyle: 'italic', color: C.t2, fontWeight: 400 }}>None of them learn from it.</em>
          </h1>

          <p style={{
            marginTop: 22, fontSize: 18, lineHeight: 1.6, color: C.t2,
            maxWidth: 600, marginInline: 'auto',
          }}>
            Omada is the planning intelligence layer that sits on top of Jira, Linear, and GitHub Projects — so your team stops repeating the same sprint failures, sprint after sprint.
          </p>

          <HeroForm />
        </div>

        <div className="fade-up" style={{ marginTop: 72, animationDelay: '0.15s' }}>
          <ProductMock />
        </div>
      </div>
    </section>
  )
}

// ─── Product mock — Velocity Mirror dashboard ─────────────────────────────────
function ProductMock() {
  const bars = [62, 78, 71, 88, 74, 92, 86, 95]
  const target = 82
  return (
    <div style={{
      maxWidth: 1020, margin: '0 auto',
      background: C.bg, border: `1px solid ${C.border}`, borderRadius: 16,
      boxShadow: '0 1px 3px rgba(15,18,25,0.04), 0 24px 64px -16px rgba(15,18,25,0.18)',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '12px 16px', borderBottom: `1px solid ${C.border}`, background: C.bgSubtle,
      }}>
        <div style={{ display: 'flex', gap: 6 }}>
          {['#ff5f57', '#febc2e', '#28c840'].map(c => (
            <div key={c} style={{ width: 11, height: 11, borderRadius: '50%', background: c, opacity: 0.85 }} />
          ))}
        </div>
        <div style={{
          flex: 1, maxWidth: 320, margin: '0 auto',
          background: C.bg, border: `1px solid ${C.border}`, borderRadius: 6,
          padding: '4px 10px', fontSize: 12, color: C.t3, textAlign: 'center',
        }}>omada.app / platform-team / sprint-47</div>
        <div style={{ width: 50 }} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', minHeight: 460 }}>
        <aside style={{ background: C.bgSubtle, borderRight: `1px solid ${C.border}`, padding: '20px 14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px 16px' }}>
            <div style={{ width: 22, height: 22, borderRadius: 5, background: C.ink, color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: "'Fraunces', serif", fontSize: 13, fontWeight: 500 }}>O</div>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Platform Team</span>
          </div>
          {[
            { i: '◇', l: 'Scope Cop' },
            { i: '◆', l: 'Sprint Brain' },
            { i: '◈', l: 'Dependency Radar' },
            { i: '◉', l: 'Velocity Mirror', active: true },
            { i: '◎', l: 'Retro AI' },
          ].map(item => (
            <div key={item.l} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '7px 8px',
              fontSize: 12, color: item.active ? C.ink : C.t2,
              fontWeight: item.active ? 600 : 500,
              background: item.active ? C.bg : 'transparent',
              border: item.active ? `1px solid ${C.border}` : '1px solid transparent',
              borderRadius: 6, marginBottom: 2,
            }}>
              <span style={{ color: item.active ? C.ink : C.t3, fontSize: 10 }}>{item.i}</span>
              {item.l}
            </div>
          ))}
        </aside>

        <main style={{ padding: '24px 28px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 22 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.t3, letterSpacing: '0.07em', textTransform: 'uppercase' }}>Sprint 47 · Day 6 of 10</div>
              <h3 style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em', marginTop: 4 }}>Velocity Mirror</h3>
            </div>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '5px 10px', borderRadius: 999,
              background: C.warnBg, color: C.warn, fontSize: 12, fontWeight: 600,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.warn }} />
              On-pace risk
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 22 }}>
            {[
              { l: 'Committed',     v: '42 pts',  s: '—',         c: C.t2 },
              { l: 'Projected',     v: '36 pts',  s: '↓ 14%',     c: C.warn },
              { l: 'Spillover risk',v: 'Medium',  s: '6 tickets', c: C.warn },
            ].map(s => (
              <div key={s.l} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: '12px 14px' }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, letterSpacing: '0.07em', textTransform: 'uppercase' }}>{s.l}</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                  <div style={{ fontSize: 19, fontWeight: 600 }}>{s.v}</div>
                  <div style={{ fontSize: 11, color: s.c, fontWeight: 500 }}>{s.s}</div>
                </div>
              </div>
            ))}
          </div>

          <div style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: '16px 18px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>Burndown · Last 8 sprints</div>
              <div style={{ display: 'flex', gap: 12, fontSize: 11, color: C.t2 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ width: 10, height: 2, background: C.ink }} /> Completed
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ width: 10, height: 2, background: C.t3, opacity: 0.5 }} /> Target ({target}%)
                </span>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 14, height: 140, position: 'relative' }}>
              {bars.map((b, i) => (
                <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                  <div style={{ flex: 1, width: '100%', display: 'flex', alignItems: 'flex-end' }}>
                    <div style={{
                      width: '100%', height: `${b}%`,
                      background: i === bars.length - 1 ? C.warn : C.ink,
                      borderRadius: '4px 4px 0 0',
                      opacity: i === bars.length - 1 ? 0.85 : 1 - (bars.length - 1 - i) * 0.07,
                    }} />
                  </div>
                  <div style={{ fontSize: 10, color: C.t3 }}>S{40 + i}</div>
                </div>
              ))}
              <div style={{ position: 'absolute', left: 0, right: 0, bottom: `${target * 0.7 * 140 / 100}px`, height: 1, borderTop: `1px dashed ${C.t3}`, opacity: 0.5 }} />
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}

// ─── Logo strip ───────────────────────────────────────────────────────────────
function LogoStrip() {
  return (
    <section style={{ borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}`, background: C.bgSubtle }}>
      <div style={{ maxWidth: MAXW, margin: '0 auto', padding: '28px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 32, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: C.t3, fontWeight: 500, letterSpacing: '0.04em' }}>WORKS ON TOP OF</span>
        <div style={{ display: 'flex', gap: 40, alignItems: 'center', flexWrap: 'wrap', color: C.t2 }}>
          {['Jira', 'Linear', 'GitHub Projects', 'GitLab', 'Azure DevOps'].map(t => (
            <span key={t} style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>{t}</span>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Problem framing ──────────────────────────────────────────────────────────
function Problem() {
  return (
    <section style={{ padding: '120px 28px 80px' }}>
      <div style={{ maxWidth: MAXW, margin: '0 auto' }}>
        <div style={{ maxWidth: 720, marginInline: 'auto', textAlign: 'center', marginBottom: 64 }}>
          <Eyebrow>The problem</Eyebrow>
          <h2 style={{
            fontFamily: "'Fraunces', serif", fontWeight: 500,
            fontSize: 'clamp(32px, 4.5vw, 48px)', lineHeight: 1.1,
            letterSpacing: '-0.02em', marginTop: 16,
          }}>
            Engineering teams fail the same way, <em style={{ color: C.t2, fontStyle: 'italic', fontWeight: 400 }}>sprint after sprint.</em>
          </h2>
          <p style={{ marginTop: 18, fontSize: 17, color: C.t2, lineHeight: 1.6 }}>
            Your tracker logs what shipped. Retros surface what hurt. Nothing closes the loop — so the same problems recur for months.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
          {[
            { stat: '~50%', label: 'Of sprint capacity lost to spillover', sub: 'in undisciplined teams' },
            { stat: '10%',  label: 'Of capacity spent on administrative overhead', sub: 'tickets, retros, replanning' },
            { stat: '6 mo', label: 'Of retros surfacing the same issues', sub: 'with no measurable improvement' },
          ].map(s => (
            <div key={s.label} style={{
              border: `1px solid ${C.border}`, borderRadius: 12, padding: '28px',
              background: C.bg,
            }}>
              <div style={{
                fontFamily: "'Fraunces', serif", fontSize: 56, fontWeight: 500,
                letterSpacing: '-0.03em', lineHeight: 1, color: C.ink,
              }}>{s.stat}</div>
              <div style={{ marginTop: 14, fontSize: 15, fontWeight: 500, color: C.ink, lineHeight: 1.4 }}>{s.label}</div>
              <div style={{ marginTop: 4, fontSize: 13, color: C.t3 }}>{s.sub}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Modules / Closed Loop ────────────────────────────────────────────────────
function Modules() {
  return (
    <section id="modules" style={{ padding: '80px 28px 56px', background: C.bgSubtle, borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}` }}>
      <div style={{ maxWidth: MAXW, margin: '0 auto' }}>
        <div style={{ maxWidth: 720, marginInline: 'auto', textAlign: 'center', marginBottom: 56 }}>
          <Eyebrow>Five modules · One closed loop</Eyebrow>
          <h2 style={{
            fontFamily: "'Fraunces', serif", fontWeight: 500,
            fontSize: 'clamp(32px, 4.5vw, 48px)', lineHeight: 1.1,
            letterSpacing: '-0.02em', marginTop: 16,
          }}>
            Every module feeds the next. <em style={{ color: C.t2, fontStyle: 'italic', fontWeight: 400 }}>Every sprint gets smarter.</em>
          </h2>
        </div>

        <LoopDiagram />
      </div>
    </section>
  )
}

function LoopDiagram() {
  const nodes = ['Scope Cop','Sprint Brain','Dependency Radar','Velocity Mirror','Retro AI']
  return (
    <div style={{
      background: C.bg, border: `1px solid ${C.border}`, borderRadius: 16,
      padding: '40px 32px', display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexWrap: 'wrap', gap: 8,
    }}>
      {nodes.map((n, i) => (
        <Fragment key={n}>
          <div style={{
            padding: '10px 16px', border: `1px solid ${C.border}`, borderRadius: 999,
            background: C.bgSubtle, fontSize: 13, fontWeight: 500, color: C.ink,
            display: 'inline-flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%', background: C.ink,
              opacity: 0.85,
            }} />
            {n}
          </div>
          {i < nodes.length - 1 && (
            <svg width="22" height="14" viewBox="0 0 22 14" style={{ color: C.t3 }}>
              <path d="M1 7 L18 7 M14 3 L18 7 L14 11" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </Fragment>
      ))}
      <svg width="22" height="14" viewBox="0 0 22 14" style={{ color: C.t3, opacity: 0.6 }}>
        <path d="M1 7 C 1 0, 21 0, 21 7" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 3" fill="none" />
      </svg>
      <div style={{ fontSize: 12, color: C.t3, fontStyle: 'italic' }}>…next sprint, smarter.</div>
    </div>
  )
}

// ─── Differentiators ──────────────────────────────────────────────────────────
function Different() {
  const items = [
    {
      title: 'Closed-loop, not point solutions',
      body: 'Other tools live in one stage. Omada connects planning, execution, and retro into a single learning system.',
      vs: 'vs. Spinach, Nave, Jira AI',
    },
    {
      title: 'Per-developer velocity',
      body: "Team averages hide everything. Omada profiles individual estimation accuracy so seniors don't carry juniors' optimism.",
      vs: 'vs. ClickUp, Jira Advanced Roadmaps',
    },
    {
      title: 'Compounds over time',
      body: 'The longer you use it, the better it gets. Institutional memory becomes a moat — not a switching cost waiting to bite.',
      vs: 'vs. spreadsheets, tribal knowledge',
    },
  ]
  return (
    <section style={{ padding: '120px 28px' }}>
      <div style={{ maxWidth: MAXW, margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 48, alignItems: 'start' }}>
          <div>
            <Eyebrow>Why Omada</Eyebrow>
            <h2 style={{
              fontFamily: "'Fraunces', serif", fontWeight: 500,
              fontSize: 'clamp(32px, 4vw, 44px)', lineHeight: 1.1,
              letterSpacing: '-0.02em', marginTop: 16,
            }}>
              Not another dashboard. <em style={{ color: C.t2, fontStyle: 'italic', fontWeight: 400 }}>An intelligence layer.</em>
            </h2>
            <p style={{ marginTop: 18, fontSize: 16, color: C.t2, lineHeight: 1.6 }}>
              We sit on top of the tools you already use. We read your sprint history. And we make the decision moments — planning, mid-sprint, retro — evidence-led instead of optimistic.
            </p>
            <div style={{ marginTop: 28 }}>
              <Btn variant="secondary" size="md" as="a" href="#how-it-works">
                See how it works →
              </Btn>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 1, background: C.border, border: `1px solid ${C.border}`, borderRadius: 12, overflow: 'hidden' }}>
            {items.map(it => (
              <div key={it.title} style={{ background: C.bg, padding: '24px 26px' }}>
                <h4 style={{ fontSize: 17, fontWeight: 600, letterSpacing: '-0.01em', marginBottom: 6 }}>{it.title}</h4>
                <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55, marginBottom: 8 }}>{it.body}</p>
                <span style={{ fontSize: 11, color: C.t3, fontWeight: 500, letterSpacing: '0.04em' }}>{it.vs}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── How it works ─────────────────────────────────────────────────────────────
function HowItWorks() {
  const steps = [
    { n: '1', t: 'Connect',  d: 'OAuth into Jira, Linear, or GitHub Projects. No migration. No rip-and-replace.' },
    { n: '2', t: 'Import',   d: 'Omada reads your last 3+ sprints and builds per-developer velocity profiles.' },
    { n: '3', t: 'Plan',     d: 'Sprint Brain surfaces capacity, dependencies, and risk at planning time — as evidence, not opinion.' },
    { n: '4', t: 'Improve',  d: 'Velocity Mirror flags drift mid-sprint. Retro AI closes the loop. Next sprint, smarter.' },
  ]
  return (
    <section id="how-it-works" style={{ padding: '80px 28px 120px', background: C.bgSubtle, borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}` }}>
      <div style={{ maxWidth: MAXW, margin: '0 auto' }}>
        <div style={{ maxWidth: 680, marginInline: 'auto', textAlign: 'center', marginBottom: 56 }}>
          <Eyebrow>How it works</Eyebrow>
          <h2 style={{
            fontFamily: "'Fraunces', serif", fontWeight: 500,
            fontSize: 'clamp(32px, 4.5vw, 48px)', lineHeight: 1.1,
            letterSpacing: '-0.02em', marginTop: 16,
          }}>
            Connected in 3 minutes. <em style={{ color: C.t2, fontStyle: 'italic', fontWeight: 400 }}>Compounding from sprint one.</em>
          </h2>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
          {steps.map((s) => (
            <div key={s.n} style={{
              background: C.bg, border: `1px solid ${C.border}`, borderRadius: 12,
              padding: '24px', position: 'relative',
            }}>
              <div style={{
                fontFamily: "'Fraunces', serif", fontSize: 32, fontWeight: 500,
                color: C.t3, letterSpacing: '-0.02em', lineHeight: 1,
              }}>{s.n}</div>
              <h4 style={{ fontSize: 16, fontWeight: 600, marginTop: 18, marginBottom: 6 }}>{s.t}</h4>
              <p style={{ fontSize: 13, color: C.t2, lineHeight: 1.55 }}>{s.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Pricing ──────────────────────────────────────────────────────────────────
function Pricing() {
  const [annual, setAnnual] = useState(false)
  const tiers = [
    {
      name: 'Free',
      size: '< 5 devs',
      sizeNote: 'Forever free — no card required',
      priceMonthly: '$0',
      priceAnnual: '$0',
      period: '',
      annualNote: '',
      modules: ['Jira integration', 'Sprint Planning', 'Scope Check', 'Last 3 sprints of history'],
      cta: 'Join the Beta',
      ctaHref: '#waitlist',
      featured: false,
    },
    {
      name: 'Starter',
      size: '5–10 devs',
      sizeNote: 'One flat rate for the whole team',
      priceMonthly: '$159',
      priceAnnual: '$129',
      period: '/mo',
      annualMonths: 129 * 12,
      modules: ['Everything in Free', 'All 5 modules', 'Unlimited sprint history', 'Slack & Google Calendar', 'Privacy controls'],
      cta: 'Join the Beta',
      ctaHref: '#waitlist',
      featured: false,
    },
    {
      name: 'Team',
      size: '11–20 devs',
      sizeNote: 'One flat rate for the whole team',
      priceMonthly: '$269',
      priceAnnual: '$219',
      period: '/mo',
      annualMonths: 219 * 12,
      modules: ['Everything in Starter', 'Microsoft Teams integration', 'Cross-sprint pattern detection', 'Priority support'],
      cta: 'Join the Beta',
      ctaHref: '#waitlist',
      featured: true,
    },
    {
      name: 'Growth',
      size: '21–35 devs',
      sizeNote: 'One flat rate for the whole team',
      priceMonthly: '$429',
      priceAnnual: '$349',
      period: '/mo',
      annualMonths: 349 * 12,
      modules: ['Everything in Team', 'Cross-squad dependency visibility', 'Linear & GitHub (soon)', 'Dedicated onboarding', 'Custom dashboards'],
      cta: 'Join the Beta',
      ctaHref: '#waitlist',
      featured: false,
    },
    {
      name: 'Enterprise',
      size: '35+ devs',
      sizeNote: 'Multiple squads, custom setup',
      priceMonthly: 'Custom',
      priceAnnual: 'Custom',
      period: '',
      annualNote: '',
      modules: ['Everything in Growth', 'SSO / SAML', 'Audit logs & compliance', 'SLA & dedicated support', 'Custom integrations'],
      cta: 'Talk to us',
      ctaHref: 'mailto:hello@omada.so',
      featured: false,
    },
  ]
  return (
    <section id="pricing" style={{ padding: '120px 28px' }}>
      <div style={{ maxWidth: MAXW, margin: '0 auto' }}>
        <div style={{ maxWidth: 680, marginInline: 'auto', textAlign: 'center', marginBottom: 40 }}>
          <Eyebrow>Pricing</Eyebrow>
          <h2 style={{
            fontFamily: "'Fraunces', serif", fontWeight: 500,
            fontSize: 'clamp(32px, 4.5vw, 48px)', lineHeight: 1.1,
            letterSpacing: '-0.02em', marginTop: 16,
          }}>
            Per team. <em style={{ color: C.t2, fontStyle: 'italic', fontWeight: 400 }}>Not per seat.</em>
          </h2>
          <p style={{ marginTop: 18, fontSize: 16, color: C.t2 }}>
            One flat rate per team. No seat counting, no surprise overages, no sales call required.
          </p>
        </div>

        {/* Billing toggle */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14,
          marginBottom: 36,
        }} role="group" aria-label="Billing period">
          <span style={{ fontSize: 13, color: annual ? C.t3 : C.ink, fontWeight: annual ? 500 : 600 }}>Monthly</span>
          <button
            type="button"
            role="switch"
            aria-checked={annual}
            onClick={() => setAnnual(a => !a)}
            style={{
              position: 'relative', width: 44, height: 24, borderRadius: 999,
              background: annual ? C.ink : C.bgMuted, border: `1px solid ${annual ? C.ink : C.border}`,
              padding: 0, cursor: 'pointer', transition: 'background 0.2s, border-color 0.2s',
            }}>
            <span style={{
              position: 'absolute', top: 2, left: annual ? 22 : 2,
              width: 18, height: 18, borderRadius: '50%',
              background: annual ? '#fff' : C.t3,
              transition: 'left 0.2s, background 0.2s',
            }} />
          </button>
          <span style={{ fontSize: 13, color: annual ? C.ink : C.t3, fontWeight: annual ? 600 : 500 }}>Annual</span>
          <span style={{
            fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
            color: C.success, background: C.successBg, border: `1px solid #c8e6d3`,
            padding: '3px 8px', borderRadius: 4,
          }}>Save 20%</span>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
          gap: 12, alignItems: 'stretch',
        }}>
          {tiers.map(t => {
            const price = annual ? t.priceAnnual : t.priceMonthly
            const showAnnualNote = annual && t.annualMonths
            return (
              <div key={t.name} style={{
                background: t.featured ? C.ink : C.bg,
                color: t.featured ? '#fff' : C.ink,
                border: `1px solid ${t.featured ? C.ink : C.border}`,
                borderRadius: 14, padding: '26px 22px',
                display: 'flex', flexDirection: 'column',
                position: 'relative',
                boxShadow: t.featured ? '0 16px 48px -12px rgba(15,18,25,0.35)' : 'none',
              }}>
                {t.featured && (
                  <div style={{
                    position: 'absolute', top: -10, left: '50%', transform: 'translateX(-50%)',
                    padding: '4px 10px', borderRadius: 999, background: '#fff', color: C.ink,
                    fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                    border: `1px solid ${C.border}`, whiteSpace: 'nowrap',
                  }}>Most teams pick this</div>
                )}
                <div style={{
                  fontSize: 11, fontWeight: 700, opacity: t.featured ? 0.7 : 0.55,
                  letterSpacing: '0.08em', textTransform: 'uppercase',
                }}>{t.name}</div>
                <div style={{
                  fontFamily: "'Fraunces', serif", fontSize: 17, fontWeight: 500,
                  marginTop: 6, opacity: t.featured ? 0.95 : 1,
                }}>{t.size}</div>
                <div style={{
                  fontSize: 11, opacity: t.featured ? 0.55 : 0.5, marginTop: 2, lineHeight: 1.45,
                }}>{t.sizeNote}</div>

                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 18 }}>
                  <span style={{
                    fontFamily: "'Fraunces', serif",
                    fontSize: price === 'Custom' || price === '$0' ? 32 : 40,
                    fontWeight: 500, letterSpacing: '-0.02em', lineHeight: 1,
                  }}>{price}</span>
                  {t.period && (
                    <span style={{ fontSize: 12, opacity: 0.6 }}>{t.period}</span>
                  )}
                </div>
                <div style={{
                  fontSize: 11, marginTop: 4, minHeight: 14,
                  color: t.featured ? 'rgba(255,255,255,0.7)' : C.success,
                  fontWeight: 500,
                }}>
                  {showAnnualNote ? `Billed $${t.annualMonths.toLocaleString()}/yr` : ' '}
                </div>

                <div style={{
                  height: 1, background: t.featured ? 'rgba(255,255,255,0.15)' : C.border,
                  margin: '18px 0',
                }} />

                <ul style={{
                  listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8,
                  marginBottom: 20, flex: 1, padding: 0,
                }}>
                  {t.modules.map(m => (
                    <li key={m} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13, lineHeight: 1.45 }}>
                      <svg width="13" height="13" viewBox="0 0 13 13" style={{ flexShrink: 0, opacity: 0.8, marginTop: 3 }}>
                        <path d="M2 7 L5 10 L11 3" stroke="currentColor" strokeWidth="1.7" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      {m}
                    </li>
                  ))}
                </ul>
                <a href={t.ctaHref} style={{
                  marginTop: 'auto',
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                  height: 42, borderRadius: 8, fontSize: 13, fontWeight: 500,
                  background: t.featured ? '#fff' : C.ink,
                  color:      t.featured ? C.ink : '#fff',
                  border: 'none', cursor: 'pointer',
                }}>{t.cta} →</a>
              </div>
            )
          })}
        </div>

        <div style={{ textAlign: 'center', marginTop: 24 }}>
          <a href="/pricing.html" style={{
            fontSize: 13, color: C.t2, fontWeight: 500,
            borderBottom: `1px solid ${C.border}`, paddingBottom: 2,
          }}>See feature comparison and FAQ →</a>
        </div>

        <p style={{
          textAlign: 'center', fontSize: 13, color: C.t3, marginTop: 18,
        }}>All paid plans include a 14-day free trial. No card required to start.</p>
      </div>
    </section>
  )
}

// ─── Final CTA ────────────────────────────────────────────────────────────────
function FinalCTA() {
  return (
    <section style={{ padding: '120px 28px' }}>
      <div style={{
        maxWidth: 940, margin: '0 auto',
        background: C.ink, color: '#fff', borderRadius: 20,
        padding: 'clamp(40px, 6vw, 72px)',
        textAlign: 'center', position: 'relative', overflow: 'hidden',
      }}>
        <div aria-hidden style={{
          position: 'absolute', inset: 0,
          backgroundImage:
            `linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px),
             linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)`,
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse at center, #000 30%, transparent 80%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, #000 30%, transparent 80%)',
        }} />
        <div style={{ position: 'relative' }}>
          <h2 style={{
            fontFamily: "'Fraunces', serif", fontWeight: 500,
            fontSize: 'clamp(32px, 4.5vw, 48px)', lineHeight: 1.1,
            letterSpacing: '-0.02em',
          }}>
            Stop repeating the same sprint failures. <em style={{ color: 'rgba(255,255,255,0.6)', fontStyle: 'italic', fontWeight: 400 }}>Start compounding.</em>
          </h2>
          <p style={{ marginTop: 18, fontSize: 16, color: 'rgba(255,255,255,0.7)', maxWidth: 520, marginInline: 'auto' }}>
            Beta opens this quarter. Join the first cohort of teams.
          </p>
          <FinalCTAForm />
        </div>
      </div>
    </section>
  )
}

// ─── Footer ───────────────────────────────────────────────────────────────────
function Footer() {
  const cols = [
    { h: 'Product',   l: [
      { t: 'Modules', href: '#modules' },
      { t: 'How it works', href: '#how-it-works' },
      { t: 'Pricing', href: '#pricing' },
    ]},
    { h: 'Company',   l: [{ t: 'About', href: '#' }, { t: 'Careers', href: '#' }] },
    { h: 'Resources', l: [{ t: 'Docs', href: '#' }, { t: 'Status', href: '#' }] },
    { h: 'Legal',     l: [{ t: 'Privacy', href: '#' }, { t: 'Terms', href: '#' }] },
  ]
  return (
    <footer style={{ background: C.bg, borderTop: `1px solid ${C.border}`, padding: '64px 28px 32px' }}>
      <div style={{ maxWidth: MAXW, margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr repeat(4, 1fr)', gap: 40, marginBottom: 56 }}>
          <div>
            <Logo />
            <p style={{ marginTop: 14, fontSize: 13, color: C.t2, lineHeight: 1.6, maxWidth: 260 }}>
              The planning intelligence layer for engineering teams that want every sprint to be smarter than the last.
            </p>
          </div>
          {cols.map(col => (
            <div key={col.h}>
              <div style={{ fontSize: 11, fontWeight: 700, color: C.t3, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 14 }}>{col.h}</div>
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 9, padding: 0 }}>
                {col.l.map(item => (
                  <li key={item.t}>
                    <a href={item.href} style={{ fontSize: 13, color: C.t2 }}>{item.t}</a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div style={{
          paddingTop: 24, borderTop: `1px solid ${C.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
        }}>
          <div style={{ fontSize: 12, color: C.t3 }}>© {new Date().getFullYear()} Omada. Built for teams that learn.</div>
          <div style={{ fontSize: 12, color: C.t3, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.success }} />
            All systems operational
          </div>
        </div>
      </div>
    </footer>
  )
}

// ─── App ──────────────────────────────────────────────────────────────────────
function App() {
  return (
    <>
      <Nav />
      <Hero />
      <LogoStrip />
      <Problem />
      <Modules />
      <Different />
      <HowItWorks />
      <Pricing />
      <FinalCTA />
      <Footer />
    </>
  )
}

export default App
