/**
 * Step 3 — purpose. A fixed 3-way choice (not free text) that steers the AI
 * interview's strategy server-side.
 */
import { useState } from 'react'
import type { ProjectPurpose } from '../../../features/onboarding-v2'
import { C } from '../theme'

const PURPOSE_OPTIONS: { value: ProjectPurpose; label: string; hint: string; hue: number }[] = [
  { value: 'hobby', label: 'A hobby project', hint: 'Something for fun, on my own time', hue: 150 },
  { value: 'startup', label: 'A startup', hint: 'A real product I want to launch and grow', hue: 18 },
  { value: 'learning', label: 'Learning', hint: 'Mainly to build a skill or portfolio piece', hue: 260 },
]

export function PurposeStep({
  onSave,
  saving,
}: {
  onSave: (purpose: ProjectPurpose) => void
  saving: boolean
}) {
  const [picked, setPicked] = useState<ProjectPurpose | null>(null)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>What's this project for?</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>This shapes how we plan it — a hobby, a startup, and a learning project all need different roadmaps.</p>
      </div>

      <div role="radiogroup" aria-label="Project purpose" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {PURPOSE_OPTIONS.map(opt => {
          const isSel = picked === opt.value
          return (
            <button
              key={opt.value}
              role="radio"
              aria-checked={isSel}
              disabled={saving}
              onClick={() => { setPicked(opt.value); onSave(opt.value) }}
              style={{
                width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13,
                cursor: saving ? 'default' : 'pointer',
                background: isSel ? C.accentSubtle : C.bg0,
                border: `1.5px solid ${isSel ? C.accent : C.border}`,
                borderRadius: 10, padding: '14px 16px', transition: 'all .12s',
                opacity: saving && !isSel ? 0.6 : 1,
              }}
            >
              <span style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, background: `oklch(0.95 0.03 ${opt.hue})`, border: `1px solid oklch(0.86 0.05 ${opt.hue})` }} />
              <span style={{ minWidth: 0, flex: 1 }}>
                <span style={{ display: 'block', fontSize: 14, fontWeight: 700, color: C.t1 }}>{opt.label}</span>
                <span style={{ display: 'block', fontSize: 12.5, color: C.t3, marginTop: 1 }}>{opt.hint}</span>
              </span>
              <span style={{ width: 18, height: 18, borderRadius: '50%', flexShrink: 0, border: `1.5px solid ${isSel ? C.accent : C.borderStrong}`, background: isSel ? C.accent : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {isSel && <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#fff' }} />}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
