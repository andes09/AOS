"""Identifier extraction & normalization.

Pure-regex tokenizer for surfacing identifier-like strings from ticket text
(titles, descriptions, epics, labels, components). No DB, no Claude, no ORM.

Locked decisions (Initiative A plan):
- CamelCase requires >= 2 segments (e.g. ``OrderService``, ``TaskList`` qualify;
  bare ``Task``, ``User`` do not).
- Punctuation always qualifies: ``.``, ``_``, ``-``, ``/`` — so
  ``dbo.tile_metrics``, ``ms-service``, ``snake_case``, ``app/api/routes`` all
  match.
- Single English / common-code keywords are filtered (see ``STOPWORDS``).
- Tokens shorter than 3 chars are filtered.

The caller is responsible for any top-N cap on frequencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedToken:
    """One identifier-like token pulled from a text blob."""

    token: str            # raw, as found in text
    normalized: str       # lowercase + stripped of trailing punctuation
    source: str           # 'ticket_title'|'ticket_description'|'epic'|'label'|'component'


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


# Common English words and generic code keywords that should never count as
# identifiers on their own. Compared case-insensitively against ``normalized``.
STOPWORDS: frozenset[str] = frozenset(
    {
        # English filler
        "the", "and", "for", "with", "from", "this", "that", "these", "those",
        "are", "was", "were", "but", "not", "you", "your", "our", "all",
        # Boolean / null literals
        "true", "false", "none", "null",
        # Generic Jira / domain nouns that are too noisy to be useful
        "task", "user", "done", "todo", "bug", "story", "epic",
    }
)


# Single combined pattern with named alternatives. Order matters only for the
# named group reported by ``lastgroup``; the union of all matches is what we
# return. The five sub-patterns:
#   1. dotted   -- schema.table style (>=1 dot)
#   2. kebab    -- lower-kebab-case (>=1 hyphen)
#   3. snake    -- lower_snake_case (>=1 underscore)
#   4. camel    -- CamelCase with >=2 [A-Z][a-z]+ segments
#   5. path     -- slash/path-like (>=1 slash)
_PATTERN = re.compile(
    r"""
    (?P<dotted>\b[a-zA-Z][\w]*\.[a-zA-Z][\w.]+\b)
    | (?P<kebab>\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b)
    | (?P<snake>\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b)
    | (?P<camel>\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b)
    | (?P<path>\b[a-zA-Z][\w]*(?:/[a-zA-Z][\w]+)+\b)
    """,
    re.VERBOSE,
)


_TRAILING_PUNCT = ".,;:)]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_token(token: str) -> str:
    """Lowercase and strip trailing punctuation. Pure function.

    Internal punctuation is preserved: ``dbo.tile_metrics`` ->
    ``dbo.tile_metrics``; ``OrderService.`` -> ``orderservice``.
    """
    if not token:
        return ""
    lowered = token.lower()
    return lowered.rstrip(_TRAILING_PUNCT)


def extract_tokens(text: str, source: str) -> list[ExtractedToken]:
    """Extract identifier-like tokens from a single text blob.

    Returns tokens in order of appearance (duplicates preserved — callers can
    aggregate via :func:`count_tokens`).
    """
    if not text:
        return []

    out: list[ExtractedToken] = []
    for match in _PATTERN.finditer(text):
        raw = match.group(0)
        normalized = normalize_token(raw)
        if len(normalized) < 3:
            continue
        if normalized in STOPWORDS:
            continue
        out.append(ExtractedToken(token=raw, normalized=normalized, source=source))
    return out


def count_tokens(extracted: Iterable[ExtractedToken]) -> dict[str, int]:
    """Aggregate by normalized token. Returns ``{normalized: occurrence_count}``."""
    counts: dict[str, int] = {}
    for item in extracted:
        counts[item.normalized] = counts.get(item.normalized, 0) + 1
    return counts
