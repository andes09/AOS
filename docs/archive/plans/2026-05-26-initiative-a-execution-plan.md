# Initiative A — Execution Plan

**Date**: 2026-05-26
**Source spec**: `tasks/todo.md` → "Initiative A — Identifier Associations + Skill Intensity Routing"
**Status**: planning approved (pending kickoff)

## Decisions locked in

- **Skill ratings**: self-declared in onboarding (new sliders in `MemberForm`), auto-recalibrate post-sprint via M8c
- **Bootstrap scan**: cap to top-200 most-frequent tokens per team, batch 50/Claude call
- **Tokenizer**: CamelCase requires ≥2 segments OR explicit punctuation (`.`, `_`, `-`, `/`)
- **First scan**: auto-persist all rows; surface confidence <0.6 in Glossary UI for review
- **Reason chip on overrides**: optional; one-time tooltip nudge on first 3 overrides
- **Override → assignee**: mutates `Ticket.assignee_id` immediately (single source of truth)
- **Recalibration trigger**: ≥3 same-direction overrides in trailing 90 days (skills + identifiers)

## Codebase reference (verified 2026-05-26)

| Concern | Path | Notes |
|---|---|---|
| Sprint Brain `_get_developer_profiles` | `apps/api/src/services/sprint_brain.py:434-540` | Returns dev profiles; `velocity_breakdown` is a single-row stub at L530-537 |
| Sprint Brain `_SPRINT_PLAN_TOOL` | `apps/api/src/services/sprint_brain.py:32-100` | Assignment field shape at L41-61 |
| Sprint Brain `_SYSTEM_PROMPT` | `apps/api/src/services/sprint_brain.py:163-183` | Where routing rules will be added |
| Sprint Brain `_build_assignment_message` | `apps/api/src/services/sprint_brain.py:351-426` | Per-ticket prompt assembly |
| Scope Cop `_SCOPE_COP_TOOL` | `apps/api/src/services/scope_cop.py:50-101` | 4 equally-weighted criteria today |
| Scope Cop `analyze_tickets` | `apps/api/src/services/scope_cop.py:222-341` | Upserts to `ticket_analyses` ON CONFLICT |
| Developer ORM | `apps/api/src/models/developer.py` | Has `domain_strengths`, `seniority`, `meeting_hours_bucket` (added in 0015); `skill_ratings` jsonb to be added in 0017 |
| Onboarding | `apps/web/src/pages/onboarding/team-setup/{AddMembersStep,MemberForm,types}.tsx` | `MemberDraft` type at `types.ts:1-23` |
| Highest existing migration | `apps/api/alembic/versions/0016_billing.py` | Next free: 0017, 0018, 0019 |
| Sprint Planner | `apps/web/src/pages/SprintPlannerPage.tsx` | Renders ScopeCopPanel, TicketList; pills will slot into TicketList |
| Settings | `apps/web/src/pages/SettingsPage.tsx` | Monolithic component; Glossary will be a new sub-page |
| Ticket ORM | `apps/api/src/models/ticket.py` | `assignee_id` is source of truth for velocity attribution |

## Subagent waves (moderate parallelism)

### Wave 0 — Foundations (M1) — 3 parallel
| ID | Task | Files | Depends |
|---|---|---|---|
| SA-1 | Alembic 0017 + ORM models | `apps/api/alembic/versions/0017_identifier_associations.py`; `apps/api/src/models/identifier.py` (TeamIdentifier, TicketSkillAnalysis); add `developers.skill_ratings` jsonb | — |
| SA-2 | Regex tokenizer + normalizer + tests | `apps/api/src/services/identifier_extraction.py`; `apps/api/tests/test_identifier_extraction.py` | — |
| SA-3 | Bootstrap data-source helper | Closed-sprint tickets + epics for `team_id` (joins `sprints` where `status=COMPLETED` → `sprint_tickets` → Jira description fetch) | — |

### Wave 1 — Classifier + Intensity (M2 + M3) — 3 parallel
| ID | Task | Files | Depends |
|---|---|---|---|
| SA-4 | Claude classifier service | `apps/api/src/services/identifier_classifier.py` (tool_use, structured output; pattern from `scope_cop.py:50-101`) | Wave 0 |
| SA-5 | Identifiers router (scan + CRUD) | `apps/api/src/routers/identifiers.py` — POST `/api/identifiers/scan`, GET list, PATCH, DELETE; lead role gated | SA-1, SA-2, SA-3 |
| SA-6 | Intensity inference service | `apps/api/src/services/skill_intensity.py` (density + verb table + effort multiplier) + tests; persists to `ticket_skill_analyses` | SA-1 |

### Wave 2 — Sprint Brain + Scope Cop + Onboarding (M4 + M5 + onboarding slice of M6) — 3 parallel (distinct files)
| ID | Task | Files | Depends |
|---|---|---|---|
| SA-7 | Sprint Brain integration | `apps/api/src/services/sprint_brain.py` — extend `_get_developer_profiles` (L434-540) to read `skill_ratings`; replace stubbed `velocity_breakdown` (L530-537) with real per-skill aggregation from `ticket_skill_analyses`; inject `skill_vector` into `_build_assignment_message` (L351-426); extend `_SPRINT_PLAN_TOOL` (L41-61) with `skill_match_reasoning`; update `_SYSTEM_PROMPT` (L163-183) with routing rules | Wave 1 |
| SA-8 | Scope Cop 5th criterion | `apps/api/src/services/scope_cop.py` — extend `_SCOPE_COP_TOOL` (L50-101) with `stack_alignment`; pass `matched_identifiers` count from `ticket_skill_analyses`; flag zero-match tickets as `needs_work` | Wave 1 |
| SA-9 | Onboarding skill_ratings capture | `apps/web/src/pages/onboarding/team-setup/{MemberForm.tsx, types.ts, AddMembersStep.tsx}` — per-skill sliders driven by team `tech_stack`; persist via existing team-setup POST | SA-1 (column exists) |

### Wave 3 — UI surfaces (M6 remainder) — 3 parallel
| ID | Task | Files |
|---|---|---|
| SA-10 | Team Glossary page | New `apps/web/src/pages/settings/TeamGlossaryPage.tsx` + slot into `SettingsPage.tsx` nav; table, inline skill/domain edit, low-confidence badge, bulk delete |
| SA-11 | Sprint Planner enhancements | `apps/web/src/pages/SprintPlannerPage.tsx` — per-ticket intensity pills color-coded; matched-identifiers list in ticket detail with link to glossary |
| SA-12 | Onboarding scan trigger | Hook into existing `import_jira_sprint_history` completion path; progress indicator; fires POST `/api/identifiers/scan` |

### Wave 4 — Refresh + Override capture + Telemetry (M7 + M8a + M8d) — 3 parallel (distinct files)
| ID | Task | Files |
|---|---|---|
| SA-13 | M7 incremental refresh | Sprint-close hook: scan new tickets since `last_seen_at`; age-out `confidence *= 0.9` per refresh; prune <0.1; idempotency tests |
| SA-14 | M8a override capture | Alembic 0018: `sprint_plan_overrides`; ORM `sprint_plan_override.py`; patch assignment-edit endpoint in `sprints` router to write override row + mutate `Ticket.assignee_id`; UI reason chip (optional + one-time tooltip) |
| SA-15 | M8d plan-quality telemetry | `apps/api/src/services/plan_quality.py`; add `plan_override_rate`, `plan_overrides_by_reason` jsonb columns to Sprint row (squashed into 0018); Exec Dashboard trailing-8-sprint chart + `>0.5` alert |

### Wave 5 — Feedback loop (M8b + M8c) — 2 subagents
| ID | Task | Files | Depends |
|---|---|---|---|
| SA-16 | M8b prompt context | `sprint_brain.py::_build_assignment_message` — append "Previous Sprint Overrides" section (last 1–2 sprints); update `_SYSTEM_PROMPT` to factor recurring patterns; empty-overrides → section omitted | Wave 4 (SA-14) |
| SA-17 | M8c recalibration backend + UI | Alembic 0019: `recalibration_proposals`; `apps/api/src/services/override_analyzer.py` (≥3 same-direction overrides in 90 days → proposal; identifier misclass same threshold); router GET pending / POST approve / dismiss; Settings → "Calibration Suggestions" card UI with evidence links; on approve → mutate `developers.skill_ratings` or `team_identifiers.skill` + audit row | Wave 4 (SA-14) |

### Wave 6 — Wiring + verification (single coordinated pass)
- End-to-end manual smoke: onboarding → bootstrap scan → intensity inference → plan generation → Scope Cop run → assignment with `skill_match_reasoning` → reassignment → override row → recalibration proposal
- Run omada-simulator on `balanced` archetype with intensity routing enabled — confirm `plan_ok_pct` ≥ baseline (verification gate from doc)
- Spot-check 5 real assignments for `skill_match_reasoning` quality
- Confirm no regression on Scope Cop `analyzed_at` cache behavior
- Verify Initiative B migrations still align (B planned 0019/0020 → will need to bump to 0020/0021 if both ship)

## Wiring & dependency map

```
Wave 0 (M1 schema/tokenizer)
    │
    ├─► Wave 1 ─► classifier (SA-4) ─┐
    │            router (SA-5)       │
    │            intensity (SA-6) ───┼─► ticket_skill_analyses populated
    │                                │
    └────────────────────────────────┤
                                     ▼
                          Wave 2 ─► sprint_brain consumes skill_vector + skill_ratings (SA-7)
                                    scope_cop consumes matched_identifiers (SA-8)
                                    onboarding writes skill_ratings (SA-9)
                                              │
                                              ▼
                                    Wave 3 ─► UI surfaces (glossary, planner pills, scan trigger)
                                              │
                                              ▼
                                    Wave 4 ─► overrides captured (SA-14)
                                              telemetry (SA-15)
                                              refresh (SA-13)
                                              │
                                              ▼
                                    Wave 5 ─► overrides fed back into prompt (SA-16)
                                              recalibration proposals → mutate ratings (SA-17)
                                              │
                                              ▼
                                    Wave 6 ─► end-to-end smoke + simulator gate
```

## Risk notes

- **Wave 2 shares `sprint_brain.py` with Wave 5.** Sequenced (Wave 2 = SA-7, Wave 5 = SA-16), no overlap.
- **Migration numbering**: 0017 (Wave 0), 0018 (Wave 4 — overrides + telemetry columns combined), 0019 (Wave 5 — recalibration_proposals). Initiative B's planned 0019/0020 will need to bump if it lands later.
- **Test coverage per wave is the gate to next wave.** No subagent moves on if its tests don't pass.
- **Wave 4 telemetry migration squash**: 0018 carries both `sprint_plan_overrides` table and the Sprint column additions. If split is preferred, bump to 0018 + 0019, and recalibration_proposals shifts to 0020.

## Open implementation flags

1. Squashed 0018 (overrides + telemetry columns) — confirm acceptable, else split.
2. Wave 2 parallelizes onboarding UI (SA-9) with backend Sprint Brain work (SA-7) — safe because SA-9 only needs the `skill_ratings` column from Wave 0.
3. Initiative B's migration numbering will need to shift downstream.
