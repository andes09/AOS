"""Render the Stage 1 integration bug report."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PACKAGE_ROOT / "output"
REPORT_PATH = OUTPUT_DIR / "BUGS_INTEGRATION.md"


def _ok(flag: bool) -> str:
    return "✅" if flag else "❌"


def _bullets(items: list[str]) -> list[str]:
    return [f"- {x}" for x in items] if items else ["- (none observed)"]


def generate_bug_report(simulation_results: dict) -> None:
    """Write output/BUGS_INTEGRATION.md from simulation_results.json shape."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sprints = simulation_results.get("sprints", [])

    header = [
        "# Omada Stage 1 — Integration Bug Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Environment: {simulation_results.get('env', '?')}",
        f"- Team: {simulation_results.get('team', '?')}",
        f"- Sprints: {len(sprints)} × "
        f"{simulation_results.get('sprint_length_minutes', '?')} min",
        f"- Omada team id: "
        f"{simulation_results.get('omada_team_id') or '(not configured — Omada-side calls skipped)'}",
        "",
    ]

    summary_table = [
        "## Per-sprint summary",
        "",
        "| Sprint | Committed | Completed | Spillover | Sync | Plan | Push | Retro | Health | Deps | Features |",
        "|--------|-----------|-----------|-----------|------|------|------|-------|--------|------|----------|",
    ]
    for s in sprints:
        summary_table.append(
            f"| {s.get('sprint_num')} "
            f"| {s.get('committed', 0)} "
            f"| {s.get('completed', 0)} "
            f"| {s.get('spillover', 0)} "
            f"| {_ok(s.get('sync_ok', False))} "
            f"| {_ok(s.get('plan_ok', False))} "
            f"| {_ok(s.get('push_ok', False))} "
            f"| {_ok(s.get('retro_ok', False))} "
            f"| {_ok(s.get('health_ok', False))} "
            f"| {_ok(s.get('deps_ok', False))} "
            f"| {_ok(s.get('features_ok', False))} |"
        )

    critical: list[str] = []
    high: list[str] = []
    medium: list[str] = []

    for s in sprints:
        sn = s.get("sprint_num")
        if s.get("error"):
            critical.append(
                f"Sprint {sn}: setup raised — {s['error']}"
            )
        if not s.get("sync_ok"):
            high.append(
                f"Sprint {sn}: POST /api/integrations/jira/sync returned no payload."
            )
        if not s.get("plan_ok"):
            critical.append(
                f"Sprint {sn}: POST /api/sprint-brain/plan failed — "
                f"see output/sprint_{sn}_plan.json and omada_audit.log."
            )
        if s.get("plan_ok") and not s.get("push_ok"):
            high.append(
                f"Sprint {sn}: plan generated but push-to-jira failed — "
                f"see output/sprint_{sn}_push.json."
            )
        if not s.get("retro_ok"):
            medium.append(
                f"Sprint {sn}: retro fetch returned None — "
                f"see output/sprint_{sn}_retro.json."
            )
        if not s.get("health_ok"):
            medium.append(
                f"Sprint {sn}: velocity/health endpoint returned None."
            )
        if not s.get("deps_ok"):
            medium.append(
                f"Sprint {sn}: dependency-radar returned None."
            )
        if not s.get("features_ok"):
            high.append(
                f"Sprint {sn}: GET /api/features returned None — "
                f"basic connectivity/auth may be broken."
            )
        committed = s.get("committed", 0)
        completed = s.get("completed", 0)
        if committed and completed == 0:
            high.append(
                f"Sprint {sn}: 0/{committed} tickets completed — Jira "
                f"transitions to Done likely never happened. Check jira_audit.log."
            )

    worked: list[str] = []
    for s in sprints:
        if s.get("sync_ok"):
            worked.append(f"Sprint {s['sprint_num']}: Jira→Omada sync reached server.")
        if s.get("plan_ok"):
            worked.append(f"Sprint {s['sprint_num']}: Sprint Brain returned a plan.")
        if s.get("push_ok"):
            worked.append(f"Sprint {s['sprint_num']}: push-to-jira succeeded.")
        if s.get("retro_ok"):
            worked.append(f"Sprint {s['sprint_num']}: retro endpoint returned data.")

    bug_sections = [
        "",
        "## Bugs found",
        "",
        "### Critical",
        *_bullets(critical),
        "",
        "### High",
        *_bullets(high),
        "",
        "### Medium",
        *_bullets(medium),
    ]

    verification = [
        "",
        "## What worked",
        "",
        *_bullets(sorted(set(worked))),
        "",
        "## Manual verification checklist",
        "",
        "- Open Jira → SIM project board → confirm 3 sprints exist and each "
        "shows committed vs completed counts matching the table above.",
        "- Open Omada UI → sprint dashboard for the synced team → confirm "
        "velocity chart and dependency radar populate.",
        "- Open Omada UI → retro view for each sprint → confirm patterns / "
        "insights rendered.",
        "- Confirm no production URL was hit (grep omada_audit.log for "
        "'production').",
        "",
        "## Cron scheduler checklist",
        "",
        "- Confirm the hourly Jira sync job in apps/api/src/worker.py ran "
        "during the simulation window.",
        "- Confirm no duplicate ticket rows were created on the Omada side "
        "across repeat syncs.",
        "- Confirm sprint_alerts table received entries if alerting is wired.",
        "",
        "## Raw output files",
        "",
        "- output/setup_state.json — Jira project + ticket pool snapshot",
        "- output/simulation_results.json — per-sprint structured results",
        "- output/sprint_{N}_plan.json — Sprint Brain plan response",
        "- output/sprint_{N}_push.json — push-to-jira response",
        "- output/sprint_{N}_retro.json — retro response",
        "- output/sprint_{N}_health.json — velocity/health response",
        "- output/sprint_{N}_deps.json — dependency-radar response",
        "- output/jira_audit.log — every Jira API call with status + duration",
        "- output/omada_audit.log — every Omada API call with status + body preview",
        "",
    ]

    REPORT_PATH.write_text(
        "\n".join(header + summary_table + bug_sections + verification)
    )
    print(f"Bug report → {REPORT_PATH}")
