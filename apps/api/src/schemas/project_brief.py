"""
ProjectBrief — the versioned, typed contract for the onboarding idea-interview's
extracted project brief.

Written by the idea interview (src/services/idea_interview.py) turn-by-turn;
read (eventually) by a not-yet-built roadmap generator. Lives outside both
services' directories because it's a cross-service contract, not an
implementation detail of either one.

The stored `OnboardingSession.project_brief` column stays plain JSON/JSONB —
this model is an application-layer contract, not a DB schema change. No
migration is needed or intended.

`schema_version` lets future breaking changes to this shape be told apart
from briefs written under an earlier version. It defaults to 1 for both
brand-new briefs and pre-existing (unstamped) legacy briefs, since this
change establishes v1 — there is no earlier version to distinguish from yet.
Future breaking changes should bump CURRENT_SCHEMA_VERSION and branch
`from_legacy`/validators on the incoming `schemaVersion` value.
"""

from typing import Any, get_origin

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

CURRENT_SCHEMA_VERSION = 1

# Fields that are pure application-layer metadata, never produced by the LLM
# extraction tool and never merged in by merge_brief. Excluded from the
# derived Anthropic tool schema and from content_field_aliases().
_NON_EXTRACTED_FIELDS = {"schema_version"}


class ProjectBrief(BaseModel):
    """Typed, versioned shape of the founder's onboarding project brief.

    All content fields are optional — the interview fills them in
    incrementally over several turns — and `model_validate`/`from_legacy`
    must accept partial, `{}`, or `None` input without raising (see
    `from_legacy`). Unknown/legacy keys are silently ignored (Pydantic v2
    default `extra="ignore"` behavior).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    schema_version: int = CURRENT_SCHEMA_VERSION

    # --- Core fields (present since the original hand-written tool schema) ---
    project_name: str | None = Field(
        default=None, description="Working name of the project, if stated"
    )
    problem_statement: str | None = Field(
        default=None, description="The problem being solved, in the founder's terms"
    )
    target_audience: str | None = Field(
        default=None, description="Who the project is for"
    )
    core_features: list[str] = Field(
        default_factory=list, description="Key features described so far"
    )
    scope: str | None = Field(
        default=None, description="What the first/MVP version includes"
    )
    out_of_scope: list[str] = Field(
        default_factory=list, description="Explicitly excluded from the first version"
    )
    timeline: str | None = Field(
        default=None, description="Target timeline or deadline"
    )
    tech_constraints: list[str] = Field(
        default_factory=list,
        description="Stack preferences, integrations, platform constraints",
    )
    existing_assets: list[str] = Field(
        default_factory=list, description="Existing code, designs, repos, or resources"
    )
    open_questions: list[str] = Field(
        default_factory=list, description="Things still unclear that a planner would need"
    )

    # --- Startup-purpose fields ---
    monetization_model: str | None = Field(
        default=None, description="How the project intends to make money, if applicable"
    )
    competitors: list[str] = Field(
        default_factory=list, description="Known competing products or alternatives"
    )

    # --- Learning-purpose fields ---
    target_skill: str | None = Field(
        default=None, description="The skill or technology the founder wants to get better at"
    )
    experience_level: str | None = Field(
        default=None,
        description="The founder's current experience level with the target skill",
    )

    # --- Hobby-purpose fields ---
    time_availability: str | None = Field(
        default=None,
        description="Realistic time the founder can commit (e.g. evenings/weekends)",
    )

    @classmethod
    def from_legacy(cls, brief: dict | None) -> "ProjectBrief":
        """Validate a stored brief dict of unknown vintage into a typed model.

        Handles `None`, `{}`, and any pre-existing camelCase dict that
        predates this change (missing `schemaVersion` and/or the
        purpose-specific fields) by falling back to field defaults. Never
        raises on missing keys; unknown/extra keys are ignored.

        Standalone/additive: not wired into `run_interview_turn`'s hot path.
        Intended for future typed consumers (e.g. the roadmap generator)
        reading `OnboardingSession.project_brief` off the ORM row.
        """
        return cls.model_validate(brief or {})


def _anthropic_property_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """Reshape one Pydantic v2 JSON-Schema property into Anthropic's dialect.

    Pydantic emits `X | None` as `{"anyOf": [{"type": "X"}, {"type": "null"}]}`;
    Anthropic's forced-tool-use schema expects `{"type": ["X", "null"]}`
    instead. List fields are already compatible; only "default"/"title" are
    stripped for parity with the schema this replaces.
    """
    if "anyOf" in raw:
        out: dict[str, Any] = {
            "type": [branch["type"] for branch in raw["anyOf"] if "type" in branch]
        }
    else:
        out = {"type": raw["type"]}
        if "items" in raw:
            out["items"] = raw["items"]
    if "description" in raw:
        out["description"] = raw["description"]
    return out


def anthropic_tool_properties() -> dict[str, dict[str, Any]]:
    """Derive Anthropic tool `input_schema.properties` from ProjectBrief.

    Single source of truth for the extraction tool's field list, types, and
    descriptions. `schema_version` is excluded — it's not conversation
    content. `isComplete` is NOT included here: it's an extraction-protocol
    control field, not project data, and must be layered on top by the
    caller (see `services/idea_interview.py`).
    """
    schema = ProjectBrief.model_json_schema()  # by_alias=True is the default
    properties: dict[str, dict[str, Any]] = {}
    for field_name, field_info in ProjectBrief.model_fields.items():
        if field_name in _NON_EXTRACTED_FIELDS:
            continue
        alias = field_info.alias or field_name
        properties[alias] = _anthropic_property_schema(schema["properties"][alias])
    return properties


def content_field_aliases() -> tuple[list[str], list[str]]:
    """Split ProjectBrief's content fields (excluding schema_version) into
    (scalar_aliases, list_aliases), by wire alias (camelCase).

    Used by idea_interview.py to derive its merge-field lists from this
    model's type shape instead of hand-copying the field list a second time.
    """
    scalars: list[str] = []
    lists: list[str] = []
    for field_name, field_info in ProjectBrief.model_fields.items():
        if field_name in _NON_EXTRACTED_FIELDS:
            continue
        alias = field_info.alias or field_name
        if get_origin(field_info.annotation) is list:
            lists.append(alias)
        else:
            scalars.append(alias)
    return scalars, lists
