"""Unit tests for the versioned ProjectBrief schema and its Anthropic tool
schema derivation. Does not touch test_idea_interview.py."""

from src.schemas.project_brief import (
    CURRENT_SCHEMA_VERSION,
    ProjectBrief,
    anthropic_tool_properties,
    content_field_aliases,
)
from src.services.idea_interview import _BRIEF_TOOL, merge_brief

_ORIGINAL_FIELD_ALIASES = [
    "projectName",
    "problemStatement",
    "targetAudience",
    "coreFeatures",
    "scope",
    "outOfScope",
    "timeline",
    "techConstraints",
    "existingAssets",
    "openQuestions",
]

_PURPOSE_FIELD_ALIASES = [
    "monetizationModel",
    "competitors",
    "targetSkill",
    "experienceLevel",
    "timeAvailability",
]


def test_full_valid_brief_round_trips_to_expected_dict_shape():
    payload = {
        "schemaVersion": 1,
        "projectName": "Roadmapper",
        "problemStatement": "planning is hard",
        "targetAudience": "founders",
        "coreFeatures": ["chat", "roadmap view"],
        "scope": "MVP chat",
        "outOfScope": ["mobile app"],
        "timeline": "3 months",
        "techConstraints": ["Python", "React"],
        "existingAssets": ["a Figma mockup"],
        "openQuestions": ["hosting provider?"],
        "monetizationModel": "subscription",
        "competitors": ["Acme Planner"],
        "targetSkill": "React",
        "experienceLevel": "beginner",
        "timeAvailability": "weekends",
    }
    brief = ProjectBrief.model_validate(payload)
    assert brief.model_dump(by_alias=True) == payload


def test_partial_brief_defaults_missing_fields():
    brief = ProjectBrief.model_validate({"projectName": "X"})
    assert brief.project_name == "X"
    assert brief.problem_statement is None
    assert brief.target_audience is None
    assert brief.core_features == []
    assert brief.out_of_scope == []
    assert brief.monetization_model is None
    assert brief.competitors == []
    assert brief.schema_version == 1


def test_legacy_brief_missing_schema_version_and_purpose_fields():
    legacy = {
        "projectName": "Roadmapper",
        "problemStatement": "planning is hard",
        "targetAudience": "founders",
        "coreFeatures": ["chat"],
        "scope": "MVP chat",
        "timeline": "3 months",
        "isComplete": True,  # extraction-only field, not part of ProjectBrief
    }
    brief = ProjectBrief.from_legacy(legacy)
    assert brief.schema_version == CURRENT_SCHEMA_VERSION == 1
    assert brief.project_name == "Roadmapper"
    assert brief.timeline == "3 months"
    assert brief.monetization_model is None
    assert brief.competitors == []
    assert brief.target_skill is None
    assert brief.experience_level is None
    assert brief.time_availability is None


def test_empty_dict_and_none_do_not_raise():
    assert ProjectBrief.model_validate({}) == ProjectBrief()
    assert ProjectBrief.from_legacy(None) == ProjectBrief()


def test_from_legacy_ignores_unknown_keys():
    brief = ProjectBrief.from_legacy({"somethingFromTheFuture": 123, "projectName": None})
    assert brief.project_name is None


def test_content_field_aliases_splits_scalar_vs_list():
    scalars, lists = content_field_aliases()
    assert set(scalars) == {
        "projectName", "problemStatement", "targetAudience", "scope", "timeline",
        "monetizationModel", "targetSkill", "experienceLevel", "timeAvailability",
    }
    assert set(lists) == {
        "coreFeatures", "outOfScope", "techConstraints", "existingAssets",
        "openQuestions", "competitors",
    }
    assert "schemaVersion" not in scalars and "schemaVersion" not in lists


def test_anthropic_tool_properties_shape():
    properties = anthropic_tool_properties()

    for alias in _ORIGINAL_FIELD_ALIASES + _PURPOSE_FIELD_ALIASES:
        assert alias in properties, alias
        prop = properties[alias]
        assert "anyOf" not in prop
        if prop["type"] == "array":
            assert "items" in prop
        else:
            assert prop["type"] in ("string", ["string", "null"])

    assert "schemaVersion" not in properties
    assert "isComplete" not in properties


def test_brief_tool_derivation_matches_original_hand_written_shape():
    assert _BRIEF_TOOL["name"] == "update_project_brief"
    schema = _BRIEF_TOOL["input_schema"]
    assert schema["required"] == ["isComplete"]
    assert schema["properties"]["isComplete"]["type"] == "boolean"
    for alias in _ORIGINAL_FIELD_ALIASES:
        assert alias in schema["properties"]


def test_merge_brief_still_ignores_purpose_fields_absent_from_extraction():
    merged = merge_brief({}, {"projectName": "X"})
    assert "monetizationModel" not in merged
    assert "competitors" not in merged

    merged = merge_brief({}, {"monetizationModel": "subscriptions", "competitors": ["Acme"]})
    assert merged["monetizationModel"] == "subscriptions"
    assert merged["competitors"] == ["Acme"]
