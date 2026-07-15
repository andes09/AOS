/**
 * Step 5 — done. `complete()` only needs the profile step, so it's always safe
 * to call here; on success we navigate into the app.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Btn, C, Spinner } from '../theme'

export function DoneStep({ onFinish }: { onFinish: () => Promise<unknown> }) {
  const navigate = useNavigate()
  const [finishing, setFinishing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const finish = async () => {
    setFinishing(true)
    setError(null)
    try {
      await onFinish()
      navigate('/app')
    } catch (err) {
      setFinishing(false)
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    }
  }

  return (
    <div style={{ textAlign: 'center', padding: '32px 0', animation: 'fadeUp 0.22s ease both' }}>
      <div style={{ width: 56, height: 56, borderRadius: '50%', background: C.successBg, border: `1px solid ${C.success}`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px', fontSize: 24, color: C.success, animation: 'checkPop 0.3s ease both' }}>✓</div>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: C.t1, marginBottom: 8 }}>You're all set</h2>
      <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.6, marginBottom: 28, maxWidth: 380, marginLeft: 'auto', marginRight: 'auto' }}>
        Your workspace is ready. Omada will use everything you shared to draft your first roadmap.
      </p>

      {error && (
        <div role="alert" style={{ maxWidth: 380, margin: '0 auto 20px', background: C.dangerBg, border: `1px solid ${C.dangerBd}`, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: C.danger }}>
          {error}
        </div>
      )}

      <Btn size="lg" onClick={finish} disabled={finishing} style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
        {finishing ? <><Spinner size={14} color="rgba(255,255,255,0.85)" /> Setting up…</> : <>Go to your project →</>}
      </Btn>
    </div>
  )
}
