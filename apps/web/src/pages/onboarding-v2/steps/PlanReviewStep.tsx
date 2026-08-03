/**
 * Step (gated behind experimental.plan_review) — review the drafted roadmap
 * before it's committed. On mount it ensures a draft exists (POST /plan/draft;
 * the chat path generates here, the import path already has one), fetches the
 * roadmap, and lets the founder regenerate it or accept it. "Looks good"
 * confirms (POST /plan/confirm), advancing the flow to `done`.
 *
 * Never-brick: if drafting fails, the founder can still "Continue anyway",
 * which confirms and falls through to POST /complete's own best-effort
 * generation (and the project-hub fallback if that also fails).
 */
import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useOnboardingState } from '../../../features/onboarding-v2'
import { useApi } from '../../../lib/api'
import type { Roadmap } from '../../../types/roadmap'
import { Alert, Btn, C, Spinner } from '../theme'

const ROADMAP_KEY = (projectId: string) => ['onboarding-plan-review-roadmap', projectId] as const

export function PlanReviewStep() {
  const { state, draftPlan, confirmPlan } = useOnboardingState()
  const api = useApi()
  const queryClient = useQueryClient()

  const projectId = state?.projectId ?? draftPlan.data?.projectId ?? null

  // Draft the roadmap once if no project exists yet (chat path). A ref guards
  // against re-firing on re-render; the query below picks up the projectId.
  const draftedRef = useRef(false)
  useEffect(() => {
    if (!projectId && !draftedRef.current && !draftPlan.isPending) {
      draftedRef.current = true
      draftPlan.mutate()
    }
  }, [projectId, draftPlan])

  const roadmap = useQuery({
    queryKey: projectId ? ROADMAP_KEY(projectId) : ['onboarding-plan-review-roadmap', 'none'],
    queryFn: () => api.get<Roadmap>(`/api/projects/${projectId}/roadmap`),
    enabled: !!projectId,
  })

  const regenerate = useMutation({
    mutationFn: () => api.post<Roadmap>(`/api/projects/${projectId}/roadmap/regenerate`, {}),
    onSuccess: data => {
      if (projectId) queryClient.setQueryData(ROADMAP_KEY(projectId), data)
    },
  })

  const draftFailed = draftPlan.isError && !projectId
  const busy = confirmPlan.isPending

  // Draft in flight, or drafted but roadmap still loading.
  if (!draftFailed && (draftPlan.isPending || (projectId && roadmap.isLoading))) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: C.t3, fontSize: 14, padding: '40px 0', animation: 'fadeUp 0.22s ease both' }}>
        <Spinner size={16} /> Drafting your roadmap…
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Review your roadmap</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>
          Here's the plan Omada drafted from everything you shared. Regenerate it if it's off, or accept it to get started.
        </p>
      </div>

      {draftFailed && (
        <>
          <Alert>We couldn't draft your roadmap just now. You can continue — we'll try again as you finish up, and you can always generate it from your project.</Alert>
          <Btn size="lg" onClick={() => confirmPlan.mutate()} disabled={busy} style={{ alignSelf: 'flex-start' }}>
            {busy ? 'Finishing…' : 'Continue anyway →'}
          </Btn>
        </>
      )}

      {roadmap.isError && !draftFailed && (
        <Alert>Couldn't load the drafted roadmap. Try regenerating, or continue to your project.</Alert>
      )}

      {roadmap.data && (
        <>
          {roadmap.data.summary && (
            <div style={{ fontSize: 13.5, color: C.t2, lineHeight: 1.55, padding: '12px 14px', background: C.bg0, border: `1px solid ${C.border}`, borderRadius: 8 }}>
              {roadmap.data.summary}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 380, overflowY: 'auto' }}>
            {roadmap.data.milestones.map((m, i) => (
              <div key={m.id} style={{ border: `1px solid ${C.border}`, borderRadius: 10, padding: '14px 16px', background: C.bg0 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: m.description ? 4 : 8 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: C.t3 }}>{i + 1}</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: C.t1 }}>{m.title}</span>
                  <span style={{ fontSize: 11.5, color: C.t3, marginLeft: 'auto' }}>{m.tasks.length} task{m.tasks.length === 1 ? '' : 's'}</span>
                </div>
                {m.description && (
                  <p style={{ fontSize: 12.5, color: C.t3, lineHeight: 1.5, marginBottom: 8 }}>{m.description}</p>
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {m.tasks.map(t => (
                    <div key={t.id} style={{ display: 'flex', gap: 8, fontSize: 12.5, color: C.t2 }}>
                      <span style={{ color: C.borderStrong }}>•</span>
                      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {regenerate.isError && (
            <Alert>{(regenerate.error as Error)?.message ?? 'Regenerating the roadmap failed.'}</Alert>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Btn size="lg" onClick={() => confirmPlan.mutate()} disabled={busy || regenerate.isPending} style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
              {busy ? <><Spinner size={14} color="rgba(255,255,255,0.85)" /> Finishing…</> : <>Looks good →</>}
            </Btn>
            <Btn variant="outline" onClick={() => regenerate.mutate()} disabled={regenerate.isPending || busy}>
              {regenerate.isPending ? <><Spinner size={14} /> Regenerating…</> : 'Regenerate'}
            </Btn>
          </div>
        </>
      )}
    </div>
  )
}
