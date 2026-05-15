"""Stage 1 simulation orchestration: setup, run, reset."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import EnvironmentConfig, Secrets
from src.developer import run_developer
from src.jira_driver import JiraDriver, JiraDriverError
from src.omada_observer import OmadaObserver
from src.ticket_generator import generate_ticket_pool, pick_sprint_tickets


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PACKAGE_ROOT / "output"
SETUP_STATE_PATH = OUTPUT_DIR / "setup_state.json"
RESULTS_PATH = OUTPUT_DIR / "simulation_results.json"

logger = logging.getLogger("simulation")


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str))
        print(f"[output] Wrote {path}")
    except Exception as e:
        print(f"[output] ERROR writing {path}: {e}")


async def _print_sprint_progress(
    sprint_num: int,
    total_sprints: int,
    total_tickets: int,
    results: dict,
    in_progress: set[str],
    started_at: float,
    interval: float = 15.0,
) -> None:
    """Print a single-line live progress indicator every ``interval`` seconds.

    Cancelled by the caller when the sprint ends. Uses ``\\r`` so the line
    updates in place; on cancel we emit a newline so subsequent output isn't
    glued to the bar.
    """
    bar_width = 16
    try:
        while True:
            elapsed = time.monotonic() - started_at
            done = sum(1 for r in results.values() if r == "completed")
            ip = len(in_progress)
            pct = (done / total_tickets) if total_tickets else 0.0
            filled = int(round(pct * bar_width))
            bar = "█" * filled + "░" * (bar_width - filled)
            mm = int(elapsed) // 60
            ss = int(elapsed) % 60
            line = (
                f"\r[Sprint {sprint_num}/{total_sprints}] {bar} "
                f"{int(pct * 100)}% | {mm:02d}:{ss:02d} elapsed | "
                f"{done}/{total_tickets} tickets done | {ip} in progress"
            )
            sys.stdout.write(line)
            sys.stdout.flush()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        sys.stdout.write("\n")
        sys.stdout.flush()
        raise


def _safety_check_project_key(project_key: str) -> None:
    if not project_key.startswith("SIM"):
        raise SystemExit(
            f"Jira project_key_prefix must start with 'SIM' (got {project_key!r}). "
            f"Stage 1 refuses to touch non-SIM projects."
        )


async def run_setup(
    env: EnvironmentConfig,
    secrets: Secrets,
    team_config: dict,
    *,
    force: bool = False,
    dry_run: bool = False,
    project_key_override: str | None = None,
) -> None:
    """Create the Jira SIM project, generate the ticket pool, persist state."""
    _ensure_output_dir()

    project_key = project_key_override or env.jira.project_key_prefix or "SIM"
    _safety_check_project_key(project_key)
    # Default project name collides with Jira's post-deletion name
    # reservation. When the caller picks a non-default key, derive a
    # matching unique name so the create call doesn't 400.
    project_name = (
        "Omada Simulation"
        if project_key == "SIM"
        else f"Omada Simulation ({project_key})"
    )

    if SETUP_STATE_PATH.exists() and not force:
        raise SystemExit(
            f"{SETUP_STATE_PATH} already exists. Use --force to overwrite, "
            f"or --reset --confirm to tear down."
        )

    pool = generate_ticket_pool(team_config)
    dep_density = float(team_config.get("dependency_density", 0.1))
    n_links = max(0, int(round(len(pool) * dep_density)))

    if dry_run:
        print(f"[DRY RUN] Would create Jira project '{project_key}' at {env.jira.url}")
        print(f"[DRY RUN] Would generate {len(pool)} tickets")
        types: dict[str, int] = {}
        skills: dict[str, int] = {}
        for t in pool:
            types[t["issue_type"]] = types.get(t["issue_type"], 0) + 1
            skills[t["required_skill"]] = skills.get(t["required_skill"], 0) + 1
        print(f"[DRY RUN]   Type breakdown:  {types}")
        print(f"[DRY RUN]   Skill breakdown: {skills}")
        print(f"[DRY RUN] Would create ~{n_links} 'Blocks' issue links")
        print(f"[DRY RUN] Would persist state to {SETUP_STATE_PATH}")
        return

    print(f"Creating Jira project '{project_key}' at {env.jira.url} ...")
    with JiraDriver(env.jira.url, secrets.jira_email, secrets.jira_api_token) as jira:
        jira.get_or_create_project(project_key, project_name)
        board_id = jira.get_board_id(project_key)

        try:
            from tqdm import tqdm  # optional, fallback below

            iterator = tqdm(pool, desc="Creating tickets", unit="ticket")
        except ImportError:
            iterator = pool

        ticket_keys: list[str] = []
        for ticket in iterator:
            key = jira.create_ticket(
                project_key,
                ticket["summary"],
                ticket["issue_type"],
                ticket["story_points"],
                labels=[ticket["label_suffix"]],
                description=ticket["description"],
            )
            ticket["jira_key"] = key
            ticket_keys.append(key)

        dep_pairs: list[list[str]] = []
        if n_links > 0 and len(ticket_keys) >= 2:
            rng = random.Random(123)
            for _ in range(n_links):
                a, b = rng.sample(ticket_keys, 2)
                jira.create_issue_link(a, b)
                dep_pairs.append([a, b])

    state = {
        "project_key": project_key,
        "board_id": board_id,
        "pool": pool,
        "ticket_keys": ticket_keys,
        "dependency_pairs": dep_pairs,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(SETUP_STATE_PATH, state)
    print(
        f"Setup complete. {len(ticket_keys)} tickets, "
        f"{len(dep_pairs)} dependency links. State → {SETUP_STATE_PATH}"
    )


async def run_simulation(
    env: EnvironmentConfig,
    secrets: Secrets,
    team_config: dict,
    *,
    dry_run: bool = False,
    project_key_override: str | None = None,
) -> None:
    """Drive 3 sprints. Capture every Omada response. Generate bug report."""
    _ensure_output_dir()

    if not SETUP_STATE_PATH.exists():
        if not dry_run:
            raise SystemExit(
                f"{SETUP_STATE_PATH} not found. Run --setup first."
            )
        # Dry-run preview without a real setup: synthesise an empty state so
        # the user can still see the plan shape.
        state = {"project_key": "SIM (not yet created)", "board_id": 0, "pool": []}
    else:
        state = json.loads(SETUP_STATE_PATH.read_text())

    pool: list[dict] = state["pool"]
    project_key = project_key_override or state["project_key"]
    board_id = state["board_id"]
    if project_key_override:
        _safety_check_project_key(project_key)

    total_sprints = int(team_config.get("total_sprints", 3))
    duration_min = int(team_config.get("sprint_length_minutes", 30))
    omada_team_id = (team_config.get("omada_team_id") or "").strip()
    developers = team_config["developers"]

    if dry_run:
        print(f"[DRY RUN] Project: {project_key}  Board: {board_id}")
        print(f"[DRY RUN] {total_sprints} sprints × {duration_min} min each")
        print(f"[DRY RUN] Pool remaining: {len(pool)} tickets")
        print(f"[DRY RUN] Developers: {[d['name'] for d in developers]}")
        if not omada_team_id:
            print(
                "[DRY RUN] omada_team_id not set in team config — team-scoped "
                "Omada calls (plan, push, retro, health, deps) will be skipped or "
                "fail and be logged as bugs."
            )
        for sn in range(1, total_sprints + 1):
            print(
                f"[DRY RUN] Sprint {sn}: pick tickets, create Jira sprint, "
                f"trigger Omada sync, generate plan, push plan, run devs, "
                f"close sprint, fetch retro/health/deps"
            )
        print("[DRY RUN] Would write simulation_results.json and BUGS_INTEGRATION.md")
        return

    sprint_results: list[dict] = []
    inter_sprint_wait = 10

    with (
        JiraDriver(env.jira.url, secrets.jira_email, secrets.jira_api_token) as jira,
        OmadaObserver(env.omada.api_url) as omada,
    ):
        resolved = omada.resolve_team_id()
        if resolved:
            print(f"[omada] Resolved team ID: {resolved}")
            omada_team_id = resolved
        elif not omada_team_id:
            print(
                "[warning] Could not resolve Omada team ID — "
                "Omada-side calls will be skipped"
            )

        for sprint_num in range(1, total_sprints + 1):
            print(f"\n=== Sprint {sprint_num}/{total_sprints} ===")

            picked = pick_sprint_tickets(pool, developers, sprint_num)
            committed_keys = [t["jira_key"] for t in picked]
            print(f"Picked {len(committed_keys)} tickets for this sprint")

            sprint_start = datetime.now(timezone.utc)
            sprint_end = sprint_start + timedelta(minutes=duration_min)
            try:
                sprint_id = jira.create_sprint(
                    board_id,
                    f"Sim Sprint {sprint_num}",
                    sprint_start.isoformat(),
                    sprint_end.isoformat(),
                )
                jira.add_issues_to_sprint(sprint_id, committed_keys)
            except JiraDriverError as e:
                logger.error("Sprint %s setup failed: %s", sprint_num, e)
                sprint_results.append({
                    "sprint_num": sprint_num,
                    "error": str(e),
                    "committed": len(committed_keys),
                    "completed": 0,
                    "spillover": len(committed_keys),
                    "sync_ok": False,
                    "plan_ok": False,
                    "push_ok": False,
                    "retro_ok": False,
                    "ticket_results": {},
                })
                continue

            # Capture the pre-sync timestamp so we can detect when the Celery
            # task finishes by watching last_synced_at advance.
            pre_status = omada.get_sync_status() if omada_team_id else None
            baseline_synced_at = (pre_status or {}).get("last_synced_at")

            sync_resp = omada.trigger_sync(omada_team_id) if omada_team_id else None
            if omada_team_id and sync_resp:
                confirmed = await asyncio.to_thread(
                    omada.wait_for_sync,
                    before=baseline_synced_at,
                    timeout=60.0,
                    interval=2.0,
                )
                if not confirmed:
                    logger.warning(
                        "Jira sync did not confirm within 60s; "
                        "falling back to 30s fixed wait before /plan"
                    )
                    await asyncio.sleep(30)
            else:
                await asyncio.sleep(10)

            plan = (
                omada.generate_sprint_plan(omada_team_id, sprint_length_days=1)
                if omada_team_id
                else None
            )
            _write_json(OUTPUT_DIR / f"sprint_{sprint_num}_plan.json", plan or {})

            push_resp = None
            if plan and omada_team_id:
                push_resp = omada.push_plan_to_jira(
                    omada_team_id, f"Sim Sprint {sprint_num}", plan
                )
            _write_json(OUTPUT_DIR / f"sprint_{sprint_num}_push.json", push_resp or {})

            by_dev: dict[str, list[str]] = {d["name"]: [] for d in developers}
            for t in picked:
                by_dev.setdefault(t["assigned_dev"], []).append(t["jira_key"])

            results: dict[str, str] = {}
            in_progress_keys: set[str] = set()
            coros = [
                run_developer(
                    d,
                    by_dev[d["name"]],
                    duration_min,
                    jira,
                    results,
                    in_progress_keys,
                )
                for d in developers
            ]
            print(
                f"Running {len(developers)} developers for {duration_min} minutes..."
            )
            progress_task = asyncio.create_task(
                _print_sprint_progress(
                    sprint_num,
                    total_sprints,
                    len(committed_keys),
                    results,
                    in_progress_keys,
                    time.monotonic(),
                )
            )
            try:
                await asyncio.gather(*coros)
            finally:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass

            try:
                jira.close_sprint(sprint_id)
            except JiraDriverError as e:
                logger.warning("close_sprint failed for %s: %s", sprint_id, e)

            if omada_team_id:
                omada.trigger_sync(omada_team_id)

            retro_gen = (
                omada.generate_retro(str(sprint_id))
                if omada_team_id
                else None
            )
            retro_get = (
                omada.get_retro(str(sprint_id)) if omada_team_id else None
            )
            retro = retro_gen or retro_get
            _write_json(
                OUTPUT_DIR / f"sprint_{sprint_num}_retro.json",
                {"generate": retro_gen or {}, "get": retro_get or {}},
            )

            health = (
                omada.get_health_score(omada_team_id) if omada_team_id else None
            )
            _write_json(OUTPUT_DIR / f"sprint_{sprint_num}_health.json", health or {})

            deps = (
                omada.get_dependency_radar(omada_team_id) if omada_team_id else None
            )
            _write_json(OUTPUT_DIR / f"sprint_{sprint_num}_deps.json", deps or {})

            features = omada.get_features()
            _write_json(
                OUTPUT_DIR / f"sprint_{sprint_num}_features.json", features or {}
            )

            committed = len(committed_keys)
            completed = sum(1 for r in results.values() if r == "completed")
            sprint_results.append({
                "sprint_num": sprint_num,
                "jira_sprint_id": sprint_id,
                "committed": committed,
                "completed": completed,
                "spillover": committed - completed,
                "sync_ok": sync_resp is not None,
                "plan_ok": plan is not None,
                "push_ok": push_resp is not None,
                "retro_ok": retro is not None,
                "retro_get_ok": retro_get is not None,
                "health_ok": health is not None,
                "deps_ok": deps is not None,
                "features_ok": features is not None,
                "ticket_results": results,
            })

            print(
                f"Sprint {sprint_num} done: "
                f"{completed}/{committed} completed "
                f"(plan={'ok' if plan else 'fail'} "
                f"push={'ok' if push_resp else 'fail'} "
                f"retro={'ok' if retro else 'fail'})"
            )

            if sprint_num < total_sprints:
                await asyncio.sleep(inter_sprint_wait)

    simulation_results = {
        "env": env.name,
        "team": team_config["team_name"],
        "sprint_length_minutes": duration_min,
        "total_sprints": total_sprints,
        "omada_team_id": omada_team_id or None,
        "sprints": sprint_results,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(RESULTS_PATH, simulation_results)

    from src.reporting import generate_bug_report

    generate_bug_report(simulation_results)
    print("\nSimulation complete. See output/BUGS_INTEGRATION.md")


async def run_reset(
    env: EnvironmentConfig,
    secrets: Secrets,
    *,
    confirm: bool = False,
    dry_run: bool = False,
    project_key_override: str | None = None,
) -> None:
    """Delete the SIM Jira project and remove setup_state.json."""
    _ensure_output_dir()

    if not confirm:
        raise SystemExit("--reset requires --confirm to proceed.")

    project_key = project_key_override or env.jira.project_key_prefix or "SIM"
    _safety_check_project_key(project_key)

    if dry_run:
        print(f"[DRY RUN] Would DELETE Jira project '{project_key}'")
        print(f"[DRY RUN] Would remove {SETUP_STATE_PATH}")
        return

    with JiraDriver(env.jira.url, secrets.jira_email, secrets.jira_api_token) as jira:
        try:
            jira.delete_project(project_key)
            print(f"Deleted Jira project '{project_key}'")
        except JiraDriverError as e:
            print(f"Project delete failed (continuing): {e}")

    if SETUP_STATE_PATH.exists():
        SETUP_STATE_PATH.unlink()
        print(f"Removed {SETUP_STATE_PATH}")
    else:
        print("No setup_state.json to remove.")


async def run_clean(
    env: EnvironmentConfig,
    secrets: Secrets,
    *,
    project_key_override: str,
    dry_run: bool = False,
) -> None:
    """Full simulator reset: delete Jira project, wipe JSON output, truncate logs."""
    _ensure_output_dir()

    await run_reset(
        env, secrets,
        confirm=True,
        dry_run=dry_run,
        project_key_override=project_key_override,
    )

    json_files = sorted(OUTPUT_DIR.glob("*.json"))
    log_files = [OUTPUT_DIR / "jira_audit.log", OUTPUT_DIR / "omada_audit.log"]

    if dry_run:
        for path in json_files:
            print(f"[DRY RUN] Would delete {path}")
        for path in log_files:
            if path.exists():
                print(f"[DRY RUN] Would truncate {path}")
        print("[DRY RUN] Simulator reset complete. Ready for --setup.")
        return

    for path in json_files:
        path.unlink()
        print(f"Removed {path}")

    for path in log_files:
        if path.exists():
            path.write_text("")
            print(f"Truncated {path}")

    print("Simulator reset complete. Ready for --setup.")
