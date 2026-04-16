import { useEffect, useState } from 'react'

export interface ConfidenceGaugeProps {
  score: number        // 0–1
  sampleSize?: number
  sprintCount?: number
}

const R = 22
const CIRC = 2 * Math.PI * R

function gaugeColour(score: number): string {
  if (score > 0.75) return 'var(--color-success)'
  if (score >= 0.5) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

export function ConfidenceGauge({ score, sampleSize, sprintCount }: ConfidenceGaugeProps) {
  const [animated, setAnimated] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 50)
    return () => clearTimeout(t)
  }, [])

  const pct = Math.round(score * 100)
  const colour = gaugeColour(score)
  const dashOffset = animated ? CIRC * (1 - score) : CIRC
  const label = score > 0.75 ? 'High' : score >= 0.5 ? 'Medium' : 'Low'

  const tooltipLines = [
    `Confidence: ${pct}%`,
    sampleSize != null ? `Based on ${sampleSize} tickets` : null,
    sprintCount != null ? `Across ${sprintCount} sprints` : null,
  ].filter((l): l is string => l !== null)

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <svg width={60} height={60} viewBox="0 0 60 60" role="img" aria-label={tooltipLines.join(', ')}>
        <title>{tooltipLines.join('\n')}</title>
        <circle cx={30} cy={30} r={R} fill="none" stroke="var(--color-border)" strokeWidth={6} />
        <circle
          cx={30} cy={30} r={R}
          fill="none"
          stroke={colour}
          strokeWidth={6}
          strokeDasharray={CIRC}
          strokeDashoffset={dashOffset}
          transform="rotate(-90 30 30)"
          style={{ transition: 'stroke-dashoffset 0.8s ease-out' }}
        />
        <text x={30} y={34} textAnchor="middle" fill="var(--color-text-primary)" fontSize={11} fontWeight={700}>
          {pct}%
        </text>
      </svg>
      <div>
        <div style={{
          color: 'var(--color-text-secondary)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
        }}>
          Confidence
        </div>
        <div style={{ color: colour, fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', fontWeight: 700, marginTop: 2 }}>
          {label}
        </div>
      </div>
    </div>
  )
}
