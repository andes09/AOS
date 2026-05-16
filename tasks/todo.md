# Add --reset-sprints flag to omada-simulator

## Goal
Provide an alternative to `--clean` that preserves the Jira project, board,
and tickets — so Omada only needs to be connected to the SIM project once
manually. Subsequent runs just reset sprints/tickets in place.

## Plan

- [x] Add JiraDriver methods: `list_sprints`, `move_issues_to_backlog`
- [x] Add `run_reset_sprints` in `simulation.py` (with dry-run support,
      project-key cross-check vs setup_state.json, safety prefix check,
      sprint close, backlog move, status reset, JSON cleanup, log truncate)
- [x] Wire `--reset-sprints` into `main.py` argparse + live + dry-run dispatch
- [x] Update README (recommended workflow now uses `--reset-sprints`)
- [x] `pytest tests/ -q` → 25 passed
- [x] `--reset-sprints --dry-run` end-to-end smoke test passes
- [ ] Commit & push to main

## Notes / decisions

- The user's spec says "Delete output/*.json files" but `--simulate` reads
  `setup_state.json` — deleting it would force a re-`--setup`, defeating the
  purpose of `--reset-sprints`. Preserving `setup_state.json` is the only
  interpretation consistent with "keep the project intact, run again".
- The pre-existing unstaged change to `stage1_team.yaml` is unrelated;
  leave it out of this commit.

## Review
(filled in after implementation)
