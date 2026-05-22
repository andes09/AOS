"""Stage-2 matrix config loader and project-key builder.

Mirrors the load_team / load_environment pattern in src/config.py: read a YAML
file from PACKAGE_ROOT/config, validate via Pydantic, raise FileNotFoundError
with a helpful "Available …" list when the file is missing.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
ARCHETYPE_DIR = CONFIG_DIR / "archetypes"
STAGE2_PATH = CONFIG_DIR / "stage2.yaml"


class ArchetypeRef(BaseModel):
    name: str


class ProjectKeyScheme(BaseModel):
    prefix: str
    archetype_codes: dict[str, str]
    strategy_codes: dict[str, str]


class Stage2Defaults(BaseModel):
    runs: int = 1
    sprint_length_minutes: int = 1
    total_sprints: int = 3


class Stage2Config(BaseModel):
    archetypes: list[ArchetypeRef]
    strategies: list[str]
    defaults: Stage2Defaults
    project_key: ProjectKeyScheme
    parallel_teams: bool = False


def load_stage2_config() -> Stage2Config:
    """Load and validate config/stage2.yaml."""
    if not STAGE2_PATH.exists():
        raise FileNotFoundError(
            f"Stage-2 config not found: {STAGE2_PATH}. "
            f"Expected at {STAGE2_PATH.relative_to(PACKAGE_ROOT)}."
        )
    with STAGE2_PATH.open() as f:
        raw = yaml.safe_load(f)
    return Stage2Config.model_validate(raw)


def load_archetype(name: str) -> dict:
    """Load config/archetypes/{name}.yaml as a plain dict.

    Same shape as src.config.load_team: archetype validation is the
    simulator's responsibility, not the loader's.
    """
    path = ARCHETYPE_DIR / f"{name}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in ARCHETYPE_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"Archetype config not found: {path}. Available archetypes: {available}"
        )
    with path.open() as f:
        return yaml.safe_load(f)


def build_project_key(
    scheme: ProjectKeyScheme, archetype: str, strategy: str
) -> str:
    """Compose 'SIM_BAL_RAND' style project key.

    Raises ValueError if either archetype or strategy is missing from the
    code maps — silent fallback would let typos leak into real Jira project
    keys.
    """
    if archetype not in scheme.archetype_codes:
        raise ValueError(
            f"Unknown archetype '{archetype}'. Available: "
            f"{sorted(scheme.archetype_codes)}"
        )
    if strategy not in scheme.strategy_codes:
        raise ValueError(
            f"Unknown strategy '{strategy}'. Available: "
            f"{sorted(scheme.strategy_codes)}"
        )
    return (
        f"{scheme.prefix}"
        f"{scheme.archetype_codes[archetype]}"
        f"{scheme.strategy_codes[strategy]}"
    )
