# Track F — Sprint Brain Core Service Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the existing Sprint Brain service with a two-step Claude API pipeline, a 3-sprint minimum data gate, and historical data citations in every assignment recommendation.

**Architecture:** The existing Track E files (`services/sprint_brain.py`, `routers/sprint_brain.py`) are enhanced in-place. Three functions are added/replaced: a gate function that splits developer profiles into eligible vs. insufficient-data buckets; a first Claude call that analyses ticket complexity; and an updated second call that builds assignment prompts with per-developer velocity breakdown tables so Claude can produce grounded historical citations. The router is extended to include `insufficient_data_devs` in its response shape.

**Tech Stack:** Python 3.12, FastAPI, Anthropic SDK (`anthropic>=0.34.0`), pytest + pytest-asyncio, unittest.mock

**Spec:** `docs/superpowers/specs/2026-03-10-track-f-sprint-brain-service-design.md`

---

## Chunk 1: Branch + 3-Sprint Gate + Output Schema

### Task 1: Create and switch to branch

**Files:**
- No file changes — git only

- [ ] **Step 1: Create the branch**

```bash
cd apps/api
git checkout -b track-f-sprint-brain-service
```

Expected: `Switched to a new branch 'track-f-sprint-brain-service'`

---

### Task 2: Update `SprintBrainOutput` to include `insufficient_data_devs`

**Files:**
- Modify: `apps/api/src/services/sprint_brain.py` (the `SprintBrainOutput` dataclass)
- Modify: `apps/api/tests/test_sprint_brain.py` (update `SAMPLE_OUTPUT` fixture)

The new field holds developers who failed the 3-sprint gate. It is always present (empty list if all developers passed).

- [ ] **Step 1: Update `SprintBrainOutput` in `services/sprint_brain.py`**

Find the existing `SprintBrainOutput` dataclass (currently ends at `what_if_dropped`) and add the new field:

```python
@dataclass
class SprintBrainOutput:
    assignments: list[dict]
    confidence_score: float
    summary: str
    warnings: list[str]
    what_if_dropped: dict[str, float]
    insufficient_data_devs: list[dict] = field(default_factory=list)
    # Each entry: {developer_id, display_name, sprints_recorded, sprints_needed}
```

- [ ] **Step 2: Update `SAMPLE_OUTPUT` fixture in `tests/test_sprint_brain.py`**

Add `insufficient_data_devs=[]` to the existing `SAMPLE_OUTPUT` construction so existing tests keep passing with the new field:

```python
SAMPLE_OUTPUT = SprintBrainOutput(
    assignments=[...],          # keep as-is
    confidence_score=0.82,
    summary="Solid sprint with two high-priority items assigned to Alice.",
    warnings=["Bob has insufficient velocity data — treat his capacity as unknown."],
    what_if_dropped={"PROJ-1": 0.91, "PROJ-2": 0.78},
    insufficient_data_devs=[],  # ADD THIS
)
```

- [ ] **Step 3: Run existing tests — they should still pass**

```bash
cd apps/api
python -m pytest tests/test_sprint_brain.py -v
```

Expected: all existing tests pass (no failures from the new field).

- [ ] **Step 4: Commit**

```bash
git add apps/api/src/services/sprint_brain.py apps/api/tests/test_sprint_brain.py
git commit -m "feat: add insufficient_data_devs field to SprintBrainOutput"
```

---

### Task 3: Implement the 3-sprint gate

**Files:**
- Modify: `apps/api/src/services/sprint_brain.py` (add `_apply_sprint_gate`)
- Modify: `apps/api/tests/test_sprint_brain.py` (new test class)

The gate reads `sprint_count` from the **top level** of each developer profile dict. This is the max `sample_count` across all their velocity breakdown entries, pre-computed by the velocity engine coordinator.

**Gate rule:** `sprint_count >= 3` → eligible. `sprint_count < 3` (or key missing) → insufficient.

**Note on profile format change:** Track F uses a flatter profile shape than Track E's nested `velocity` dict. The new shape is:
```python
{
    "developer_id": "alice",
    "display_name": "Alice",
    "sprint_count": 5,                 # top-level — used for the gate
    "velocity_breakdown": [            # per-type/domain rows for citations
        {"ticket_type": "bug", "domain": "backend", "avg_pts": 8.2, "sample_count": 4},
    ],
    "safe_capacity_pts": 24.0,
}
```
The router stubs return `[]` so no live data breaks. Only test fixtures need updating.

- [ ] **Step 1: Write failing tests for `_apply_sprint_gate`**

Add this test class to `tests/test_sprint_brain.py`:

```python
from src.services.sprint_brain import _apply_sprint_gate

# New profile shape used in Track F tests
PROFILE_ALICE = {
    "developer_id": "dev-1",
    "display_name": "Alice",
    "sprint_count": 5,
    "velocity_breakdown": [
        {"ticket_type": "bug", "domain": "backend", "avg_pts": 8.2, "sample_count": 4},
        {"ticket_type": "story", "domain": "frontend", "avg_pts": 5.0, "sample_count": 2},
    ],
    "safe_capacity_pts": 24.0,
}

PROFILE_BOB = {
    "developer_id": "dev-2",
    "display_name": "Bob",
    "sprint_count": 1,
    "velocity_breakdown": [
        {"ticket_type": "story", "domain": "backend", "avg_pts": 3.0, "sample_count": 1},
    ],
    "safe_capacity_pts": 8.0,
}

PROFILE_CHARLIE = {
    "developer_id": "dev-3",
    "display_name": "Charlie",
    "sprint_count": 3,
    "velocity_breakdown": [
        {"ticket_type": "task", "domain": "infra", "avg_pts": 6.0, "sample_count": 3},
    ],
    "safe_capacity_pts": 18.0,
}


class TestApplySprintGate:
    def test_eligible_developer_passes(self):
        eligible, insufficient = _apply_sprint_gate([PROFILE_ALICE])
        assert len(eligible) == 1
        assert len(insufficient) == 0

    def test_insufficient_developer_fails(self):
        eligible, insufficient = _apply_sprint_gate([PROFILE_BOB])
        assert len(eligible) == 0
        assert len(insufficient) == 1

    def test_exactly_three_sprints_passes(self):
        eligible, insufficient = _apply_sprint_gate([PROFILE_CHARLIE])
        assert len(eligible) == 1
        assert len(insufficient) == 0

    def test_mixed_profiles_split_correctly(self):
        eligible, insufficient = _apply_sprint_gate([PROFILE_ALICE, PROFILE_BOB, PROFILE_CHARLIE])
        assert len(eligible) == 2
        assert len(insufficient) == 1
        assert insufficient[0]["developer_id"] == "dev-2"

    def test_insufficient_entry_has_required_fields(self):
        _, insufficient = _apply_sprint_gate([PROFILE_BOB])
        entry = insufficient[0]
        assert entry["developer_id"] == "dev-2"
        assert entry["display_name"] == "Bob"
        assert entry["sprints_recorded"] == 1
        assert entry["sprints_needed"] == 2  # 3 - 1

    def test_missing_sprint_count_treated_as_zero(self):
        profile_no_count = {"developer_id": "dev-x", "display_name": "X"}
        eligible, insufficient = _apply_sprint_gate([profile_no_count])
        assert len(eligible) == 0
        assert insufficient[0]["sprints_recorded"] == 0
        assert insufficient[0]["sprints_needed"] == 3

    def test_empty_profiles_returns_empty_buckets(self):
        eligible, insufficient = _apply_sprint_gate([])
        assert eligible == []
        assert insufficient == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_sprint_brain.py::TestApplySprintGate -v
```

Expected: `ImportError` or `AttributeError` — `_apply_sprint_gate` does not exist yet.

- [ ] **Step 3: Implement `_apply_sprint_gate` in `services/sprint_brain.py`**

Add this function after the `SprintBrainOutput` dataclass, before the existing helpers:

```python
_MIN_SPRINTS = 3


def _apply_sprint_gate(
    developer_profiles: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Split developer profiles into eligible and insufficient-data buckets.

    A developer is eligible if their top-level sprint_count >= _MIN_SPRINTS.
    Returns (eligible_profiles, insufficient_data_entries).
    """
    eligible: list[dict] = []
    insufficient: list[dict] = []

    for profile in developer_profiles:
        recorded = int(profile.get("sprint_count", 0))
        if recorded >= _MIN_SPRINTS:
            eligible.append(profile)
        else:
            needed = max(0, _MIN_SPRINTS - recorded)
            insufficient.append({
                "developer_id": profile.get("developer_id", "unknown"),
                "display_name": profile.get("display_name", "Unknown"),
                "sprints_recorded": recorded,
                "sprints_needed": needed,
            })

    return eligible, insufficient
```

- [ ] **Step 4: Run the gate tests to confirm they pass**

```bash
python -m pytest tests/test_sprint_brain.py::TestApplySprintGate -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Run the full test suite — no regressions**

```bash
python -m pytest tests/test_sprint_brain.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/services/sprint_brain.py apps/api/tests/test_sprint_brain.py
git commit -m "feat: implement 3-sprint gate for sprint brain service"
```

---

## Chunk 2: Claude Call 1 — Ticket Complexity Analysis

### Task 4: Add the `analyse_tickets` tool schema and system prompt

**Files:**
- Modify: `apps/api/src/services/sprint_brain.py` (add tool schema + system prompt constant)

- [ ] **Step 1: Add `_COMPLEXITY_TOOL` and `_COMPLEXITY_SYSTEM_PROMPT` to `sprint_brain.py`**

Insert these after the existing `_SPRINT_PLAN_TOOL` definition:

```python
_COMPLEXITY_TOOL: dict = {
    "name": "analyse_tickets",
    "description": (
        "Analyse a list of tickets and return a complexity estimate for each one. "
        "Focus purely on the work itself — do not consider developer availability."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticket_analyses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "effort": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Overall implementation effort.",
                        },
                        "required_skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Technical skills needed, e.g. ['backend', 'sql', 'api-design']. "
                                "Use domain names from: frontend, backend, infra. "
                                "Add specifics as extra tags."
                            ),
                        },
                        "complexity_notes": {
                            "type": "string",
                            "description": "One sentence explaining the main complexity driver.",
                        },
                        "estimated_days": {
                            "type": "number",
                            "description": "Estimated calendar days for a mid-level engineer.",
                        },
                    },
                    "required": ["ticket_id", "effort", "required_skills", "complexity_notes", "estimated_days"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["ticket_analyses"],
        "additionalProperties": False,
    },
}

_COMPLEXITY_SYSTEM_PROMPT = """\
You are a senior software engineer estimating implementation effort for sprint tickets.

For each ticket, assess:
1. Effort level: low (< 1 day), medium (1–3 days), high (3+ days)
2. Required skills: use domain terms (frontend, backend, infra) plus specific tags
3. Complexity notes: one sentence on the main driver of complexity
4. Estimated days: your best estimate for a mid-level engineer

Focus purely on the work. Ignore team composition and availability.
Always respond by calling the analyse_tickets tool.\
"""
```

- [ ] **Step 2: Run tests to confirm no regressions**

```bash
python -m pytest tests/test_sprint_brain.py -v
```

Expected: all tests pass (this step adds constants only — no logic change).

- [ ] **Step 3: Commit**

```bash
git add apps/api/src/services/sprint_brain.py
git commit -m "feat: add complexity analysis tool schema and system prompt"
```

---

### Task 5: Implement complexity analysis helpers and async function

**Files:**
- Modify: `apps/api/src/services/sprint_brain.py` (add `_build_complexity_message`, `_extract_complexity`, `_analyse_ticket_complexity`)
- Modify: `apps/api/tests/test_sprint_brain.py` (new test class)

- [ ] **Step 1: Write failing tests for complexity analysis**

Add to `tests/test_sprint_brain.py`:

> **Important:** Do NOT add a module-level import for `_build_complexity_message` or
> `_extract_complexity` yet — those names do not exist until Step 3. Adding a top-level
> import of undefined symbols causes the entire test file to fail at collection, breaking
> all existing tests. Use deferred (inline) imports inside each method instead, matching
> the existing pattern used for `_analyse_ticket_complexity` at the bottom of Step 1.
> After Step 3 (implementation), move them to the existing module-level import block.

```python
class TestComplexityAnalysis:
    def test_build_complexity_message_includes_all_ticket_ids(self):
        from src.services.sprint_brain import _build_complexity_message
        msg = _build_complexity_message(SAMPLE_TICKETS)
        assert "PROJ-1" in msg
        assert "PROJ-2" in msg
        assert "PROJ-3" in msg

    def test_build_complexity_message_includes_summaries(self):
        from src.services.sprint_brain import _build_complexity_message
        msg = _build_complexity_message(SAMPLE_TICKETS)
        assert "Build login page" in msg
        assert "Fix null pointer bug" in msg

    def test_build_complexity_message_includes_story_points(self):
        from src.services.sprint_brain import _build_complexity_message
        msg = _build_complexity_message(SAMPLE_TICKETS)
        # Points are useful context for the complexity estimate
        assert "3" in msg

    def test_extract_complexity_parses_tool_response(self):
        from src.services.sprint_brain import _extract_complexity
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "analyse_tickets"
        tool_block.input = {
            "ticket_analyses": [
                {
                    "ticket_id": "PROJ-1",
                    "effort": "medium",
                    "required_skills": ["frontend", "auth"],
                    "complexity_notes": "Requires auth integration.",
                    "estimated_days": 2.0,
                }
            ]
        }
        response = MagicMock()
        response.content = [tool_block]

        result = _extract_complexity(response)

        assert len(result) == 1
        assert result[0]["ticket_id"] == "PROJ-1"
        assert result[0]["effort"] == "medium"
        assert result[0]["estimated_days"] == 2.0

    def test_extract_complexity_raises_when_tool_missing(self):
        from src.services.sprint_brain import _extract_complexity
        text_block = MagicMock()
        text_block.type = "text"
        response = MagicMock()
        response.content = [text_block]

        with pytest.raises(RuntimeError, match="complexity analysis"):
            _extract_complexity(response)


@pytest.mark.asyncio
async def test_analyse_ticket_complexity_calls_claude():
    """_analyse_ticket_complexity must call Claude exactly once with the right tool."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "analyse_tickets"
    tool_block.input = {
        "ticket_analyses": [
            {
                "ticket_id": "PROJ-1",
                "effort": "low",
                "required_skills": ["frontend"],
                "complexity_notes": "Simple UI.",
                "estimated_days": 0.5,
            }
        ]
    }
    mock_response = MagicMock()
    mock_response.content = [tool_block]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    from src.services.sprint_brain import _analyse_ticket_complexity
    result = await _analyse_ticket_complexity(SAMPLE_TICKETS[:1], mock_client)

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "analyse_tickets"}
    assert len(result) == 1
    assert result[0]["ticket_id"] == "PROJ-1"
```

- [ ] **Step 2: Run to confirm new tests fail, existing tests unaffected**

```bash
python -m pytest tests/test_sprint_brain.py::TestComplexityAnalysis tests/test_sprint_brain.py::test_analyse_ticket_complexity_calls_claude -v
```

Expected: `ImportError` on the new tests only — helpers not yet defined. The rest of the
existing test suite must still collect and pass (run `python -m pytest tests/test_sprint_brain.py -v`
to confirm no collection-time failures before proceeding).

- [ ] **Step 3: Implement the three complexity helpers in `sprint_brain.py`**

> **Note:** `_apply_sprint_gate` (the anchor point) was added in Chunk 1 Task 3. `_MODEL`
> already exists in the file from Track E — no change needed.

After implementing, add `_build_complexity_message` and `_extract_complexity` to the
**existing module-level import block** at the top of `tests/test_sprint_brain.py` so the
inline deferred imports are no longer needed (the deferred pattern was only to avoid
collection-time failures before the symbols existed):

```python
# In tests/test_sprint_brain.py — update the existing import to include new symbols:
from src.services.sprint_brain import (
    SprintBrainInput,
    SprintBrainOutput,
    _build_user_message,
    _build_complexity_message,   # ADD
    _extract_complexity,          # ADD
    generate_sprint_plan,
    simulate_what_if,
)
```

Then remove the deferred `from src.services.sprint_brain import ...` lines from inside
each `TestComplexityAnalysis` method.

Add the three helpers after `_apply_sprint_gate`:

```python
def _build_complexity_message(tickets: list[dict]) -> str:
    lines = ["## Tickets to Analyse", ""]
    for i, ticket in enumerate(tickets, 1):
        tid = ticket.get("id") or ticket.get("ticket_id") or f"ticket-{i}"
        title = ticket.get("summary") or ticket.get("title") or "(no title)"
        points = ticket.get("story_points") or ticket.get("points") or "?"
        priority = ticket.get("priority", "medium")
        labels = ticket.get("labels") or []

        lines.append(f"{i}. [{tid}] {title}")
        lines.append(f"   Story points: {points} | Priority: {priority}")
        if labels:
            lines.append(f"   Labels: {', '.join(labels)}")
        if ticket.get("description"):
            desc = str(ticket["description"])[:200]
            lines.append(f"   Description: {desc}")
        lines.append("")

    lines.append("Analyse each ticket and call the analyse_tickets tool with your assessment.")
    return "\n".join(lines)


def _extract_complexity(response: anthropic.types.Message) -> list[dict]:
    tool_block = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "analyse_tickets"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            "Claude did not return a complexity analysis tool call. "
            "Please try again."
        )
    return tool_block.input["ticket_analyses"]


async def _analyse_ticket_complexity(
    tickets: list[dict],
    client: anthropic.AsyncAnthropic,
) -> list[dict]:
    """
    Claude Call 1: analyse ticket complexity without developer context.
    Returns a list of per-ticket complexity dicts.
    """
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_COMPLEXITY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_complexity_message(tickets)}],
        tools=[_COMPLEXITY_TOOL],
        tool_choice={"type": "tool", "name": "analyse_tickets"},
    )
    return _extract_complexity(response)
```

- [ ] **Step 4: Run complexity tests to confirm they pass**

```bash
python -m pytest tests/test_sprint_brain.py::TestComplexityAnalysis tests/test_sprint_brain.py::test_analyse_ticket_complexity_calls_claude -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Run full test suite — no regressions**

```bash
python -m pytest tests/test_sprint_brain.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/services/sprint_brain.py apps/api/tests/test_sprint_brain.py
git commit -m "feat: implement Claude Call 1 — ticket complexity analysis"
```

---

## Chunk 3: Claude Call 2 — Assignment Message with Velocity Breakdown

### Task 6: Replace `_build_user_message` with `_build_assignment_message`

**Files:**
- Modify: `apps/api/src/services/sprint_brain.py` (add `_build_assignment_message`, update `_SYSTEM_PROMPT`)
- Modify: `apps/api/tests/test_sprint_brain.py` (update + add tests)

The new function takes `eligible_profiles` (already gated) and `complexity_analysis` from Call 1, and builds a prompt where each developer section has a velocity breakdown table formatted for easy citation.

- [ ] **Step 1: Write failing tests for `_build_assignment_message`**

> **Note:** `PROFILE_ALICE`, `PROFILE_BOB`, and `PROFILE_CHARLIE` were defined in Chunk 1 Task 3
> and are already in the test file at this point. Do not redefine them.

Add to `tests/test_sprint_brain.py`:

```python
from src.services.sprint_brain import _build_assignment_message

COMPLEXITY_ANALYSIS = [
    {"ticket_id": "PROJ-1", "effort": "low", "required_skills": ["frontend"], "complexity_notes": "Simple UI.", "estimated_days": 1.0},
    {"ticket_id": "PROJ-2", "effort": "medium", "required_skills": ["backend"], "complexity_notes": "Auth layer.", "estimated_days": 2.0},
]

# Use the new Track F profile shape (PROFILE_ALICE and PROFILE_CHARLIE defined in Chunk 1)
NEW_SAMPLE_PROFILES = [PROFILE_ALICE, PROFILE_CHARLIE]

NEW_SAMPLE_INPUT = SprintBrainInput(
    team_id="team-abc",
    candidate_tickets=SAMPLE_TICKETS[:2],
    developer_profiles=NEW_SAMPLE_PROFILES,
    sprint_length_days=14,
    sprint_start_date="2026-03-17",
    pto_overrides={"dev-1": 1.0},
)


class TestBuildAssignmentMessage:
    def test_includes_team_id(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "team-abc" in msg

    def test_includes_ticket_ids(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "PROJ-1" in msg
        assert "PROJ-2" in msg

    def test_includes_complexity_effort(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "low" in msg or "medium" in msg

    def test_includes_developer_names(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "Alice" in msg
        assert "Charlie" in msg

    def test_includes_velocity_breakdown(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        # Should render breakdown table with avg_pts
        assert "8.2" in msg   # Alice's backend/bug avg

    def test_includes_safe_capacity(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "24" in msg    # Alice's safe_capacity_pts

    def test_includes_pto(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "PTO" in msg
        assert "1.0" in msg

    def test_includes_citation_instruction(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "historical data" in msg.lower() or "based on" in msg.lower()

    def test_excludes_insufficient_developers(self):
        # If only Alice is eligible, Bob should not appear
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, [PROFILE_ALICE])
        assert "Alice" in msg
        assert "Bob" not in msg
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_sprint_brain.py::TestBuildAssignmentMessage -v
```

Expected: `ImportError` — `_build_assignment_message` not yet defined.

- [ ] **Step 3: Add `_CITATION_INSTRUCTION` constant and `_build_assignment_message` to `sprint_brain.py`**

Add this constant near the other module-level constants (after `_SYSTEM_PROMPT`), then add the function after `_analyse_ticket_complexity`. Keep the old `_build_user_message` in place for now (it is still tested by existing tests; it will be removed in Task 8).

```python
_CITATION_INSTRUCTION = (
    "For each assignment, cite the specific historical data you are using. "
    'Example: "Based on 4 backend/bug sprints averaging 8.2 pts, '
    "this fits within Alice's safe capacity of 24 pts.\""
)
```

Then update `test_includes_citation_instruction` to use the constant instead of a fragile string match:

```python
from src.services.sprint_brain import _CITATION_INSTRUCTION

def test_includes_citation_instruction(self):
    msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
    assert _CITATION_INSTRUCTION in msg
```

```python
def _build_assignment_message(
    inp: SprintBrainInput,
    complexity_analysis: list[dict],
    eligible_profiles: list[dict],
) -> str:
    # Index complexity by ticket_id for quick lookup
    complexity_map = {c["ticket_id"]: c for c in complexity_analysis}

    lines: list[str] = [
        "## Sprint Planning Request",
        f"Team ID: {inp.team_id}",
        f"Sprint start: {inp.sprint_start_date}",
        f"Sprint length: {inp.sprint_length_days} days",
        "",
        "## Developer Profiles (eligible assignees only)",
        _CITATION_INSTRUCTION,
        "",
    ]

    for profile in eligible_profiles:
        dev_id = profile.get("developer_id", "unknown")
        display = profile.get("display_name", dev_id)
        capacity = profile.get("safe_capacity_pts", "?")
        pto = inp.pto_overrides.get(dev_id, 0.0)

        lines.append(f"### {display}  (id: {dev_id})")
        lines.append(f"  Safe capacity : {capacity} pts this sprint")
        if pto > 0:
            lines.append(f"  PTO           : {pto} day(s)")

        breakdown = profile.get("velocity_breakdown") or []
        if breakdown:
            lines.append("  Historical velocity breakdown:")
            for row in breakdown:
                ttype = row.get("ticket_type", "?")
                domain = row.get("domain", "?")
                avg = row.get("avg_pts", "?")
                count = row.get("sample_count", "?")
                lines.append(f"    {domain} / {ttype} → {count} sprints, avg {avg} pts/sprint")
        else:
            lines.append("  Historical velocity breakdown: no data recorded")
        lines.append("")

    lines += ["## Candidate Tickets (with complexity analysis)", ""]
    for i, ticket in enumerate(inp.candidate_tickets, 1):
        tid = ticket.get("id") or ticket.get("ticket_id") or f"ticket-{i}"
        title = ticket.get("summary") or ticket.get("title") or "(no title)"
        points = ticket.get("story_points") or ticket.get("points") or "?"
        priority = ticket.get("priority", "medium")
        labels = ticket.get("labels") or []
        analysis = complexity_map.get(tid, {})

        lines.append(f"{i}. [{tid}] {title}")
        lines.append(f"   Points: {points} | Priority: {priority}")
        if labels:
            lines.append(f"   Labels: {', '.join(labels)}")
        if analysis:
            lines.append(f"   Effort    : {analysis.get('effort', '?')}")
            lines.append(f"   Est. days : {analysis.get('estimated_days', '?')}")
            lines.append(f"   Skills    : {', '.join(analysis.get('required_skills', []))}")
            lines.append(f"   Notes     : {analysis.get('complexity_notes', '')}")
        lines.append("")

    lines += [
        "Please create the optimal sprint plan. For each ticket, assign it to the "
        "best-fit developer and include a citation of the specific historical data "
        "supporting your decision. Populate what_if_dropped for each assigned ticket.",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Update `_SYSTEM_PROMPT` to include citation instruction**

Find the existing `_SYSTEM_PROMPT` constant and add a citation rule. Replace it with:

```python
_SYSTEM_PROMPT = """\
You are an expert agile sprint planning assistant with deep expertise in \
software engineering team dynamics and velocity-based capacity planning.

Your responsibilities:
1. Assign tickets to developers based on their velocity profiles, historical \
   performance, and skill fit.
2. Respect each developer's safe capacity — never overload.
3. Prioritise high-value, unblocked tickets first.
4. Surface risks proactively: overloaded developers, skill gaps, low-data \
   estimates, sequential dependencies.
5. Be conservative. A sprint with 80 % confidence is far better than one \
   that looks full on paper but will slip.
6. For EVERY assignment, include in your reasoning a direct citation of \
   the historical velocity data you used. \
   Example: "Based on 4 backend/bug sprints averaging 8.2 pts, this fits \
   within Alice's safe capacity of 24 pts."

Always respond by calling the create_sprint_plan tool with your complete \
analysis. Do not respond in prose outside the tool call.\
"""
```

- [ ] **Step 5: Run assignment message tests**

```bash
python -m pytest tests/test_sprint_brain.py::TestBuildAssignmentMessage -v
```

Expected: all 9 tests pass.

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/test_sprint_brain.py -v
```

Expected: all tests pass. At this point `generate_sprint_plan` has **not** been rewritten yet
(that is Chunk 4), so the existing single-call mocked tests for it still pass unchanged.
The `_SYSTEM_PROMPT` update does not affect those tests because they mock the API response
and do not inspect the prompt content.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/services/sprint_brain.py apps/api/tests/test_sprint_brain.py
git commit -m "feat: add velocity breakdown assignment message builder for Call 2"
```

---

## Chunk 4: Wire Up Two-Step Pipeline

### Task 7: Rewrite `generate_sprint_plan` to use the two-step approach

**Files:**
- Modify: `apps/api/src/services/sprint_brain.py` (rewrite `generate_sprint_plan`)
- Modify: `apps/api/tests/test_sprint_brain.py` (update mocking, add new tests)

The new `generate_sprint_plan` flow:
1. Apply the gate → `eligible_profiles`, `insufficient_data_devs`
2. Guard: raise `RuntimeError` if `eligible_profiles` is empty
3. Claude Call 1: `_analyse_ticket_complexity(tickets, client)`
4. Claude Call 2: build assignment message → `create_sprint_plan` tool call
5. Merge `insufficient_data_devs` into the returned `SprintBrainOutput`

- [ ] **Step 1: Write failing tests for the new two-step behaviour**

Add to `tests/test_sprint_brain.py`:

```python
def _make_complexity_response(analyses: list[dict]):
    """Build a mock response for the complexity analysis Claude call."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "analyse_tickets"
    tool_block.input = {"ticket_analyses": analyses}
    response = MagicMock()
    response.content = [tool_block]
    return response


SAMPLE_COMPLEXITY = [
    {"ticket_id": "PROJ-1", "effort": "low", "required_skills": ["frontend"], "complexity_notes": "Simple.", "estimated_days": 1.0},
    {"ticket_id": "PROJ-2", "effort": "medium", "required_skills": ["backend"], "complexity_notes": "Auth.", "estimated_days": 2.0},
    {"ticket_id": "PROJ-3", "effort": "high", "required_skills": ["backend", "infra"], "complexity_notes": "Perf.", "estimated_days": 4.0},
]

PLAN_DICT = {
    "assignments": [
        {"ticket_id": "PROJ-1", "developer_id": "dev-1", "reasoning": "Based on 4 backend/bug sprints averaging 8.2 pts.", "confidence": 0.88, "story_points": 3},
    ],
    "confidence_score": 0.85,
    "summary": "One ticket assigned to Alice based on her backend history.",
    "warnings": [],
    "what_if_dropped": {"PROJ-1": 1.0},
}

# NEW_SAMPLE_INPUT uses NEW_SAMPLE_PROFILES (PROFILE_ALICE + PROFILE_CHARLIE — both eligible)

@pytest.mark.asyncio
async def test_generate_sprint_plan_makes_two_claude_calls():
    """generate_sprint_plan must call the Anthropic API exactly twice."""
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    plan_response = _make_mock_response(PLAN_DICT)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, plan_response])

        result = await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")

    assert instance.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_generate_sprint_plan_attaches_insufficient_data_devs():
    """Developers who fail the gate appear in insufficient_data_devs."""
    mixed_input = SprintBrainInput(
        team_id="team-abc",
        candidate_tickets=SAMPLE_TICKETS,
        developer_profiles=[PROFILE_ALICE, PROFILE_BOB],  # Bob fails gate
        sprint_length_days=14,
        sprint_start_date="2026-03-17",
    )
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    plan_response = _make_mock_response(PLAN_DICT)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, plan_response])

        result = await generate_sprint_plan(mixed_input, "sk-ant-test")

    assert len(result.insufficient_data_devs) == 1
    assert result.insufficient_data_devs[0]["developer_id"] == "dev-2"


@pytest.mark.asyncio
async def test_generate_sprint_plan_raises_when_all_devs_insufficient():
    """If all developers fail the gate, raise RuntimeError before calling Claude."""
    all_insufficient_input = SprintBrainInput(
        team_id="team-abc",
        candidate_tickets=SAMPLE_TICKETS,
        developer_profiles=[PROFILE_BOB],  # only Bob — fails gate
        sprint_length_days=14,
        sprint_start_date="2026-03-17",
    )

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock()

        with pytest.raises(RuntimeError, match="no eligible developers"):
            await generate_sprint_plan(all_insufficient_input, "sk-ant-test")

    instance.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_generate_sprint_plan_second_call_uses_assignment_tool():
    """The second Claude call must use create_sprint_plan tool, not analyse_tickets."""
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    plan_response = _make_mock_response(PLAN_DICT)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, plan_response])

        await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")

    second_call_kwargs = instance.messages.create.call_args_list[1].kwargs
    assert second_call_kwargs["tool_choice"] == {"type": "tool", "name": "create_sprint_plan"}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_sprint_brain.py::test_generate_sprint_plan_makes_two_claude_calls tests/test_sprint_brain.py::test_generate_sprint_plan_attaches_insufficient_data_devs tests/test_sprint_brain.py::test_generate_sprint_plan_raises_when_all_devs_insufficient tests/test_sprint_brain.py::test_generate_sprint_plan_second_call_uses_assignment_tool -v
```

Expected: failures — current `generate_sprint_plan` makes one call, not two.

- [ ] **Step 3: Rewrite `generate_sprint_plan` in `sprint_brain.py`**

Replace the existing `generate_sprint_plan` function with:

```python
async def generate_sprint_plan(
    inp: SprintBrainInput,
    anthropic_api_key: str,
) -> SprintBrainOutput:
    """
    Generate an AI-powered sprint plan using a two-step Claude Opus 4.6 pipeline.

    Step 1 — Analyse ticket complexity (no developer context).
    Step 2 — Generate assignments with velocity-grounded reasoning and citations.

    Developers with fewer than 3 sprints of data are gated out before either call.
    Their cards are returned in SprintBrainOutput.insufficient_data_devs.

    The anthropic_api_key must come from the customer (BYOK) — never from env.

    Raises:
        ValueError: if the API key is invalid.
        RuntimeError: if all developers fail the data gate, on rate limits,
                      API errors, or unexpected model output.
    """
    eligible_profiles, insufficient_data_devs = _apply_sprint_gate(inp.developer_profiles)

    if not eligible_profiles:
        raise RuntimeError(
            "Sprint plan cannot be generated: no eligible developers. "
            "All team members have fewer than 3 sprints of recorded data."
        )

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

    try:
        # --- Call 1: ticket complexity analysis ---
        complexity_analysis = await _analyse_ticket_complexity(inp.candidate_tickets, client)

        # --- Call 2: assignment generation with historical citations ---
        assignment_message = _build_assignment_message(inp, complexity_analysis, eligible_profiles)
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=16384,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": assignment_message}],
            tools=[_SPRINT_PLAN_TOOL],
            tool_choice={"type": "tool", "name": "create_sprint_plan"},
        )

    except anthropic.AuthenticationError as exc:
        raise ValueError(
            "Invalid Anthropic API key. Please update your key in Settings."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            "Anthropic API rate limit reached. Please wait a moment and try again."
        ) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc.message}") from exc

    plan = _extract_plan(response)
    plan.insufficient_data_devs = insufficient_data_devs
    return plan
```

- [ ] **Step 4: Run the new two-step tests**

```bash
python -m pytest tests/test_sprint_brain.py::test_generate_sprint_plan_makes_two_claude_calls tests/test_sprint_brain.py::test_generate_sprint_plan_attaches_insufficient_data_devs tests/test_sprint_brain.py::test_generate_sprint_plan_raises_when_all_devs_insufficient tests/test_sprint_brain.py::test_generate_sprint_plan_second_call_uses_assignment_tool -v
```

Expected: all 4 pass.

- [ ] **Step 5: Update pre-existing `generate_sprint_plan` tests to use two-call mocking**

The three pre-existing tests (`test_generate_sprint_plan_returns_output`, `test_generate_sprint_plan_raises_on_auth_error`, `test_generate_sprint_plan_raises_on_rate_limit`, `test_generate_sprint_plan_raises_when_no_tool_call`) currently mock a single Claude call. They need updating to:
  1. Use `NEW_SAMPLE_INPUT` (which has eligible profiles) instead of `SAMPLE_INPUT`
  2. Provide two side-effect responses for the mock

Update `test_generate_sprint_plan_returns_output`:
```python
@pytest.mark.asyncio
async def test_generate_sprint_plan_returns_output():
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    plan_dict = {
        "assignments": SAMPLE_OUTPUT.assignments,
        "confidence_score": SAMPLE_OUTPUT.confidence_score,
        "summary": SAMPLE_OUTPUT.summary,
        "warnings": SAMPLE_OUTPUT.warnings,
        "what_if_dropped": SAMPLE_OUTPUT.what_if_dropped,
    }
    plan_response = _make_mock_response(plan_dict)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, plan_response])

        result = await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")

    assert isinstance(result, SprintBrainOutput)
    assert result.confidence_score == pytest.approx(0.82)
    assert len(result.assignments) == 2
    assert result.what_if_dropped["PROJ-1"] == pytest.approx(0.91)
```

Update `test_generate_sprint_plan_raises_on_auth_error` and `test_generate_sprint_plan_raises_on_rate_limit` to use `NEW_SAMPLE_INPUT` — the error fires on the first call so only one side_effect is needed:
```python
# In both auth + rate-limit tests, replace SAMPLE_INPUT with NEW_SAMPLE_INPUT
result = await generate_sprint_plan(NEW_SAMPLE_INPUT, "bad-key")   # or "sk-ant-test"
```

Update `test_generate_sprint_plan_raises_when_no_tool_call` — the bad response is for the *second* call (Call 1 must succeed first):
```python
@pytest.mark.asyncio
async def test_generate_sprint_plan_raises_when_no_tool_call():
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    text_block = MagicMock()
    text_block.type = "text"
    bad_response = MagicMock()
    bad_response.content = [text_block]

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, bad_response])

        with pytest.raises(RuntimeError, match="did not return a sprint plan"):
            await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")
```

- [ ] **Step 6: Run the full test suite**

```bash
python -m pytest tests/test_sprint_brain.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/services/sprint_brain.py apps/api/tests/test_sprint_brain.py
git commit -m "feat: rewrite generate_sprint_plan with two-step Claude pipeline and gate"
```

---

### Task 8: Remove the now-unused `_build_user_message`

**Files:**
- Modify: `apps/api/src/services/sprint_brain.py` (delete `_build_user_message`)
- Modify: `apps/api/tests/test_sprint_brain.py` (delete its tests)

`_build_user_message` was the Track E single-call prompt builder. It is fully replaced by `_build_assignment_message`. Keeping it would be dead code.

- [ ] **Step 1: Delete `_build_user_message` from `sprint_brain.py`**

Remove the entire `_build_user_message` function (roughly lines 139–190 in the original file — verify by reading before deleting).

- [ ] **Step 2: Remove the import and tests for `_build_user_message` in the test file**

Remove:
- The `_build_user_message` import from `from src.services.sprint_brain import ...`
- The six tests in the `# _build_user_message unit tests` section (`test_build_user_message_*`)

- [ ] **Step 3: Run full test suite — confirm clean**

```bash
python -m pytest tests/test_sprint_brain.py -v
```

Expected: all tests pass, no references to `_build_user_message`.

- [ ] **Step 4: Commit**

```bash
git add apps/api/src/services/sprint_brain.py apps/api/tests/test_sprint_brain.py
git commit -m "refactor: remove unused _build_user_message replaced by Track F pipeline"
```

---

## Chunk 5: Router Update + Final Verification

### Task 9: Include `insufficient_data_devs` in router responses

**Files:**
- Modify: `apps/api/src/routers/sprint_brain.py` (`_sprint_plan_response` helper + `/what-if` endpoint)

- [ ] **Step 1: Update `_sprint_plan_response` in the router**

Find the existing `_sprint_plan_response` function and add the new field:

```python
def _sprint_plan_response(team_id: str, sprint_start: str, plan: SprintBrainOutput) -> dict:
    return {
        "team_id": team_id,
        "sprint_start": sprint_start,
        "assignments": plan.assignments,
        "confidence_score": plan.confidence_score,
        "summary": plan.summary,
        "warnings": plan.warnings,
        "what_if_dropped": plan.what_if_dropped,
        "insufficient_data_devs": plan.insufficient_data_devs,  # ADD THIS
    }
```

- [ ] **Step 2: Add `insufficient_data_devs` to the `/what-if` response**

Find the `return { ... }` block inside `what_if_scenario` and update `revised_plan`:

```python
return {
    "team_id": request.team_id,
    "sprint_start": sprint_start,
    "dropped_tickets": request.dropped_ticket_ids,
    "revised_plan": {
        "assignments": plan.assignments,
        "confidence_score": plan.confidence_score,
        "summary": plan.summary,
        "warnings": plan.warnings,
        "insufficient_data_devs": plan.insufficient_data_devs,  # ADD THIS
    },
}
```

- [ ] **Step 3: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add apps/api/src/routers/sprint_brain.py
git commit -m "feat: expose insufficient_data_devs in sprint brain API responses"
```

---

### Task 10: Final verification

- [ ] **Step 1: Run entire test suite one final time**

```bash
cd apps/api && python -m pytest tests/ -v --tb=short
```

Expected: all tests pass, zero failures.

- [ ] **Step 2: Confirm no references to removed symbols**

```bash
grep -r "_build_user_message" apps/api/src apps/api/tests
```

Expected: no output.

- [ ] **Step 3: Verify the branch is clean and up to date**

```bash
git status
git log --oneline track-f-sprint-brain-service ^main
```

Expected: clean working tree. Log shows all Track F commits since branching from main.

- [ ] **Step 4: Final commit if any loose files remain, then invoke finishing skill**

```bash
# Only if git status shows untracked or modified files:
git add <files>
git commit -m "chore: final cleanup for track-f-sprint-brain-service"
```

Then invoke: `superpowers:finishing-a-development-branch`
