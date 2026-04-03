// apps/web/src/components/mirror/DeveloperProfileModal.tsx

import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useApi, ApiError } from '../../lib/api'
import type { DeveloperProfileResponse } from '../../types/developer'

interface DeveloperProfileModalProps {
  developerId: string
  onClose: () => void
}

export function DeveloperProfileModal({ developerId, onClose }: DeveloperProfileModalProps) {
  const { get } = useApi()
  const backdropRef = useRef<HTMLDivElement>(null)

  const query = useQuery<DeveloperProfileResponse, ApiError>({
    queryKey: ['developer-profile', developerId],
    queryFn: () => get<DeveloperProfileResponse>(`/api/developers/${developerId}/profile`),
    retry: false,
  })

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === backdropRef.current) onClose()
  }

  const is403 = query.isError && query.error instanceof ApiError && query.error.status === 403

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div style={{
        background: '#1e2030',
        borderRadius: 12,
        padding: '1.5rem',
        minWidth: 340,
        maxWidth: 480,
        width: '90%',
        boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
        position: 'relative',
      }}>
        {/* Close button */}
        <button
          onClick={onClose}
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            background: 'none',
            border: 'none',
            color: '#64748b',
            fontSize: 18,
            cursor: 'pointer',
            lineHeight: 1,
          }}
          aria-label="Close"
        >
          ✕
        </button>

        {/* 403 */}
        {is403 && (
          <div style={{ color: '#fbbf24', fontSize: 14, padding: '1rem 0' }}>
            Lead role required to view profiles
          </div>
        )}

        {/* Loading skeleton */}
        {query.isLoading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[80, 120, 60, 100].map((w, i) => (
              <div key={i} style={{
                height: 14,
                width: `${w}%`,
                background: '#2d2f45',
                borderRadius: 4,
                animation: 'pulse 1.5s ease-in-out infinite',
              }} />
            ))}
          </div>
        )}

        {/* Other errors (not 403) */}
        {query.isError && !is403 && (
          <div style={{ color: '#ef4444', fontSize: 13 }}>
            Failed to load developer profile
          </div>
        )}

        {/* Success */}
        {query.isSuccess && (() => {
          const p = query.data
          const consistencyPct = Math.min(Math.max(Math.round(p.consistencyScore), 0), 100)
          const consistencyColour = consistencyPct >= 75 ? '#4ade80' : consistencyPct >= 50 ? '#fbbf24' : '#ef4444'

          return (
            <>
              {/* Header */}
              <div style={{ marginBottom: '1.25rem', paddingRight: 24 }}>
                <div style={{ color: '#e2e8f0', fontSize: 17, fontWeight: 700, marginBottom: 2 }}>
                  {p.name}
                </div>
                {p.role && (
                  <div style={{ color: '#64748b', fontSize: 12 }}>{p.role}</div>
                )}
              </div>

              {/* Stats row */}
              <div style={{ display: 'flex', gap: 20, marginBottom: '1.25rem' }}>
                <div>
                  <div style={{ color: '#94a3b8', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
                    Avg Velocity
                  </div>
                  <div style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 700 }}>
                    {p.avgVelocity}
                    <span style={{ color: '#64748b', fontSize: 11, marginLeft: 3 }}>pts/sprint</span>
                  </div>
                </div>
                <div>
                  <div style={{ color: '#94a3b8', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
                    Sprints
                  </div>
                  <div style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 700 }}>
                    {p.sprintCount}
                  </div>
                </div>
              </div>

              {/* Consistency score bar */}
              <div style={{ marginBottom: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <div style={{ color: '#94a3b8', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    Consistency
                  </div>
                  <div style={{ color: consistencyColour, fontSize: 12, fontWeight: 700 }}>
                    {consistencyPct}
                  </div>
                </div>
                <div style={{ background: '#2d2f45', height: 6, borderRadius: 3 }}>
                  <div style={{
                    width: `${consistencyPct}%`,
                    height: 6,
                    borderRadius: 3,
                    background: consistencyColour,
                    transition: 'width 0.4s ease',
                  }} />
                </div>
              </div>

              {/* Domains */}
              {p.domains.length > 0 && (
                <div style={{ marginBottom: '1.25rem' }}>
                  <div style={{ color: '#94a3b8', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
                    Domains
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {p.domains.map(domain => (
                      <span key={domain} style={{
                        background: '#2d2f45',
                        color: '#a5b4fc',
                        fontSize: 11,
                        padding: '2px 8px',
                        borderRadius: 20,
                      }}>
                        {domain}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Strong ticket types */}
              {p.strongTicketTypes.length > 0 && (
                <div>
                  <div style={{ color: '#94a3b8', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
                    Strong Ticket Types
                  </div>
                  <ol style={{ margin: 0, paddingLeft: 18 }}>
                    {p.strongTicketTypes.map(type => (
                      <li key={type} style={{ color: '#e2e8f0', fontSize: 13, marginBottom: 2 }}>
                        {type}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </>
          )
        })()}
      </div>
    </div>
  )
}
