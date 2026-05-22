"""Tests for src/assigners/* — the stage-2 assignment strategies.

Every strategy must:
1. Cover every committed ticket exactly once (no drops, no duplicates).
2. Only assign to devs from the supplied developer list.
3. Be deterministic when given the same seed (so the matrix experiment
   is reproducible).
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from src.assigners import (
    AlgorithmAssigner,
    BaseAssigner,
    RandomAssigner,
    SprintContext,
    make_assigner,
)
from src.assigners.omada_assigner import OmadaAssigner


# ---------- helpers ----------

def _devs(n: int = 4) -> list[dict]:
    skills = [
        ["backend"],
        ["frontend"],
        ["backend", "infra"],
        ["frontend", "infra"],
    ]
    return [
        {
            "name": f"Dev{i}",
            "completion_rate": 0.8,
            "speed": 1.0,
            "skills": skills[i % len(skills)],
        }
        for i in range(n)
    ]


def _pool(n: int = 30) -> list[dict]:
    """Synthetic pool. Story-point mix mirrors stage-1 distribution."""
    rng = random.Random(123)
    skills = ["backend", "frontend", "infra", "any"]
    return [
        {
            "jira_key": f"SIM-{i+1}",
            "summary": f"Ticket {i+1}",
            "issue_type": rng.choice(["Story", "Bug", "Task"]),
            "story_points": rng.choice([1, 2, 3, 5, 8]),
            "required_skill": rng.choice(skills),
        }
        for i in range(n)
    ]


def _ctx(
    picked: list[dict],
    developers: list[dict],
    *,
    strategy: str,
    sprint_num: int = 1,
    run_seed: int = 42,
) -> SprintContext:
    """Build a SprintContext with stubbed jira/omada (assigners don't need
    them in M1 — only OmadaAssigner does, tested separately in M2)."""
    return SprintContext(
        sprint_num=sprint_num,
        sprint_id=0,
        committed_keys=[t["jira_key"] for t in picked],
        picked_tickets=picked,
        developers=developers,
        jira=None,  # type: ignore[arg-type]
        omada=None,  # type: ignore[arg-type]
        omada_team_id=None,
        archetype="test",
        strategy=strategy,
        run_seed=run_seed,
        output_dir=Path("/tmp"),
    )


def _assert_covers_every_ticket_once(
    result, picked: list[dict], developers: list[dict]
) -> None:
    """Coverage invariant: by_dev keys == dev names; flat list has each
    jira_key once; no foreign tickets sneaked in."""
    expected = {t["jira_key"] for t in picked}
    assigned_keys = [k for keys in result.by_dev.values() for k in keys]
    assert sorted(assigned_keys) == sorted(expected), (
        f"missing/extra tickets in by_dev: "
        f"got {sorted(assigned_keys)}, want {sorted(expected)}"
    )
    flat_keys = [a.jira_key for a in result.assignments]
    assert sorted(flat_keys) == sorted(expected), (
        "assignments list mismatch with by_dev"
    )
    dev_names = {d["name"] for d in developers}
    extra_devs = set(result.by_dev) - dev_names
    assert not extra_devs, f"by_dev has unknown devs: {extra_devs}"


# ---------- BaseAssigner.select_tickets ----------

def test_select_tickets_pops_from_front_and_mutates_pool() -> None:
    pool = _pool(30)
    devs = _devs(4)
    rng = random.Random(7)
    base = BaseAssigner()

    picked = base.select_tickets(pool, devs, sprint_num=1, rng=rng)

    # 4 devs × (5-8 each) = between 20 and 32; capped at len(pool)=30
    assert 20 <= len(picked) <= 30
    assert len(pool) == 30 - len(picked)
    # Picked must be the front of the original pool — order preserved
    assert all(p["jira_key"].startswith("SIM-") for p in picked)


def test_select_tickets_is_deterministic_given_same_seed() -> None:
    pool1 = _pool(30)
    pool2 = _pool(30)
    base = BaseAssigner()

    picked1 = base.select_tickets(
        pool1, _devs(4), sprint_num=1, rng=random.Random(99)
    )
    picked2 = base.select_tickets(
        pool2, _devs(4), sprint_num=1, rng=random.Random(99)
    )
    assert [t["jira_key"] for t in picked1] == [t["jira_key"] for t in picked2]


def test_select_tickets_empty_inputs() -> None:
    base = BaseAssigner()
    assert base.select_tickets([], _devs(4), 1, rng=random.Random(0)) == []
    assert base.select_tickets(_pool(5), [], 1, rng=random.Random(0)) == []


def test_select_tickets_pool_smaller_than_demand() -> None:
    """When the pool can't satisfy total demand, take what's there."""
    pool = _pool(5)
    devs = _devs(4)  # demands 20-32, pool has 5
    base = BaseAssigner()

    picked = base.select_tickets(pool, devs, 1, rng=random.Random(0))
    assert len(picked) == 5
    assert pool == []


def test_base_assign_raises_not_implemented() -> None:
    """BaseAssigner is abstract for assign(); subclasses must override."""
    devs = _devs(2)
    picked = _pool(4)
    ctx = _ctx(picked, devs, strategy="base")
    with pytest.raises(NotImplementedError):
        BaseAssigner().assign(ctx)


# ---------- RandomAssigner ----------

def test_random_assigner_covers_every_ticket_once() -> None:
    devs = _devs(4)
    picked = _pool(12)
    ctx = _ctx(picked, devs, strategy="random")

    result = RandomAssigner().assign(ctx)
    _assert_covers_every_ticket_once(result, picked, devs)
    assert all(a.source == "random" for a in result.assignments)


def test_random_assigner_is_deterministic_given_same_seed() -> None:
    devs = _devs(4)
    picked = _pool(15)

    r1 = RandomAssigner().assign(_ctx(picked, devs, strategy="random", run_seed=777))
    r2 = RandomAssigner().assign(_ctx(picked, devs, strategy="random", run_seed=777))
    assert r1.by_dev == r2.by_dev


def test_random_assigner_differs_across_seeds() -> None:
    """Different run_seeds should typically produce different assignments
    (smoke test for the RNG actually being used)."""
    devs = _devs(4)
    picked = _pool(30)

    r1 = RandomAssigner().assign(_ctx(picked, devs, strategy="random", run_seed=1))
    r2 = RandomAssigner().assign(_ctx(picked, devs, strategy="random", run_seed=2))
    assert r1.by_dev != r2.by_dev


# ---------- AlgorithmAssigner ----------

def test_algorithm_assigner_covers_every_ticket_once() -> None:
    devs = _devs(4)
    picked = _pool(20)
    ctx = _ctx(picked, devs, strategy="algorithm")

    result = AlgorithmAssigner().assign(ctx)
    _assert_covers_every_ticket_once(result, picked, devs)
    assert all(a.source == "algorithm" for a in result.assignments)


def test_algorithm_assigner_load_balances_by_story_points() -> None:
    """Greedy bin-packing: load spread shouldn't exceed the largest single
    ticket's point value, since each new ticket goes to the lightest dev."""
    devs = _devs(4)
    # Skill-free pool so the eligibility filter never kicks in.
    picked = [
        {
            "jira_key": f"SIM-{i+1}",
            "story_points": pts,
            "required_skill": "any",
        }
        for i, pts in enumerate([8, 8, 5, 5, 3, 3, 2, 2, 1, 1])
    ]
    ctx = _ctx(picked, devs, strategy="algorithm")
    result = AlgorithmAssigner().assign(ctx)

    keys_to_points = {t["jira_key"]: t["story_points"] for t in picked}
    per_dev_load = {
        dev: sum(keys_to_points[k] for k in keys)
        for dev, keys in result.by_dev.items()
    }
    spread = max(per_dev_load.values()) - min(per_dev_load.values())
    assert spread <= max(keys_to_points.values()), (
        f"load spread {spread} exceeds biggest-ticket size "
        f"{max(keys_to_points.values())}: {per_dev_load}"
    )


def test_algorithm_assigner_respects_skill_when_possible() -> None:
    """A backend-only ticket should land on a backend dev when one exists."""
    devs = [
        {"name": "BackOnly", "completion_rate": 0.8, "speed": 1.0,
         "skills": ["backend"]},
        {"name": "FrontOnly", "completion_rate": 0.8, "speed": 1.0,
         "skills": ["frontend"]},
    ]
    picked = [
        {"jira_key": "SIM-1", "story_points": 5, "required_skill": "backend"},
        {"jira_key": "SIM-2", "story_points": 5, "required_skill": "frontend"},
    ]
    ctx = _ctx(picked, devs, strategy="algorithm")
    result = AlgorithmAssigner().assign(ctx)
    assert "SIM-1" in result.by_dev["BackOnly"]
    assert "SIM-2" in result.by_dev["FrontOnly"]


def test_algorithm_assigner_falls_back_when_no_skill_match() -> None:
    """When no dev has the required skill, all devs are eligible."""
    devs = [
        {"name": "OnlyBackend", "completion_rate": 0.8, "speed": 1.0,
         "skills": ["backend"]},
    ]
    picked = [
        {"jira_key": "SIM-1", "story_points": 5, "required_skill": "frontend"},
    ]
    ctx = _ctx(picked, devs, strategy="algorithm")
    result = AlgorithmAssigner().assign(ctx)
    # Fallback: the only dev gets it even though skill doesn't match.
    assert result.by_dev["OnlyBackend"] == ["SIM-1"]


# ---------- make_assigner factory ----------

def test_make_assigner_returns_known_strategies() -> None:
    assert isinstance(make_assigner("random"), RandomAssigner)
    assert isinstance(make_assigner("algorithm"), AlgorithmAssigner)


def test_make_assigner_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown assigner"):
        make_assigner("nonexistent_strategy")


# ---------- OmadaAssigner ----------

class _StubOmada:
    """Minimal OmadaObserver stand-in for OmadaAssigner tests.

    Records every call so tests can assert on push payloads, and returns
    canned responses for the two methods OmadaAssigner uses:
    generate_sprint_plan and _request (for the team roster).
    """

    def __init__(
        self,
        *,
        plan: dict | None = None,
        roster: dict | None = None,
        push_response: dict | None = None,
    ) -> None:
        self._plan = plan
        self._roster = roster
        self._push_response = push_response
        self.generate_calls: list[tuple] = []
        self.push_calls: list[tuple] = []
        self.request_calls: list[tuple] = []

    def generate_sprint_plan(self, team_id, sprint_length_days=14, sprint_start_date=None):
        self.generate_calls.append((team_id, sprint_length_days, sprint_start_date))
        return self._plan

    def push_plan_to_jira(self, team_id, sprint_name, plan, sprint_length_days=14):
        self.push_calls.append((team_id, sprint_name, plan, sprint_length_days))
        return self._push_response

    def _request(self, method, path, **kwargs):
        self.request_calls.append((method, path, kwargs))
        return self._roster


def _omada_ctx(
    picked: list[dict],
    developers: list[dict],
    omada,
    *,
    team_id: str | None,
    tmp_path: Path,
    committed_keys: list[str] | None = None,
    sprint_num: int = 1,
    run_seed: int = 42,
) -> SprintContext:
    return SprintContext(
        sprint_num=sprint_num,
        sprint_id=0,
        committed_keys=committed_keys if committed_keys is not None else [t["jira_key"] for t in picked],
        picked_tickets=picked,
        developers=developers,
        jira=None,  # type: ignore[arg-type]
        omada=omada,
        omada_team_id=team_id,
        archetype="test",
        strategy="omada",
        run_seed=run_seed,
        output_dir=tmp_path,
    )


def test_omada_assigner_no_team_id_falls_back_to_random(tmp_path: Path) -> None:
    """No team_id configured -> short-circuit before any API call, with
    every source tagged 'fallback' so post-hoc can see the degradation."""
    devs = _devs(4)
    picked = _pool(10)
    omada = _StubOmada()
    ctx = _omada_ctx(picked, devs, omada, team_id=None, tmp_path=tmp_path)

    result = OmadaAssigner().assign(ctx)

    _assert_covers_every_ticket_once(result, picked, devs)
    assert all(a.source == "fallback" for a in result.assignments)
    # Short-circuit should mean zero observer traffic.
    assert omada.generate_calls == []
    assert omada.request_calls == []
    assert omada.push_calls == []


def test_omada_assigner_empty_plan_falls_back(tmp_path: Path) -> None:
    """SprintBrain replies with an empty plan -> degrade to random but
    still persist the empty response to disk for the bug report."""
    devs = _devs(3)
    picked = _pool(8)
    omada = _StubOmada(plan={"assignments": []})
    ctx = _omada_ctx(picked, devs, omada, team_id="team-xyz", tmp_path=tmp_path)

    result = OmadaAssigner().assign(ctx)

    _assert_covers_every_ticket_once(result, picked, devs)
    assert all(a.source == "fallback" for a in result.assignments)
    assert omada.generate_calls == [("team-xyz", 1, None)]
    # Empty plan path must NOT push to Jira.
    assert omada.push_calls == []
    # The empty plan was persisted.
    assert (tmp_path / "sprint_1_plan.json").exists()


def test_omada_assigner_applies_mapped_plan(tmp_path: Path) -> None:
    """A plan with resolvable UUIDs lands tickets on the right sim devs
    with source='omada_plan', and the result is pushed back to Jira."""
    devs = _devs(4)  # Dev0, Dev1, Dev2, Dev3
    picked = [
        {"jira_key": "SIM-1", "story_points": 3, "required_skill": "any"},
        {"jira_key": "SIM-2", "story_points": 5, "required_skill": "any"},
        {"jira_key": "SIM-3", "story_points": 2, "required_skill": "any"},
    ]
    plan = {
        "assignments": [
            {"ticket_id": "SIM-1", "developer_id": "uuid-0"},
            {"ticket_id": "SIM-2", "developer_id": "uuid-1"},
            {"ticket_id": "SIM-3", "developer_id": "uuid-2"},
        ],
        "sprint_start": "2026-05-18",
    }
    roster = {
        "developers": [
            {"developerId": "uuid-0", "displayName": "Dev0"},
            {"developerId": "uuid-1", "displayName": "Dev1"},
            {"developerId": "uuid-2", "displayName": "Dev2"},
            {"developerId": "uuid-3", "displayName": "Dev3"},
        ]
    }
    omada = _StubOmada(plan=plan, roster=roster, push_response={"created": True})
    ctx = _omada_ctx(picked, devs, omada, team_id="team-xyz", tmp_path=tmp_path)

    result = OmadaAssigner().assign(ctx)

    _assert_covers_every_ticket_once(result, picked, devs)
    assert result.by_dev["Dev0"] == ["SIM-1"]
    assert result.by_dev["Dev1"] == ["SIM-2"]
    assert result.by_dev["Dev2"] == ["SIM-3"]
    assert all(a.source == "omada_plan" for a in result.assignments)
    assert result.plan_used is plan
    assert result.push_response == {"created": True}
    # Roster fetched from the right path.
    assert omada.request_calls == [
        ("GET", "/api/capacity/team/team-xyz", {})
    ]
    # Push happened with the same plan and sprint name.
    assert len(omada.push_calls) == 1
    team_id, sprint_name, pushed_plan, length = omada.push_calls[0]
    assert team_id == "team-xyz"
    assert sprint_name == "Sim Sprint 1"
    assert pushed_plan is plan
    assert length == 1


def test_omada_assigner_round_robins_unmapped(tmp_path: Path) -> None:
    """When some UUIDs don't resolve, those tickets still land on a dev
    (round-robin onto ctx.developers) with source='fallback'."""
    devs = _devs(3)  # Dev0, Dev1, Dev2
    picked = [
        {"jira_key": f"SIM-{i+1}", "story_points": 3, "required_skill": "any"}
        for i in range(5)
    ]
    plan = {
        "assignments": [
            {"ticket_id": "SIM-1", "developer_id": "uuid-0"},
            {"ticket_id": "SIM-2", "developer_id": "uuid-1"},
            {"ticket_id": "SIM-3", "developer_id": "uuid-2"},
            # These two reference UUIDs the roster doesn't know.
            {"ticket_id": "SIM-4", "developer_id": "uuid-ghost-a"},
            {"ticket_id": "SIM-5", "developer_id": "uuid-ghost-b"},
        ]
    }
    roster = {
        "developers": [
            {"developerId": "uuid-0", "displayName": "Dev0"},
            {"developerId": "uuid-1", "displayName": "Dev1"},
            {"developerId": "uuid-2", "displayName": "Dev2"},
        ]
    }
    omada = _StubOmada(plan=plan, roster=roster)
    ctx = _omada_ctx(picked, devs, omada, team_id="team-xyz", tmp_path=tmp_path)

    result = OmadaAssigner().assign(ctx)

    _assert_covers_every_ticket_once(result, picked, devs)
    sources = {a.jira_key: a.source for a in result.assignments}
    assert sources["SIM-1"] == "omada_plan"
    assert sources["SIM-2"] == "omada_plan"
    assert sources["SIM-3"] == "omada_plan"
    assert sources["SIM-4"] == "fallback"
    assert sources["SIM-5"] == "fallback"


def test_omada_assigner_fills_in_dropped_tickets(tmp_path: Path) -> None:
    """SprintBrain dropped some committed tickets entirely. The assigner
    must still cover them (round-robin, source='fallback') so the matrix
    can compare sprint sizes fairly across strategies."""
    devs = _devs(3)
    picked = [
        {"jira_key": f"SIM-{i+1}", "story_points": 3, "required_skill": "any"}
        for i in range(6)
    ]
    # Plan only covers 4 of the 6 committed tickets.
    plan = {
        "assignments": [
            {"ticket_id": "SIM-1", "developer_id": "uuid-0"},
            {"ticket_id": "SIM-2", "developer_id": "uuid-1"},
            {"ticket_id": "SIM-3", "developer_id": "uuid-2"},
            {"ticket_id": "SIM-4", "developer_id": "uuid-0"},
        ]
    }
    roster = {
        "developers": [
            {"developerId": "uuid-0", "displayName": "Dev0"},
            {"developerId": "uuid-1", "displayName": "Dev1"},
            {"developerId": "uuid-2", "displayName": "Dev2"},
        ]
    }
    omada = _StubOmada(plan=plan, roster=roster)
    ctx = _omada_ctx(picked, devs, omada, team_id="team-xyz", tmp_path=tmp_path)

    result = OmadaAssigner().assign(ctx)

    _assert_covers_every_ticket_once(result, picked, devs)
    sources = {a.jira_key: a.source for a in result.assignments}
    # First 4 came from the plan.
    for k in ["SIM-1", "SIM-2", "SIM-3", "SIM-4"]:
        assert sources[k] == "omada_plan", f"{k} should be omada_plan"
    # SIM-5 and SIM-6 were dropped -> must show up as fallback.
    for k in ["SIM-5", "SIM-6"]:
        assert sources[k] == "fallback", f"{k} should be fallback"


def test_make_assigner_returns_omada_instance() -> None:
    """make_assigner('omada') resolves via the lazy import in
    src/assigners/__init__.py once omada_assigner.py exists."""
    assert isinstance(make_assigner("omada"), OmadaAssigner)


# ---------- OmadaObserver.create_team (M5) ----------

def test_omada_observer_create_team_returns_response(monkeypatch) -> None:
    """OmadaObserver.create_team POSTs the dev payload and returns the API
    response dict on success (M5 frozen contract: teamId, isNew, developers)."""
    import httpx
    import json as _json

    from src.omada_observer import OmadaObserver

    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["path"] = req.url.path
        seen["body"] = _json.loads(req.content.decode())
        return httpx.Response(
            201,
            json={
                "teamId": "team-uuid-123",
                "name": "Sim BAL OMAD",
                "isNew": True,
                "developers": [
                    {"developerId": "dev-uuid-a", "name": "Alex"},
                    {"developerId": "dev-uuid-b", "name": "Jordan"},
                ],
            },
        )

    real_client_cls = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("src.omada_observer.httpx.Client", factory)

    with OmadaObserver("http://localhost:8000") as obs:
        resp = obs.create_team(
            "Sim BAL OMAD",
            developers=[
                {"name": "Alex", "role": "engineer"},
                {"name": "Jordan", "role": "engineer"},
            ],
        )

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/teams"
    assert seen["body"] == {
        "name": "Sim BAL OMAD",
        "developers": [
            {"name": "Alex", "role": "engineer"},
            {"name": "Jordan", "role": "engineer"},
        ],
    }
    assert resp is not None
    assert resp["teamId"] == "team-uuid-123"
    assert resp["isNew"] is True
    assert resp["developers"][0]["name"] == "Alex"


def test_omada_observer_create_team_returns_none_on_403(monkeypatch) -> None:
    """A 403 (feature flag disabled in prod) returns None so the matrix
    can fall back to the org's primary team without raising."""
    import httpx

    from src.omada_observer import OmadaObserver

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="feature disabled")

    real_client_cls = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("src.omada_observer.httpx.Client", factory)

    with OmadaObserver("http://localhost:8000") as obs:
        assert obs.create_team("Sim BAL OMAD", developers=[]) is None


def test_omada_observer_switch_board_includes_team_id_when_provided(monkeypatch) -> None:
    """When ``team_id`` is provided, switch_board includes it in the body.
    When omitted, the body is the stage-1 shape (backward-compat)."""
    import httpx
    import json as _json

    from src.omada_observer import OmadaObserver

    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(_json.loads(req.content.decode()))
        return httpx.Response(200, json={"ok": True})

    real_client_cls = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("src.omada_observer.httpx.Client", factory)

    with OmadaObserver("http://localhost:8000") as obs:
        # Stage-1 call shape — no team_id.
        assert obs.switch_board(99, "SIM_BAL_OMAD") is True
        # M5 call shape — per-team.
        assert obs.switch_board(99, "SIM_BAL_OMAD", team_id="team-xyz") is True

    assert bodies[0] == {"board_id": 99, "project_key": "SIM_BAL_OMAD"}
    assert bodies[1] == {
        "board_id": 99,
        "project_key": "SIM_BAL_OMAD",
        "team_id": "team-xyz",
    }
