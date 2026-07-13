/**
 * Onboarding v2 — reference UI.
 *
 * Deliberately unstyled plain HTML: this page exists to prove the headless
 * layer end-to-end and document how to wire it. The production UI replaces
 * this file entirely and consumes the same hooks from
 * `src/features/onboarding-v2` — nothing else knows about this page.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  useGithubConnect,
  useIdeaChat,
  useOnboardingState,
} from '../features/onboarding-v2'
import type { ProjectPurpose } from '../features/onboarding-v2'

export function OnboardingV2Page() {
  const { state, isLoading, error, skipGithub, saveProfile, savePurpose, complete } =
    useOnboardingState()

  if (isLoading) return <main><p>Loading onboarding…</p></main>
  if (error) return <main><p role="alert">Failed to load onboarding: {String(error)}</p></main>
  if (!state) return null

  return (
    <main>
      <h1>Welcome to Omada</h1>
      <ol>
        {state.steps.map(step => (
          <li key={step.id} aria-current={step.status === 'current'}>
            {step.id} — {step.status}
          </li>
        ))}
      </ol>

      {state.currentStep === 'github_connect' && (
        <GithubStep onSkip={() => skipGithub.mutate()} skipping={skipGithub.isPending} />
      )}
      {state.currentStep === 'profile' && (
        <ProfileStep
          onSave={(name, phone) => saveProfile.mutate({ name, phone })}
          saving={saveProfile.isPending}
          saveError={saveProfile.error?.message ?? null}
        />
      )}
      {state.currentStep === 'purpose' && (
        <PurposeStep
          onSave={purpose => savePurpose.mutate(purpose)}
          saving={savePurpose.isPending}
        />
      )}
      {state.currentStep === 'idea_chat' && <IdeaChatStep />}
      {state.currentStep === 'done' && <DoneStep onFinish={() => complete.mutateAsync()} />}
    </main>
  )
}

function GithubStep({ onSkip, skipping }: { onSkip: () => void; skipping: boolean }) {
  const { connect, redirectResult } = useGithubConnect('/onboarding')
  return (
    <section aria-label="Connect GitHub">
      <h2>Connect your GitHub</h2>
      <p>Connecting GitHub lets the roadmap AI read your repos to plan around what already exists.</p>
      {redirectResult?.outcome === 'error' && (
        <p role="alert">GitHub connection failed ({redirectResult.reason}). Try again.</p>
      )}
      <button onClick={() => connect.mutate()} disabled={connect.isPending}>
        Connect GitHub
      </button>
      <button onClick={onSkip} disabled={skipping}>
        Skip for now
      </button>
    </section>
  )
}

function ProfileStep({
  onSave,
  saving,
  saveError,
}: {
  onSave: (name: string, phone: string) => void
  saving: boolean
  saveError: string | null
}) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  return (
    <section aria-label="Your details">
      <h2>Tell us who you are</h2>
      <form
        onSubmit={e => {
          e.preventDefault()
          onSave(name, phone)
        }}
      >
        <label>
          Name
          <input value={name} onChange={e => setName(e.target.value)} required />
        </label>
        <label>
          Phone
          <input
            type="tel"
            value={phone}
            onChange={e => setPhone(e.target.value)}
            placeholder="+1 555 123 4567"
            required
          />
        </label>
        {saveError && <p role="alert">{saveError}</p>}
        <button type="submit" disabled={saving}>
          Continue
        </button>
      </form>
    </section>
  )
}

const PURPOSE_OPTIONS: { value: ProjectPurpose; label: string; hint: string }[] = [
  { value: 'hobby', label: 'A hobby project', hint: "Something for fun, on my own time" },
  { value: 'startup', label: 'A startup', hint: 'A real product I want to launch and grow' },
  { value: 'learning', label: 'Learning', hint: 'Mainly to build a skill or portfolio piece' },
]

function PurposeStep({
  onSave,
  saving,
}: {
  onSave: (purpose: ProjectPurpose) => void
  saving: boolean
}) {
  return (
    <section aria-label="What is this project for">
      <h2>What's this project for?</h2>
      <p>This shapes how we plan it — a hobby, a startup, and a learning project all need different roadmaps.</p>
      <div role="radiogroup" aria-label="Project purpose">
        {PURPOSE_OPTIONS.map(opt => (
          <button key={opt.value} disabled={saving} onClick={() => onSave(opt.value)}>
            <strong>{opt.label}</strong>
            <div>{opt.hint}</div>
          </button>
        ))}
      </div>
    </section>
  )
}

function IdeaChatStep() {
  const chat = useIdeaChat()
  const [draft, setDraft] = useState('')

  const submit = () => {
    const content = draft.trim()
    if (!content) return
    setDraft('')
    void chat.send(content)
  }

  if (chat.isLoading) return <section><p>Starting the interview…</p></section>

  return (
    <section aria-label="Tell us about your idea">
      <h2>Tell us about your idea</h2>
      <ul aria-label="conversation">
        {chat.messages.map(m => (
          <li key={m.id} data-role={m.role}>
            <strong>{m.role === 'assistant' ? 'Omada' : 'You'}:</strong> {m.content}
          </li>
        ))}
        {chat.isStreaming && (
          <li data-role="assistant" aria-busy="true">
            <strong>Omada:</strong> {chat.streamingReply}
          </li>
        )}
      </ul>
      {chat.error && <p role="alert">{chat.error}</p>}
      <form
        onSubmit={e => {
          e.preventDefault()
          submit()
        }}
      >
        <input
          aria-label="Your message"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          disabled={chat.isStreaming || chat.status === 'completed'}
        />
        <button type="submit" disabled={chat.isStreaming || chat.status === 'completed'}>
          Send
        </button>
      </form>
      {chat.status !== 'completed' && chat.messages.length > 2 && (
        <button onClick={() => void chat.complete()}>That's enough — finish up</button>
      )}
    </section>
  )
}

function DoneStep({ onFinish }: { onFinish: () => Promise<unknown> }) {
  const navigate = useNavigate()
  const [finishing, setFinishing] = useState(false)
  return (
    <section aria-label="All set">
      <h2>You're all set</h2>
      <button
        disabled={finishing}
        onClick={async () => {
          setFinishing(true)
          try {
            await onFinish()
            navigate('/app')
          } finally {
            setFinishing(false)
          }
        }}
      >
        Go to your project
      </button>
    </section>
  )
}
