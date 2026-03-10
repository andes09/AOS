# Track F — Sprint Brain Core Service Design

**Date:** 2026-03-10
**Branch:** `track-f-sprint-brain-service`
**Files touched:** `apps/api/src/services/sprint_brain.py`, `apps/api/src/routers/sprint_brain.py`

---

## Overview

Track F enhances the existing Track E Sprint Brain files with three capabilities:

1. **Two-step Claude API pipeline** — separate complexity analysis from assignment generation
2. **Historical data citations** — every assignment recommendation cites specific velocity data
3. **3-sprint minimum gate** — developers without enough history return an "insufficient data" card

The velocity engine (Track D) is consumed read-only. The router coordinator stubs are not touched.

---

## Architecture

```
PlanRequest
    │
    ▼
_get_developer_profiles()  ──► velocity engine profiles (dicts)
    │
    ▼
3-sprint gate ──► eligible_profiles + insufficient_data_devs
    │
    ▼
[Claude Call 1] analyse_tickets
    │  input:  raw tickets only
    │  output: per-ticket {effort, required_skills, complexity_notes, estimated_days}
    ▼
[Claude Call 2] create_sprint_plan
    │  input:  complexity analysis + eligible developer profiles
    │           (profiles include per-type/domain velocity breakdown for citations)
    │  output: assignments with historical citations, confidence scores,
    │           warnings, what_if_dropped
    ▼
SprintBrainOutput
    assignments[]              ← each includes reasoning with historical citation
    insufficient_data_devs[]   ← developers who failed the gate
    confidence_score
    summary
    warnings
    what_if_dropped{}
```

---

## Data Structures

### Developer profile dict (expected from velocity engine)

```python
{
    "developer_id": "alice",
    "display_name": "Alice",
    "sprint_count": 5,           # max sample_count across all profiles — gate input
    "velocity_breakdown": [      # per-type/domain rows for Call 2 citations
        {"ticket_type": "bug", "domain": "backend", "avg_pts": 8.2, "sample_count": 4},
        {"ticket_type": "story", "domain": "frontend", "avg_pts": 5.0, "sample_count": 2},
    ],
    "safe_capacity_pts": 24.0,   # from velocity engine's adjusted budget
}
```

`Domain` values are fixed by the velocity engine enum: `frontend`, `backend`, `infra`.

> **Future:** Allow teams to define custom domains (tracked in `tasks/todo.md`).

### `SprintBrainOutput` (updated)

```python
@dataclass
class SprintBrainOutput:
    assignments: list[dict]            # [{ticket_id, developer_id, reasoning, confidence, story_points?}]
    confidence_score: float            # 0.0–1.0
    summary: str
    warnings: list[str]
    what_if_dropped: dict[str, float]  # ticket_id → new overall confidence if dropped
    insufficient_data_devs: list[dict] # NEW: [{developer_id, display_name, sprints_recorded, sprints_needed}]
```

---

## 3-Sprint Gate

**Rule:** A developer is eligible if `max(sample_count across all their velocity_breakdown entries) >= 3`.
Developers with no profiles at all, or whose highest sample_count is < 3, fail the gate.

**Gate output:**
```python
{"developer_id": "bob", "display_name": "Bob", "sprints_recorded": 1, "sprints_needed": 2}
```

**Edge case:** If all developers fail the gate, raise `RuntimeError` before calling Claude — no plan can be generated.

---

## Claude Call 1 — Ticket Complexity Analysis

**Tool:** `analyse_tickets`

**System prompt focus:** Senior engineer estimating effort. No developer context. No capacity logic.

**Per-ticket output schema:**
```json
{
  "ticket_id": "string",
  "effort": "low | medium | high",
  "required_skills": ["string"],
  "complexity_notes": "string",
  "estimated_days": "number"
}
```

**Model:** `claude-opus-4-6`
**max_tokens:** 4096 (complexity analysis is short)

---

## Claude Call 2 — Assignment Generation

**Tool:** `create_sprint_plan` (existing schema, unchanged)

**System prompt focus:** Expert sprint planner. Must cite specific historical data in every assignment reasoning. Conservative — 80% confidence sprint beats an overloaded one.

**User message includes a velocity breakdown table per eligible developer:**
```
### Alice  (safe capacity: 24 pts)
  backend / bug    → 4 sprints, avg 8.2 pts/sprint
  frontend / story → 2 sprints, avg 5.0 pts/sprint
```

**Citation instruction in system prompt:**
> "For each assignment, cite the specific historical data you are using. Example: 'Based on 4 backend bug sprints averaging 8.2 pts, this fits within Alice's safe capacity of 24 pts.'"

**Model:** `claude-opus-4-6`
**max_tokens:** 16384 (full plan with reasoning)

---

## Router Changes

`routers/sprint_brain.py` response includes `insufficient_data_devs` alongside assignments:

```python
{
    "team_id": "...",
    "sprint_start": "...",
    "assignments": [...],
    "confidence_score": 0.85,
    "summary": "...",
    "warnings": [...],
    "what_if_dropped": {...},
    "insufficient_data_devs": [...]   # NEW field
}
```

The what-if endpoint (`/what-if`) also includes `insufficient_data_devs` in `revised_plan`.

---

## Constraints

- BYOK: Anthropic API key always supplied by caller, never from environment
- Router coordinator stubs (`_get_anthropic_key`, `_get_developer_profiles`, `_get_candidate_tickets`) are not modified
- Velocity engine logic is not duplicated — profiles consumed as dicts
- Domain enum values (`frontend`, `backend`, `infra`) are fixed by Track D
