/**
 * Step 4 (import path) — import_artifact. Upload dropzone + paste-text
 * textarea -> "Analyze" -> review screen: one card per proposed milestone
 * with an accept/reject toggle (defaults to accepted), a small inline form
 * for any missing brief fields, and an "Apply" button (disabled until at
 * least one milestone is accepted).
 */
import { useRef, useState } from 'react'
import { useImportArtifact } from '../../../features/onboarding-v2'
import { Alert, Btn, C, Spinner } from '../theme'

const ACCEPTED_EXTENSIONS = '.txt,.md,.pdf,.docx'

export function ImportArtifactStep() {
  const { importState, analyze, apply, milestones, isAccepted, toggleMilestone, acceptedCount } =
    useImportArtifact()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const fileInputRef = useRef<HTMLInputElement>(null)

  const analyzed = importState?.analyzed ?? false

  const handleAnalyze = () => {
    analyze.mutate({ text, files })
  }

  const handleFilePick = (picked: FileList | null) => {
    if (!picked) return
    setFiles(prev => [...prev, ...Array.from(picked)])
  }

  const handleApply = () => {
    const briefOverrides = Object.fromEntries(
      Object.entries(overrides).filter(([, v]) => v.trim().length > 0),
    )
    apply.mutate(Object.keys(briefOverrides).length > 0 ? briefOverrides : undefined)
  }

  if (!analyzed) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
        <div>
          <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Import your plan</h2>
          <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Paste your plan, or attach up to 5 files (.txt, .md, .pdf, .docx, 10MB each). We'll extract a project brief and draft a roadmap from it.</p>
        </div>

        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder="Paste a PRD, validation summary, or brainstorm here…"
          rows={8}
          style={{
            width: '100%', resize: 'vertical', fontSize: 13.5, lineHeight: 1.5, color: C.t1,
            padding: '12px 14px', borderRadius: 10, border: `1.5px solid ${C.border}`,
            fontFamily: 'inherit', background: C.bg0,
          }}
        />

        <div
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: `1.5px dashed ${C.borderStrong}`, borderRadius: 10, padding: '20px 16px',
            textAlign: 'center', cursor: 'pointer', background: C.bg0,
          }}
        >
          <div style={{ fontSize: 13.5, fontWeight: 600, color: C.t1 }}>Click to attach files</div>
          <div style={{ fontSize: 12, color: C.t3, marginTop: 2 }}>.txt, .md, .pdf, .docx — up to 5 files, 10MB each</div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS}
            onChange={e => handleFilePick(e.target.files)}
            style={{ display: 'none' }}
          />
        </div>

        {files.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {files.map((f, i) => (
              <div key={`${f.name}-${i}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 13, color: C.t2, padding: '6px 10px', background: C.bg3, borderRadius: 6 }}>
                <span>{f.name}</span>
                <button
                  type="button"
                  onClick={() => setFiles(prev => prev.filter((_, idx) => idx !== i))}
                  style={{ background: 'none', border: 'none', color: C.t3, cursor: 'pointer', fontSize: 12 }}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        {analyze.isError && <Alert>{(analyze.error as Error)?.message ?? 'Analysis failed. Please try again.'}</Alert>}

        <Btn
          size="lg"
          onClick={handleAnalyze}
          disabled={analyze.isPending || (!text.trim() && files.length === 0)}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 9, alignSelf: 'flex-start' }}
        >
          {analyze.isPending ? <><Spinner size={14} color="rgba(255,255,255,0.85)" /> Analyzing…</> : 'Analyze →'}
        </Btn>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>
          {importState?.projectName || 'Review your plan'}
        </h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>{importState?.summary}</p>
      </div>

      {importState?.truncated && (
        <Alert>Your document was long, so we only analyzed the first part of it.</Alert>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: C.t3, letterSpacing: '.07em', textTransform: 'uppercase', marginBottom: 8 }}>Proposed milestones — uncheck any you don't want</div>
        {milestones.map((m, i) => {
          const accepted = isAccepted(i)
          return (
            <button
              key={`${m.title}-${i}`}
              onClick={() => toggleMilestone(i)}
              style={{
                width: '100%', textAlign: 'left', display: 'flex', gap: 12, alignItems: 'flex-start',
                padding: '12px 14px', marginBottom: 8, borderRadius: 10, cursor: 'pointer',
                background: accepted ? C.bg0 : C.bg3,
                border: `1.5px solid ${accepted ? C.border : C.borderSubtle}`,
                opacity: accepted ? 1 : 0.55,
              }}
            >
              <span style={{ width: 18, height: 18, marginTop: 2, borderRadius: 5, flexShrink: 0, border: `1.5px solid ${accepted ? C.accent : C.borderStrong}`, background: accepted ? C.accent : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {accepted && <svg width="10" height="10" viewBox="0 0 8 8"><path d="M1 4 L3 6 L7 1" stroke="#fff" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>}
              </span>
              <span style={{ minWidth: 0, flex: 1 }}>
                <span style={{ display: 'block', fontSize: 14, fontWeight: 700, color: C.t1 }}>{m.title}</span>
                {m.description && <span style={{ display: 'block', fontSize: 12.5, color: C.t3, marginTop: 2 }}>{m.description}</span>}
                <span style={{ display: 'block', fontSize: 11.5, color: C.t3, marginTop: 4 }}>{m.tasks.length} task{m.tasks.length === 1 ? '' : 's'}</span>
              </span>
            </button>
          )
        })}
      </div>

      {importState && importState.missingFields.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.t3, letterSpacing: '.07em', textTransform: 'uppercase' }}>A few details we couldn't find</div>
          {importState.missingFields.map(field => (
            <input
              key={field}
              value={overrides[field] ?? ''}
              onChange={e => setOverrides(prev => ({ ...prev, [field]: e.target.value }))}
              placeholder={field.replace(/([A-Z])/g, ' $1').replace(/^./, c => c.toUpperCase())}
              style={{
                width: '100%', fontSize: 13.5, color: C.t1, padding: '9px 12px',
                borderRadius: 8, border: `1.5px solid ${C.border}`, fontFamily: 'inherit',
              }}
            />
          ))}
        </div>
      )}

      {apply.isError && <Alert>{(apply.error as Error)?.message ?? 'Applying the plan failed. Please try again.'}</Alert>}

      <Btn
        size="lg"
        onClick={handleApply}
        disabled={apply.isPending || acceptedCount < 1}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 9, alignSelf: 'flex-start' }}
      >
        {apply.isPending
          ? <><Spinner size={14} color="rgba(255,255,255,0.85)" /> Creating your project…</>
          : `Apply ${acceptedCount} milestone${acceptedCount === 1 ? '' : 's'} →`}
      </Btn>
    </div>
  )
}
