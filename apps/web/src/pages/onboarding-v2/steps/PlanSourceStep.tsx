/**
 * Step 4 (chooser) — build_plan. A fork inside onboarding, not a standalone
 * flow: pick "Chat with AI" (existing idea_chat sub-flow) or "Import a plan"
 * (new import_artifact sub-flow). Same two-card visual language as
 * PurposeStep. No path-switching UI in v1 — once chosen, the choice is fixed
 * for the session (see docs/plans/2026-07-20-import-artifacts.md).
 */
import { useState } from 'react'
import type { PlanSource } from '../../../features/onboarding-v2'
import { C } from '../theme'

const SOURCE_OPTIONS: { value: PlanSource; label: string; hint: string; hue: number }[] = [
  { value: 'chat', label: 'Chat with AI', hint: "Answer a few questions and we'll draft your roadmap", hue: 210 },
  { value: 'import', label: 'Import a plan', hint: 'Paste text or upload a PRD, brainstorm, or README', hue: 320 },
]

export function PlanSourceStep({
  onSave,
  saving,
}: {
  onSave: (source: PlanSource) => void
  saving: boolean
}) {
  const [picked, setPicked] = useState<PlanSource | null>(null)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>How do you want to build your plan?</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Already have a PRD, a validation summary, or a rough brainstorm? Import it instead of re-explaining it.</p>
      </div>

      <div role="radiogroup" aria-label="Plan source" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {SOURCE_OPTIONS.map(opt => {
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
