"""Tests for the pure-regex identifier extractor.

Covers the locked decisions from the Initiative A plan:
- punctuation-bearing identifiers always qualify (``.``, ``_``, ``-``, ``/``)
- CamelCase requires >= 2 segments
- stopwords / too-short tokens are filtered
- normalizer lowercases and strips trailing punctuation
- ``count_tokens`` aggregates by normalized form
"""

from __future__ import annotations

from src.services.identifier_extraction import (
    ExtractedToken,
    count_tokens,
    extract_tokens,
    normalize_token,
)


def _normalized(tokens: list[ExtractedToken]) -> list[str]:
    return [t.normalized for t in tokens]


# ---------------------------------------------------------------------------
# extract_tokens — happy paths for each pattern
# ---------------------------------------------------------------------------


def test_dotted_schema_table_extracted() -> None:
    tokens = extract_tokens(
        "The query reads from dbo.tile_metrics every minute.",
        source="ticket_description",
    )
    assert "dbo.tile_metrics" in _normalized(tokens)


def test_kebab_case_service_extracted() -> None:
    tokens = extract_tokens("ms-service is flaky in prod", source="ticket_title")
    assert "ms-service" in _normalized(tokens)


def test_snake_case_var_extracted() -> None:
    tokens = extract_tokens("rename snake_case_var to camel", source="ticket_title")
    assert "snake_case_var" in _normalized(tokens)


def test_camel_case_two_segments_extracted() -> None:
    tokens = extract_tokens("OrderService is down", source="ticket_title")
    assert "orderservice" in _normalized(tokens)


def test_path_like_extracted() -> None:
    tokens = extract_tokens(
        "See app/api/routes for the endpoint list", source="ticket_description"
    )
    assert "app/api/routes" in _normalized(tokens)


# ---------------------------------------------------------------------------
# extract_tokens — negative cases
# ---------------------------------------------------------------------------


def test_bare_camel_single_segment_not_extracted() -> None:
    # ``User`` is a single [A-Z][a-z]+ segment — must NOT match.
    tokens = extract_tokens("User cannot login", source="ticket_title")
    assert "user" not in _normalized(tokens)
    # And nothing identifier-like is in this sentence:
    assert tokens == []


def test_stopwords_filtered() -> None:
    # Even though ``Task`` and ``Done`` look like proper nouns, they're stopwords.
    tokens = extract_tokens("Task Done True False", source="label")
    assert tokens == []


def test_short_tokens_filtered() -> None:
    # ``a.b`` is dotted but length<3 after normalize, should not survive.
    tokens = extract_tokens("a.b is too short", source="ticket_title")
    assert _normalized(tokens) == []


def test_empty_string_returns_empty_list() -> None:
    assert extract_tokens("", source="ticket_title") == []
    assert extract_tokens("   \n\t  ", source="ticket_title") == []


# ---------------------------------------------------------------------------
# normalize_token
# ---------------------------------------------------------------------------


def test_normalize_lowercases_and_strips_trailing_punct() -> None:
    assert normalize_token("OrderService.") == "orderservice"
    assert normalize_token("dbo.tile_metrics,") == "dbo.tile_metrics"
    assert normalize_token("ms-service):") == "ms-service"


def test_normalize_preserves_internal_punctuation() -> None:
    assert normalize_token("dbo.tile_metrics") == "dbo.tile_metrics"
    assert normalize_token("snake_case_var") == "snake_case_var"
    assert normalize_token("app/api/routes") == "app/api/routes"


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


def test_count_tokens_aggregates_duplicates() -> None:
    text = (
        "OrderService failed. Restart OrderService and check ms-service. "
        "ms-service depends on dbo.tile_metrics."
    )
    tokens = extract_tokens(text, source="ticket_description")
    counts = count_tokens(tokens)
    assert counts["orderservice"] == 2
    assert counts["ms-service"] == 2
    assert counts["dbo.tile_metrics"] == 1


# ---------------------------------------------------------------------------
# Integration: multi-line description with mixed identifiers
# ---------------------------------------------------------------------------


def test_multiline_description_mixed_identifiers() -> None:
    text = """
    OrderService is timing out when calling ms-service.
    The downstream query hits dbo.tile_metrics.
    See app/api/routes and the snake_case_var flag.
    Task: investigate. User impact: high.
    """
    tokens = extract_tokens(text, source="ticket_description")
    normalized = set(_normalized(tokens))
    assert {
        "orderservice",
        "ms-service",
        "dbo.tile_metrics",
        "app/api/routes",
        "snake_case_var",
    }.issubset(normalized)
    # Stopwords + bare single-segment CamelCase should be absent.
    assert "task" not in normalized
    assert "user" not in normalized


def test_source_field_is_carried_through() -> None:
    tokens = extract_tokens("OrderService down", source="epic")
    assert all(t.source == "epic" for t in tokens)
    assert len(tokens) == 1
