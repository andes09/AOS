// apps/web/src/components/sprint/TicketRefineDrawer.tsx
// SB-13 — One-off "Refine" entry point. A lightweight single-ticket editor that
// wraps just TicketEditorPane in a right-side drawer, hitting SB-7's
// single-ticket revision endpoints (GET revision-preview + PATCH). This is the
// NON-batched path — distinct from PlanReviewModal / SignOffCarousel which go
// through the /commit flow.

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Button } from '../ui/Button'
import { Alert } from '../ui/Alert'
import { Spinner } from '../ui/Spinner'
import { TicketEditorPane } from './TicketEditorPane'
import { useApi, ApiError } from '../../lib/api'
import type {
  RevisionPreviewResponse,
  PatchRevisionRequest,
  TicketFields,
} from '../../types/inlineRefinement'

export interface TicketRefineDrawerProps {
  ticketKey: string
  teamId: string
  open: boolean
  onClose: () => void
  onRefined: () => void
}

// The revision-preview's original.description may be raw Jira ADF (an object)
// rather than a plain string (ADF round-tripping is deferred to v2). Guard: if
// it's not a string, treat it as empty for editing purposes.
function asText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

// Build the three TicketFields shapes the editor pane needs from the preview.
// - original: from preview.original (no AC available on the original side).
// - suggested: from preview.suggestedRevision (snake_case → camel), falling
//   back to the original value per field.
// - current: a clone of suggested (the editable starting point).
function buildFields(preview: RevisionPreviewResponse): {
  original: TicketFields
  suggested: TicketFields
  current: TicketFields
} {
  const original: TicketFields = {
    title: asText(preview.original.title),
    description: asText(preview.original.description),
    acceptanceCriteria: [],
    storyPoints: preview.original.story_points ?? null,
  }

  const rev = preview.suggestedRevision
  const suggested: TicketFields = {
    title: asText(rev?.title) || original.title,
    description: asText(rev?.description) || original.description,
    acceptanceCriteria: rev?.acceptance_criteria ?? original.acceptanceCriteria,
    storyPoints: rev?.story_points ?? original.storyPoints,
  }

  const current: TicketFields = {
    title: suggested.title,
    description: suggested.description,
    acceptanceCriteria: suggested.acceptanceCriteria.slice(),
    storyPoints: suggested.storyPoints,
  }

  return { original, suggested, current }
}

export function TicketRefineDrawer({
  ticketKey,
  teamId,
  open,
  onClose,
  onRefined,
}: TicketRefineDrawerProps) {
  const api = useApi()
  const [current, setCurrent] = useState<TicketFields | null>(null)
  const [conflict, setConflict] = useState(false)

  const previewQuery = useQuery<RevisionPreviewResponse>({
    queryKey: ['scope-cop', 'revision-preview', teamId, ticketKey],
    enabled: open,
    queryFn: () =>
      api.get<RevisionPreviewResponse>(
        `/api/scope-cop/tickets/${encodeURIComponent(ticketKey)}/revision-preview?team_id=${encodeURIComponent(teamId)}`,
      ),
  })

  const preview = previewQuery.data
  const fields = useMemo(() => (preview ? buildFields(preview) : null), [preview])

  // Seed editable `current` once the preview arrives (clone of suggested).
  useEffect(() => {
    if (fields) setCurrent(fields.current)
  }, [fields])

  const pushMutation = useMutation({
    mutationFn: () => {
      if (!current) throw new Error('No edits to push')
      const body: PatchRevisionRequest = {
        revision: {
          title: current.title,
          description: current.description,
          acceptanceCriteria: current.acceptanceCriteria,
          storyPoints: current.storyPoints,
        },
        fetchedUpdatedAt: preview?.fetchedUpdatedAt ?? '',
        teamId,
      }
      return api.patch<{ committed: boolean; result: unknown }>(
        `/api/scope-cop/tickets/${encodeURIComponent(ticketKey)}`,
        body,
      )
    },
    onSuccess: () => {
      setConflict(false)
      onRefined()
      onClose()
    },
    onError: err => {
      if (err instanceof ApiError && err.status === 409) {
        setConflict(true)
      }
    },
  })

  const handleReload = () => {
    setConflict(false)
    previewQuery.refetch()
  }

  if (!open) return null

  const isLoading = previewQuery.isLoading || previewQuery.isFetching
  const loadError = previewQuery.isError && !previewQuery.isFetching

  return (
    <div
      // Fixed overlay anchoring a right-side drawer.
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        justifyContent: 'flex-end',
        background: 'rgba(0, 0, 0, 0.4)',
      }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(720px, 92vw)',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--color-bg-primary)',
          borderLeft: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-lg, 0 0 24px rgba(0,0,0,0.3))',
          fontFamily: 'var(--font-sans)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '14px 18px',
            borderBottom: '1px solid var(--color-border-subtle)',
          }}
        >
          <span
            style={{
              fontSize: 'var(--text-sm)',
              fontWeight: 700,
              color: 'var(--color-text-primary)',
            }}
          >
            Refine ticket
          </span>
          <span
            style={{
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              color: 'var(--color-text-secondary)',
            }}
          >
            {ticketKey}
          </span>
          <div style={{ marginLeft: 'auto' }}>
            <Button size="sm" variant="ghost" onClick={onClose} title="Close">
              ×
            </Button>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {conflict && (
            <Alert variant="warning" title="Ticket changed in Jira">
              Ticket changed in Jira since you opened it — reload to get the latest.
              <div style={{ marginTop: 8 }}>
                <Button size="sm" variant="secondary" onClick={handleReload}>
                  Reload latest
                </Button>
              </div>
            </Alert>
          )}

          {isLoading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)' }}>
              <Spinner /> Loading suggestion…
            </div>
          )}

          {loadError && (
            <Alert variant="danger" title="Couldn't load suggestion">
              {previewQuery.error instanceof Error ? previewQuery.error.message : 'Unknown error.'}
              <div style={{ marginTop: 8 }}>
                <Button size="sm" variant="secondary" onClick={handleReload}>
                  Retry
                </Button>
              </div>
            </Alert>
          )}

          {!isLoading && !loadError && fields && current && (
            <TicketEditorPane
              original={fields.original}
              current={current}
              suggested={fields.suggested}
              onChange={setCurrent}
            />
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '12px 18px',
            borderTop: '1px solid var(--color-border-subtle)',
          }}
        >
          {pushMutation.isError && !conflict && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>
              {pushMutation.error instanceof Error ? pushMutation.error.message : 'Push failed.'}
            </span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <Button size="sm" variant="ghost" onClick={onClose} disabled={pushMutation.isPending}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => pushMutation.mutate()}
              disabled={pushMutation.isPending || !current || isLoading || loadError}
            >
              {pushMutation.isPending ? 'Pushing…' : 'Push to Jira'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
