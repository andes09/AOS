# Import Artifacts — bring an existing plan into Omada

## Context

Today the only way to seed a project in Omada is the onboarding chat interview
(`github_connect → profile → purpose → idea_chat → done`): the AI asks
questions, extracts a `ProjectBrief`, and later (on `/app/roadmap`) the user
clicks "Generate roadmap" to turn that brief into `Project → Milestone →
Task` rows.

Many founders already have a plan — a Buildpad validation summary, a ChatPRD
PRD, a raw ChatGPT/Claude brainstorm transcript, a README — and re-explaining
it to a chatbot is friction, not value. This feature lets them **import**
that artifact instead of chatting: Omada extracts a brief and drafts a
roadmap from it in one shot, the user reviews and accepts/rejects each
proposed milestone, then connects a GitHub repo, then lands in the app with
the project already populated.

Decided with the user: this is a **fork inside onboarding** (not a
standalone post-onboarding flow); broad file support (paste text, `.txt`,
`.md`, `.pdf`, `.docx`); **per-milestone** accept/reject only; the original
uploaded file is **never persisted** — only extracted text + structured
output.

Explicitly out of scope (don't build): a generic diff/patch engine for
re-importing against an *existing* roadmap later (this only ever produces
the org's *first* roadmap, matching today's one-project-per-org model via
`Project.onboarding_session_id` being a unique FK — a natural v2 extension,
not now); blob storage; a background job queue (files are small — parse
synchronously in the request).

## Step machine

```
github_connect → profile → purpose → build_plan → repo_select → done
                                         │
                                         ├─ (mode unset) chooser: "Chat" or "Import a plan"
                                         ├─ mode='chat'   → existing idea_chat sub-flow
                                         └─ mode='import' → new import_artifact sub-flow
```

`steps[]` stays 5 entries; the 4th entry's `id` is one of `build_plan`
(mode not yet chosen), `idea_chat`, or `import_artifact`, depending on
`OnboardingSession.onboarding_path`. This is additive, not a rename — the
existing `idea_chat` step/endpoints are untouched; `build_plan` is just the
new pre-choice state exposed at that position. `repo_select` is a genuinely
new step, skippable (mirrors `github_connect`), and auto-satisfied if the
user never connected GitHub in the first place.

`build_plan_done` unifies both paths on one signal: `session.status ==
"completed"` (already true for chat via `/chat/complete`; import's new
`/apply` endpoint sets the same field). No path-switching UI in v1 — once
`onboarding_path` is set and its sub-flow has started, it's fixed for the
session.

## Backend

### Migration `apps/api/alembic/versions/0032_artifact_import.py` (`down_revision = '0031'`)

New nullable columns on `onboarding_sessions`: `onboarding_path`
(`VARCHAR(20)`), `raw_import_text` (`TEXT` — extracted text only, kept for
debugging/audit, never the original file), `proposed_roadmap` (`JSON`/`JSONB`
— the analysis output: `{projectName, summary, milestones: [{title,
description, tasks: [...]}]}`, no accept state persisted), `import_analyzed_at`
(`TIMESTAMP`), `selected_github_repo_full_name` (`VARCHAR(255)`),
`repo_select_skipped_at` (`TIMESTAMP`). New nullable column on `projects`:
`github_repo_full_name` (`VARCHAR(255)`).

*(Note: `docs/plans/2026-07-20-master-dashboard.md` also reserves `0032`/`0033` — that plan isn't implemented yet. Whichever lands first claims `0032`; the other rebases its `down_revision`.)*

### Dependencies (`apps/api/pyproject.toml`)

Add `python-multipart` (required for FastAPI `UploadFile`), `pypdf` (PDF text
extraction), `python-docx` (`.docx` text extraction). None currently exist in
the codebase — this is genuinely greenfield.

### Shared roadmap-shape module — `apps/api/src/services/roadmap_shapes.py` (new, small extraction)

Move `_MAX_MILESTONES`, `_MAX_TASKS_PER_MILESTONE`, `_MAX_DAY_OFFSET` and the
validation functions `_validated_task` / `_validated_milestone` /
`_validated_milestones` out of `roadmap_generator.py` into this shared
module (drop the leading underscores — they're public now), and have
`roadmap_generator.py` import them. This is a plain move, not a rewrite.
Justification: as soon as a second call site (`artifact_import.py`) needs
the exact same validate-before-persist contract, duplicating it violates
"minimal impact" — extracting is the smaller change of the two options.

Also extract a tiny `create_project_with_milestones(session, team, name,
summary, purpose, milestones, db)` helper (the "make a `Project` row +
`_persist_milestones`" block currently inlined in
`roadmap_generator.generate_roadmap`) into the same module, and have both
`generate_roadmap` and the new import-apply endpoint call it — again, same
"used twice → extract" rule, not new abstraction for its own sake.

### New router `apps/api/src/routers/artifact_import.py` (prefix `/api/onboarding/v2`)

- **`POST /import/analyze`** — multipart form: `text` (pasted string) and/or
  `files: list[UploadFile]`. Validates: ≤5 files, ≤10MB each, content-type
  allowlist (`text/plain`, `text/markdown`, `application/pdf`,
  `application/vnd.openxmlformats-officedocument.wordprocessingml.document`),
  extracts text per file (plain decode for txt/md, `pypdf` for pdf,
  `python-docx` for docx), concatenates with `--- FILE: <name> ---`
  delimiters, caps total extracted text (~60k chars) with truncation +
  warning if exceeded. If a PDF yields ~0 extracted chars (scanned/image
  PDF), 422 with a clear message ("couldn't extract text — try pasting it
  directly") rather than sending near-empty content to the model.

  Makes **one forced-tool Claude call** (reuses `roadmap_generator.resolve_api_key`
  — BYOK-first Anthropic, same as roadmap generation, not the Groq-only
  pattern idea_interview uses) against a new tool `analyze_project_artifact`
  whose schema is `anthropic_tool_properties()` (from `project_brief.py`,
  unchanged) merged with the existing `milestones` array shape from
  `roadmap_shapes`. System prompt combines: (a) `project_brief`'s field
  descriptions for the extraction half, (b) `roadmap_generator._SYSTEM_PROMPT`
  + `_system_prompt(purpose)` for the drafting half, plus one added
  instruction — **if the source document already describes phases,
  milestones, or a feature list, structure the roadmap around those instead
  of inventing a different structure; only add standard engineering
  scaffolding (setup, testing, deploy) where the document is silent.**

  **Prompt-injection hygiene**: the extracted text is wrapped in a clearly
  delimited `<uploaded_document>` block with an explicit instruction to
  treat its contents as source material only, never as instructions to
  follow; the call uses forced `tool_choice` (no free-form agency) with no
  other tools available — same posture `idea_interview` and
  `roadmap_generator` already use for untrusted/user-supplied content, just
  called out explicitly since this is the first path where raw external
  document text (not user-typed chat) reaches a prompt.

  Output validated via `roadmap_shapes.validated_milestones` before
  anything is stored. Persists: `session.raw_import_text`,
  `session.proposed_roadmap` (validated milestones + projectName/summary,
  no accept flags — review state lives client-side), `session.project_brief`
  merged via `idea_interview.merge_brief` (imported, not moved — minimal
  diff), `session.import_analyzed_at`. Cost-tracked via
  `record_generation_cost("artifact_import_analyze", usage, ...)` — no new
  registration needed, matches the existing 3-line-per-call-site pattern.
  Truncation risk: brief+roadmap in one call is more output than
  `roadmap_generator` alone produces (which already needed `_MAX_TOKENS=8192`
  to avoid truncation); start with one call reusing that same limit, and if
  testing shows truncation, fall back to two sequential forced-tool calls
  (extract brief, then draft roadmap from it) — same pattern
  `generate_roadmap` already uses.

- **`GET /import`** — returns `{analyzed, projectName, summary, milestones,
  missingFields}` where `missingFields` is `idea_interview.missing_fields()`
  run against the merged brief, so the review screen knows exactly which
  fields to ask for manually.

- **`POST /import/apply`** — body `{acceptedMilestoneIndexes: number[],
  briefOverrides?: object}`. 409 if no `proposed_roadmap` yet; 422 if
  `acceptedMilestoneIndexes` is empty (must accept at least one milestone).
  Merges `briefOverrides` into `session.project_brief` (fills any
  `missingFields` gaps the user typed in), filters `proposed_roadmap.milestones`
  to the accepted indexes, calls `roadmap_shapes.create_project_with_milestones`
  (same helper `generate_roadmap` uses) to create `Project` +
  `Milestone`/`Task` rows from just that subset. If
  `session.selected_github_repo_full_name` is already set (repo picked
  before this point isn't possible given step order, but defensive), copies
  it onto the new `project.github_repo_full_name`. Sets `session.status =
  "completed"`, `session.completed_at`. No LLM call here — analysis already
  happened, this is a DB write. Returns full onboarding state.

### `onboarding_v2.py` additions

- **`PUT /plan-source`** — body `{source: 'chat'|'import'}`, sets
  `session.onboarding_path` (mirrors `PUT /purpose`'s shape exactly).
- **`PUT /repo`** — body `{repoFullName: string}`, sets
  `session.selected_github_repo_full_name`; if a `Project` already exists
  for this session (true on the import path, since `/apply` already ran),
  also sets `project.github_repo_full_name` immediately. On the chat path
  no `Project` exists yet at this point — `generate_roadmap` picks up
  `session.selected_github_repo_full_name` and copies it onto the new
  `Project` at creation time (one new line there).
- **`POST /repo/skip`** — sets `session.repo_select_skipped_at`, mirrors
  `github/skip`.
- **`_build_state()`**: add `onboardingPath`, `importArtifact` (populated
  once analyzed — thin wrapper around the `artifact_import` GET payload so
  the single state hook still covers everything), and `repo: {selected,
  skipped, available}` (`available = bool(connection)`) to the response.
  Extend the `done_flags` list with the branch-aware 4th entry and the new
  `repo_select` entry as described above.

### Tests

Extend `apps/api/tests/test_onboarding_v2.py` for `plan-source`/`repo`
endpoints and the branching `steps[]`/`currentStep` logic. New
`apps/api/tests/test_artifact_import.py`: analyze from pasted text (mocked
Anthropic call) and from each file type; rejected file type/size; PDF with
no extractable text → 422; apply with a subset of milestones accepted
creates exactly those `Milestone`/`Task` rows; apply with zero accepted →
422; missing-fields flow via `briefOverrides`; repo selection before vs.
after `Project` exists.

## Frontend (mirrors the existing headless-layer pattern exactly)

### `apps/web/src/features/onboarding-v2/`

- `types.ts` — extend `OnboardingState` with `onboardingPath`,
  `importArtifact: ImportArtifactState | null`, `repo: RepoState`; add
  `ProposedMilestone`, `ImportArtifactState`, `RepoState` types matching the
  backend shapes above exactly (per this repo's existing rule: `types.ts` is
  the source of truth, kept in lockstep with backend tests).
- `api.ts` — add `setPlanSource`, `analyzeImport(formData)` (multipart,
  the one place this client sends non-JSON), `getImportState`,
  `applyImport`, `setRepo`, `skipRepo`. Finally wire up `listGithubRepos`
  (defined in this file already, currently dead code per prior exploration).
- `hooks/` — new `useImportArtifact.ts` (mutations for analyze/apply; local
  accept/reject state for the review list lives here as plain React state,
  not round-tripped to the server per toggle — only the final decision is
  sent on apply) and `useRepoSelect.ts` (wraps `listGithubRepos` +
  `setRepo`/`skipRepo`). Extend `useOnboardingState.ts` with a
  `setPlanSource` mutation alongside the existing ones.

### `apps/web/src/pages/onboarding-v2/steps/`

New step components, styled to match `PurposeStep.tsx`'s existing
card/radio pattern:

- `PlanSourceStep.tsx` — two-card chooser ("Chat with AI" / "Import a
  plan"), same visual language as `PurposeStep`.
- `ImportArtifactStep.tsx` — upload dropzone + paste-text textarea →
  "Analyze" → review screen: one card per proposed milestone (title,
  description, task count) with an accept/reject toggle, defaulting to
  accepted; a small inline form for any `missingFields`; "Apply" button
  (disabled until ≥1 milestone accepted).
- `RepoSelectStep.tsx` — searchable list from `listGithubRepos` (paginated),
  "Connect this repo" / "Skip for now". If GitHub was skipped earlier,
  render nothing and auto-advance (state already marks this step done).

Update the `state.currentStep === 'x' && <XStep/>` switch (in
`OnboardingV2Page.tsx` or wherever it lives) to add the three new cases;
`IdeaChatStep.tsx` and its wiring are untouched.

### Docs

Update `docs/onboarding-v2-frontend-integration.md`: describe the branch at
`build_plan`, the new step ids, the new hooks, and the repo-connect step —
this is the partner's integration contract and needs to stay accurate.

## Verification

1. `cd apps/api && alembic upgrade head` applies cleanly.
2. Backend: `pytest tests/test_onboarding_v2.py tests/test_artifact_import.py tests/test_roadmap.py` — new tests green, existing onboarding/roadmap suites unaffected (regression check on the shared `roadmap_shapes` extraction).
3. Manual end-to-end locally: paste a sample PRD text → Analyze → confirm extracted brief fields and proposed milestones render → uncheck one milestone → Apply → confirm `/app/roadmap` shows only the accepted milestones with tasks scheduled from today (same as chat-path output shape) → connect a repo → confirm `projects.github_repo_full_name` persisted in the DB.
4. Regression: run the existing chat path end to end unchanged, including skipping GitHub and skipping repo-select, confirming it still reaches `done` and `/app`.
5. Try a rejected file type and an oversized file → confirm clean 422s, not 500s.
6. Try a scanned/image-only PDF → confirm the "couldn't extract text" 422, not a near-empty LLM call.
