// Wraps start -> purpose -> chat -> generate as one small state union, so
// ProjectCreatePage can render off a single `state.step` switch instead of
// juggling several independent loading/error flags.

import { useCallback, useState } from 'react'
import { useApi } from '../../../lib/api'
import { useProjectMutations } from './useProjects'
import type { ProjectPurpose } from '../../onboarding-v2'
import type { ProjectSummary } from '../types'

export type ProjectCreationState =
  | { step: 'idle' }
  | { step: 'purpose'; sessionId: string }
  | { step: 'chat'; sessionId: string }
  | { step: 'generating'; sessionId: string }
  | { step: 'done'; project: ProjectSummary }
  | { step: 'error'; message: string }

export function useProjectCreation() {
  const { put, post } = useApi()
  const { startCreation } = useProjectMutations()
  const [state, setState] = useState<ProjectCreationState>({ step: 'idle' })

  const start = useCallback(async () => {
    try {
      const { sessionId } = await startCreation.mutateAsync()
      setState({ step: 'purpose', sessionId })
    } catch (e) {
      setState({ step: 'error', message: e instanceof Error ? e.message : 'Could not start' })
    }
  }, [startCreation])

  const choosePurpose = useCallback(
    async (sessionId: string, purpose: ProjectPurpose) => {
      try {
        await put(`/api/projects/sessions/${sessionId}/purpose`, { purpose })
        setState({ step: 'chat', sessionId })
      } catch (e) {
        setState({ step: 'error', message: e instanceof Error ? e.message : 'Could not save purpose' })
      }
    },
    [put],
  )

  const generate = useCallback(
    async (sessionId: string) => {
      setState({ step: 'generating', sessionId })
      try {
        const project = await post<ProjectSummary>(`/api/projects/sessions/${sessionId}/generate`, {})
        setState({ step: 'done', project })
      } catch (e) {
        setState({ step: 'error', message: e instanceof Error ? e.message : 'Could not generate your roadmap' })
      }
    },
    [post],
  )

  const reset = useCallback(() => setState({ step: 'idle' }), [])

  return { state, start, choosePurpose, generate, reset, isStarting: startCreation.isPending }
}
