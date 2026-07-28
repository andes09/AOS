// The Project Hub's data layer: list/group by status, rename, status
// transitions, and starting a new project's creation session.

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useApi } from '../../../lib/api'
import type { ProjectStatus, ProjectSummary } from '../types'

export const PROJECTS_KEY = ['projects'] as const

export function useProjects() {
  const { get } = useApi()
  return useQuery({
    queryKey: PROJECTS_KEY,
    queryFn: () => get<{ projects: ProjectSummary[] }>('/api/projects'),
    select: data => data.projects,
  })
}

export function useProjectMutations() {
  const { post, patch } = useApi()
  const qc = useQueryClient()

  function invalidate() {
    qc.invalidateQueries({ queryKey: PROJECTS_KEY })
  }

  const startCreation = useMutation({
    mutationFn: () => post<{ sessionId: string }>('/api/projects', {}),
  })

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      patch<ProjectSummary>(`/api/projects/${id}`, { name }),
    onSuccess: invalidate,
  })

  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: ProjectStatus }) =>
      patch<ProjectSummary>(`/api/projects/${id}`, { status }),
    onSuccess: invalidate,
  })

  return { startCreation, rename, setStatus }
}
