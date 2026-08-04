/**
 * Tech-stack step — what the founder already knows, or that they're new to
 * this. A multi-select (not a radio group, unlike PurposeStep) plus a
 * mutually-exclusive "I'm new to this" escape hatch: picking it clears any
 * chip selection, and picking a chip while it's active clears it back.
 */
import { useState } from 'react'
import type { TechExperience } from '../../../features/onboarding-v2'
import { Btn, C, Spinner } from '../theme'

const CATEGORIES: { label: string; options: string[] }[] = [
  { label: 'Frontend', options: ['React', 'Vue', 'Next.js', 'Angular', 'Svelte'] },
  { label: 'Backend', options: ['Node.js', 'Python (Django/Flask)', 'Go', 'Ruby on Rails', 'Java/Spring'] },
  { label: 'Database', options: ['PostgreSQL/MySQL', 'MongoDB'] },
  { label: 'Mobile', options: ['Swift/iOS', 'Kotlin/Android', 'React Native/Flutter'] },
  { label: 'Cloud & Hosting', options: ['AWS', 'Azure', 'Google Cloud', 'Railway', 'Vercel', 'Render', 'Heroku', 'DigitalOcean'] },
]

const inputStyle: React.CSSProperties = {
  background: C.bg0, border: `1px solid ${C.border}`, borderRadius: 6,
  padding: '7px 10px', color: C.t1, fontSize: 13,
}

export function TechStackStep({
  onSave,
  saving,
  saveError,
}: {
  onSave: (stack: string[], experience: TechExperience) => void
  saving: boolean
  saveError: string | null
}) {
  const [selected, setSelected] = useState<string[]>([])
  const [isNew, setIsNew] = useState(false)
  const [otherInput, setOtherInput] = useState('')

  function toggleChip(option: string) {
    setIsNew(false)
    setSelected(prev =>
      prev.includes(option) ? prev.filter(o => o !== option) : [...prev, option]
    )
  }

  function addOther() {
    const value = otherInput.trim()
    if (!value || selected.includes(value)) return
    setIsNew(false)
    setSelected(prev => [...prev, value])
    setOtherInput('')
  }

  function pickNew() {
    setSelected([])
    setOtherInput('')
    setIsNew(true)
  }

  const canContinue = isNew || selected.length > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>What do you already know?</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Pick anything you're comfortable building with — we'll plan around your existing tools instead of guessing.</p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {CATEGORIES.map(cat => (
          <div key={cat.label}>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.t3, letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>{cat.label}</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {cat.options.map(option => {
                const isSel = selected.includes(option)
                return (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={isSel}
                    disabled={saving}
                    onClick={() => toggleChip(option)}
                    style={{
                      cursor: saving ? 'default' : 'pointer',
                      background: isSel ? C.accentSubtle : C.bg0,
                      border: `1.5px solid ${isSel ? C.accent : C.border}`,
                      borderRadius: 999, padding: '6px 14px', fontSize: 13,
                      fontWeight: isSel ? 600 : 400, color: isSel ? C.t1 : C.t2,
                      transition: 'all .12s',
                    }}
                  >
                    {option}
                  </button>
                )
              })}
            </div>
          </div>
        ))}

        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: C.t3, letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>Something else?</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={otherInput}
              onChange={e => setOtherInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addOther() } }}
              placeholder="e.g. Rust, Elixir, Unity…"
              disabled={saving}
              style={{ ...inputStyle, flex: 1 }}
            />
            <Btn variant="secondary" size="sm" onClick={addOther} disabled={saving || !otherInput.trim()}>Add</Btn>
          </div>
          {selected.filter(o => !CATEGORIES.some(c => c.options.includes(o))).length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
              {selected.filter(o => !CATEGORIES.some(c => c.options.includes(o))).map(o => (
                <button
                  key={o}
                  type="button"
                  disabled={saving}
                  onClick={() => toggleChip(o)}
                  style={{
                    cursor: saving ? 'default' : 'pointer', background: C.accentSubtle,
                    border: `1.5px solid ${C.accent}`, borderRadius: 999, padding: '6px 14px',
                    fontSize: 13, fontWeight: 600, color: C.t1,
                  }}
                >
                  {o} ✕
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div style={{ borderTop: `1px solid ${C.borderSubtle}`, paddingTop: 18 }}>
        <button
          type="button"
          role="radio"
          aria-checked={isNew}
          disabled={saving}
          onClick={pickNew}
          style={{
            width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13,
            cursor: saving ? 'default' : 'pointer',
            background: isNew ? C.accentSubtle : C.bg0,
            border: `1.5px solid ${isNew ? C.accent : C.border}`,
            borderRadius: 10, padding: '14px 16px', transition: 'all .12s',
          }}
        >
          <span style={{ minWidth: 0, flex: 1 }}>
            <span style={{ display: 'block', fontSize: 14, fontWeight: 700, color: C.t1 }}>None of these — I'm new to this</span>
            <span style={{ display: 'block', fontSize: 12.5, color: C.t3, marginTop: 1 }}>We'll recommend a beginner-friendly stack and walk you through setup.</span>
          </span>
          <span style={{ width: 18, height: 18, borderRadius: '50%', flexShrink: 0, border: `1.5px solid ${isNew ? C.accent : C.borderStrong}`, background: isNew ? C.accent : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {isNew && <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#fff' }} />}
          </span>
        </button>
      </div>

      {saveError && (
        <div role="alert" style={{ background: C.dangerBg, border: `1px solid ${C.dangerBd}`, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: C.danger }}>
          {saveError}
        </div>
      )}

      <div>
        <Btn
          size="lg"
          disabled={saving || !canContinue}
          onClick={() => onSave(isNew ? [] : selected, isNew ? 'new' : 'experienced')}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}
        >
          {saving ? <><Spinner size={14} color="rgba(255,255,255,0.85)" /> Saving…</> : <>Continue →</>}
        </Btn>
      </div>
    </div>
  )
}
