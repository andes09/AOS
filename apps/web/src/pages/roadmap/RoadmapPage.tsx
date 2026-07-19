/**
 * Roadmap — the app's landing surface after onboarding.
 *
 * Deliberately unstyled: this page proves the features/roadmap barrel
 * end-to-end (generate → milestone/task tree → status toggles) and nothing
 * else. Visual design is Phase B. Everything it knows about the roadmap comes
 * through the barrel — no direct fetches, no bespoke API calls.
 */
import { useRoadmap, useTaskMutations } from '../../features/roadmap'
import type { RoadmapProject, TaskStatus } from '../../features/roadmap'

/** Check-off cycle: each click advances the status one step. */
const NEXT_STATUS: Record<TaskStatus, TaskStatus> = {
  todo: 'in_progress',
  in_progress: 'done',
  done: 'todo',
}

function ProjectTree({ project }: { project: RoadmapProject }) {
  const { setTaskStatus, updateTask } = useTaskMutations()

  return (
    <div>
      <h1>{project.name}</h1>
      {project.summary && <p>{project.summary}</p>}
      {project.milestones.map(milestone => (
        <section key={milestone.id} aria-label={milestone.title}>
          <h2>{milestone.title}</h2>
          {milestone.description && <p>{milestone.description}</p>}
          <ul>
            {milestone.tasks.map(task => (
              <li key={task.id}>
                <button
                  onClick={() => setTaskStatus(task.id, NEXT_STATUS[task.status])}
                  aria-label={`${task.title}: ${task.status}`}
                  disabled={updateTask.isPending}
                >
                  {task.status}
                </button>{' '}
                {task.title}
                {task.scheduledDate && <span> — {task.scheduledDate}</span>}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

export function RoadmapPage() {
  const { state, generate, regenerate } = useRoadmap()

  switch (state.status) {
    case 'loading':
      return <p>Loading roadmap…</p>

    case 'empty':
      return (
        <div>
          <h1>No roadmap yet</h1>
          <p>Generate a plan from your onboarding brief to get started.</p>
          <button onClick={() => generate.mutate()}>Generate roadmap</button>
        </div>
      )

    case 'generating':
      return (
        <div>
          <p role="status">Generating your roadmap… this can take a minute.</p>
          {state.project && <ProjectTree project={state.project} />}
        </div>
      )

    case 'error':
      return (
        <div>
          <p role="alert">Something went wrong: {state.error.message}</p>
          <button onClick={() => (state.project ? regenerate.mutate() : generate.mutate())}>
            Try again
          </button>
          {state.project && <ProjectTree project={state.project} />}
        </div>
      )

    case 'ready':
      return (
        <div>
          <ProjectTree project={state.project} />
          <button onClick={() => regenerate.mutate()}>Regenerate roadmap</button>
        </div>
      )
  }
}
