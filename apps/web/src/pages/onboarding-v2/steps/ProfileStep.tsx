/**
 * Step 2 — profile (name + phone). Validation is server-side; a 422 surfaces
 * as `saveError` shown next to the form.
 */
import { useState } from 'react'
import { Btn, C, Spinner } from '../theme'

const labelStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: C.t3, letterSpacing: '0.07em',
  textTransform: 'uppercase', marginBottom: 8, display: 'block',
}
const inputStyle: React.CSSProperties = {
  width: '100%', background: C.bg0, border: `1px solid ${C.border}`, borderRadius: 6,
  padding: '9px 12px', color: C.t1, fontSize: 14,
}

export function ProfileStep({
  onSave,
  saving,
  saveError,
}: {
  onSave: (name: string, phone: string) => void
  saving: boolean
  saveError: string | null
}) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Tell us who you are</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Just the basics — we use these to personalize your workspace and reach you about your projects.</p>
      </div>

      <form
        onSubmit={e => { e.preventDefault(); onSave(name, phone) }}
        style={{ display: 'flex', flexDirection: 'column', gap: 18 }}
      >
        <div>
          <label htmlFor="ob-name" style={labelStyle}>Name</label>
          <input id="ob-name" value={name} onChange={e => setName(e.target.value)} placeholder="Ada Lovelace" required style={inputStyle} />
        </div>
        <div>
          <label htmlFor="ob-phone" style={labelStyle}>Phone</label>
          <input id="ob-phone" type="tel" value={phone} onChange={e => setPhone(e.target.value)} placeholder="+1 555 123 4567" required style={inputStyle} />
        </div>

        {saveError && (
          <div role="alert" style={{ background: C.dangerBg, border: `1px solid ${C.dangerBd}`, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: C.danger }}>
            {saveError}
          </div>
        )}

        <div>
          <Btn type="submit" size="lg" disabled={saving} style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
            {saving ? <><Spinner size={14} color="rgba(255,255,255,0.85)" /> Saving…</> : <>Continue →</>}
          </Btn>
        </div>
      </form>
    </div>
  )
}
