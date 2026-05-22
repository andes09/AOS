import { Dispatch, SetStateAction } from 'react'
import { TeamDraft } from './types'
import { CADENCES, METHODS, SIZE_OPTIONS, TECH } from './data'
import { MultiSelect } from './MultiSelect'

interface TeamBasicsStepProps {
  data: TeamDraft
  setData: Dispatch<SetStateAction<TeamDraft>>
  onNext: () => void
}

const labelStyle = {
  display: 'block' as const,
  fontSize: 'var(--text-sm)' as const,
  fontWeight: 600 as const,
  color: 'var(--color-text-primary)' as const,
  fontFamily: 'var(--font-sans)' as const,
  marginBottom: 8,
}

function SegmentGroup({
  options,
  value,
  onChange,
}: {
  options: string[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {options.map(opt => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          style={{
            padding: '6px 14px',
            fontSize: 'var(--text-sm)',
            fontFamily: 'var(--font-sans)',
            fontWeight: value === opt ? 600 : 400,
            border: `1.5px solid ${value === opt ? 'var(--color-accent)' : 'var(--color-border)'}`,
            borderRadius: 'var(--radius-md)',
            background: value === opt ? 'rgba(12,102,228,0.08)' : 'transparent',
            color: value === opt ? 'var(--color-accent)' : 'var(--color-text-secondary)',
            cursor: 'pointer',
            transition: 'all 0.12s',
          }}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

export function TeamBasicsStep({ data, setData, onNext }: TeamBasicsStepProps) {
  function set<K extends keyof TeamDraft>(key: K, value: TeamDraft[K]) {
    setData(d => ({ ...d, [key]: value }))
  }

  const canNext = data.name.trim() !== ''

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div>
        <h2 style={{
          fontSize: 'var(--text-xl)',
          fontWeight: 700,
          color: 'var(--color-text-primary)',
          fontFamily: 'var(--font-sans)',
          margin: '0 0 4px',
          letterSpacing: '-0.01em',
        }}>
          Team basics
        </h2>
        <p style={{
          fontSize: 'var(--text-sm)',
          color: 'var(--color-text-muted)',
          fontFamily: 'var(--font-sans)',
          margin: 0,
        }}>
          This shapes how Omada tracks and reports on your team&rsquo;s velocity.
        </p>
      </div>

      {/* Team name */}
      <div>
        <label style={labelStyle}>Team name</label>
        <input
          style={{
            width: '100%',
            height: 38,
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            padding: '0 12px',
            fontSize: 'var(--text-sm)',
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            background: 'var(--color-bg-primary)',
            outline: 'none',
            boxSizing: 'border-box',
            transition: 'border-color 0.15s',
          }}
          placeholder="e.g. Platform Team"
          value={data.name}
          onChange={e => set('name', e.target.value)}
          onFocus={e => { (e.target as HTMLInputElement).style.borderColor = 'var(--color-accent)' }}
          onBlur={e => { (e.target as HTMLInputElement).style.borderColor = 'var(--color-border)' }}
        />
      </div>

      {/* Team size */}
      <div>
        <label style={labelStyle}>Team size</label>
        <SegmentGroup options={SIZE_OPTIONS} value={data.size} onChange={v => set('size', v)} />
      </div>

      {/* Sprint cadence */}
      <div>
        <label style={labelStyle}>Sprint cadence</label>
        <SegmentGroup options={CADENCES} value={data.cadence} onChange={v => set('cadence', v)} />
      </div>

      {/* How you work */}
      <div>
        <label style={labelStyle}>How you work</label>
        <SegmentGroup options={METHODS} value={data.methodology} onChange={v => set('methodology', v)} />
      </div>

      {/* Tech stack */}
      <MultiSelect
        label="Primary tech stack"
        placeholder="Search technologies…"
        options={TECH}
        selected={data.techStack}
        onChange={v => set('techStack', v)}
        allowCustom
      />

      {/* Next */}
      <div style={{ paddingTop: 4 }}>
        <button
          type="button"
          onClick={() => { if (canNext) onNext() }}
          disabled={!canNext}
          style={{
            padding: '10px 24px',
            fontSize: 'var(--text-sm)',
            fontFamily: 'var(--font-sans)',
            fontWeight: 600,
            border: 'none',
            borderRadius: 'var(--radius-md)',
            background: canNext ? 'var(--color-accent)' : 'var(--color-border)',
            color: canNext ? '#ffffff' : 'var(--color-text-muted)',
            cursor: canNext ? 'pointer' : 'not-allowed',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            transition: 'background 0.12s',
          }}
        >
          Add team members →
        </button>
      </div>
    </div>
  )
}
