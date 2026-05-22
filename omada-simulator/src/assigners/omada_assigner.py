"""Omada (SprintBrain) assigner: call /api/sprint-brain/plan, apply it.

This is the strategy under test in the stage-2 matrix. The flow:

1. Ask SprintBrain to plan against the team (returns a list of
   ``{ticket_id, developer_id}`` where ``developer_id`` is an Omada
   UUID).
2. Persist the raw plan to disk for post-hoc analysis.
3. Map each Omada developer UUID back to the in-simulator dev name via
   ``GET /api/capacity/team/{team_id}`` (matches on ``displayName``).
   See "Open risks §2" in the stage-2 plan — the UUID is not the sim
   identifier, so we have to bridge it ourselves.
4. Round-robin any tickets SprintBrain dropped or assigned to UUIDs we
   couldn't map, so coverage matches what Random/Algorithm produced for
   the same archetype.
5. Push the plan back to Jira (best-effort — the simulator's job is to
   surface bugs, not bail out when SprintBrain misbehaves).

When SprintBrain is unreachable or returns garbage, we degrade to the
same logic as ``RandomAssigner`` but tag every assignment with
``source="fallback"`` so the post-hoc matrix can tell "Omada degraded"
apart from a real Random run.
"""

from __future__ import annotations

import random

from src.assigners.base import (
    AssignmentResult,
    BaseAssigner,
    SprintContext,
    TicketAssignment,
    empty_by_dev,
)


def _fallback_random(ctx: SprintContext, *, reason: str) -> AssignmentResult:
    """Degrade to RandomAssigner — same logic as src/assigners/random_assigner.py.

    Source on every assignment is 'fallback' (not 'random') so post-hoc
    analysis can distinguish 'omada was supposed to do this but degraded'
    from a true random strategy run.
    """
    print(f"[omada-assigner] sprint {ctx.sprint_num}: degrading to random — {reason}")
    rng = random.Random(ctx.run_seed ^ hash(("omada-fallback", ctx.sprint_num)))
    by_dev = empty_by_dev(ctx.developers)
    assignments: list[TicketAssignment] = []
    for ticket in ctx.picked_tickets:
        dev = rng.choice(ctx.developers)
        by_dev[dev["name"]].append(ticket["jira_key"])
        assignments.append(
            TicketAssignment(
                jira_key=ticket["jira_key"],
                dev_name=dev["name"],
                source="fallback",
            )
        )
    return AssignmentResult(by_dev=by_dev, assignments=assignments)


class OmadaAssigner(BaseAssigner):
    name = "omada"

    def assign(self, ctx: SprintContext) -> AssignmentResult:
        # Import here so the assigners package stays importable even when
        # the simulation module isn't fully wired (matches the lazy-import
        # pattern in src/assigners/__init__.py).
        from src.simulation import _write_json

        # 1. Fallback short-circuit when no team is configured.
        if not ctx.omada_team_id:
            return _fallback_random(ctx, reason="no_team_id")

        # 2. Generate plan and always persist it (even when empty/None).
        plan = ctx.omada.generate_sprint_plan(
            ctx.omada_team_id, sprint_length_days=1
        )
        _write_json(
            ctx.output_dir / f"sprint_{ctx.sprint_num}_plan.json",
            plan or {},
        )

        # 3. Validate plan shape before trusting it.
        if not plan or not plan.get("assignments"):
            return _fallback_random(ctx, reason="empty_plan")

        # 4. Build UUID -> sim-dev-name map from the team roster.
        roster = ctx.omada._request(
            "GET", f"/api/capacity/team/{ctx.omada_team_id}"
        )
        uuid_to_name: dict[str, str] = {}
        if roster and roster.get("developers"):
            sim_names_lower = {d["name"].lower(): d["name"] for d in ctx.developers}
            for r in roster["developers"]:
                uuid = r.get("developerId") or r.get("developer_id")
                display = r.get("displayName") or r.get("display_name") or ""
                sim_name = sim_names_lower.get(display.lower())
                if uuid and sim_name:
                    uuid_to_name[uuid] = sim_name

        by_dev = empty_by_dev(ctx.developers)
        assignments: list[TicketAssignment] = []
        unmapped: list[str] = []
        covered: set[str] = set()

        # 5. Apply Omada's assignments where the UUID resolves.
        for entry in plan.get("assignments", []):
            ticket_id = entry.get("ticket_id")
            dev_uuid = entry.get("developer_id")
            if not ticket_id:
                continue
            covered.add(ticket_id)
            sim_name = uuid_to_name.get(dev_uuid) if dev_uuid else None
            if sim_name is not None:
                by_dev[sim_name].append(ticket_id)
                assignments.append(
                    TicketAssignment(
                        jira_key=ticket_id,
                        dev_name=sim_name,
                        source="omada_plan",
                    )
                )
            else:
                unmapped.append(ticket_id)

        # 6 + 7. Round-robin any unmapped UUIDs *and* any committed tickets
        # the plan dropped entirely, so the sprint covers exactly what
        # Random/Algorithm would have committed for the same archetype.
        dropped = [k for k in ctx.committed_keys if k not in covered]
        leftovers = unmapped + dropped
        if leftovers:
            for i, ticket_id in enumerate(leftovers):
                dev = ctx.developers[i % len(ctx.developers)]
                by_dev[dev["name"]].append(ticket_id)
                assignments.append(
                    TicketAssignment(
                        jira_key=ticket_id,
                        dev_name=dev["name"],
                        source="fallback",
                    )
                )

        # 8. Push back to Jira (best-effort — Sprint Brain push is allowed
        # to fail; the sim still has a complete in-memory assignment).
        push_resp = ctx.omada.push_plan_to_jira(
            ctx.omada_team_id,
            f"Sim Sprint {ctx.sprint_num}",
            plan,
            sprint_length_days=1,
        )
        _write_json(
            ctx.output_dir / f"sprint_{ctx.sprint_num}_push.json",
            push_resp or {},
        )

        return AssignmentResult(
            by_dev=by_dev,
            assignments=assignments,
            plan_used=plan,
            push_response=push_resp,
        )
