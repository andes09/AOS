// Roadmap — headless public contract.
//
// This barrel is the integration surface for any roadmap UI: types, a
// framework-agnostic client, and React hooks. Nothing here renders or styles
// anything.
//
// Typical wiring:
//   const { state, generate, regenerate, regenerateMilestone } = useRoadmap()
//   const { updateTask, deleteTask, setTaskStatus } = useTaskMutations()
//
// Render from state.status: 'loading' | 'empty' | 'generating' | 'ready' |
// 'error'. Task edits (check off, retitle, reschedule, reorder, delete) are
// optimistic — the tree updates instantly and rolls back on server rejection.
//
// Non-React consumers can use createRoadmapApi(getToken) directly.

export * from './types'
export { createRoadmapApi, RoadmapApiError } from './api'
export type { RoadmapApi, GetToken } from './api'
export { useRoadmap, ROADMAP_KEY } from './hooks/useRoadmap'
export { useTaskMutations } from './hooks/useTaskMutations'
export { useRoadmapApi } from './hooks/useRoadmapApi'
