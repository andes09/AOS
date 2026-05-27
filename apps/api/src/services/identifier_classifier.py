"""
Identifier classifier — Claude maps extracted code-identifier tokens to
team-stack skills + a coarse domain bucket.

Public entry point: :func:`classify_identifiers`.

Locked decisions (Initiative A Wave 1):
- Caller is responsible for capping input to the top-200 tokens per team
  by occurrence frequency.
- This service batches tokens (default 50 per Claude call) and issues
  ceil(N/50) requests sequentially.
- Each input token gets exactly one :class:`ClassifiedIdentifier` back.
- Unknown / hallucinated skills returned by Claude are coerced to
  ``"unknown"`` so downstream consumers can trust the contract.
- Missing tokens (Claude returned fewer items than asked) default to
  ``skill="unknown"``, ``domain=None``, ``confidence=0.0``.

The caller (router, SA-5) is expected to resolve the Anthropic API key from
the team's org and pass it in via ``anthropic_api_key``. We do **not**
reach into the DB here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import anthropic

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096
_VALID_DOMAINS = {"backend", "frontend", "infra", "data", "unknown"}


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassifiedIdentifier:
    """A single Claude classification result, joined back to its input row.

    ``token`` is preserved verbatim from the caller so the upsert in the
    router can stash both the raw + normalized forms.
    """

    token: str
    normalized_token: str
    skill: str
    domain: str | None
    confidence: float
    occurrence_count: int


# ---------------------------------------------------------------------------
# Claude tool schema
# ---------------------------------------------------------------------------


_IDENTIFIER_CLASSIFIER_TOOL: dict = {
    "name": "classify_identifiers",
    "description": "Classify a batch of code-identifier tokens by which skill they belong to.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "normalized_token": {"type": "string"},
                        "skill": {
                            "type": "string",
                            "description": (
                                "Must be one of the provided team_stack labels, "
                                "or 'unknown' if none fit."
                            ),
                        },
                        "domain": {
                            "type": "string",
                            "enum": ["backend", "frontend", "infra", "data", "unknown"],
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                    "required": [
                        "normalized_token",
                        "skill",
                        "domain",
                        "confidence",
                    ],
                },
            },
        },
        "required": ["classifications"],
    },
}


_SYSTEM_PROMPT = """\
You map code-identifier tokens to engineering skills and a coarse domain bucket.

Each token may be a database table (e.g. `dbo.tile_metrics`), a service or \
binary name (`ms-billing`), a class (`OrderController`), a file path \
(`apps/web/src/api.ts`), or a function name (`refresh_token`).

For every token in the batch:
1. **skill** — pick a label from the team_stack list provided in the user \
message, verbatim (no rewording, no casing changes). If none of the labels \
fit, return the literal string `"unknown"`.
2. **domain** — infer from the name shape:
   - `backend`: services, controllers, server-side classes, API routes \
     (e.g. `OrderController`, `refresh_token`, `ms-billing`)
   - `frontend`: UI components, page paths, client modules \
     (e.g. `LoginForm`, `apps/web/src/Header.tsx`)
   - `infra`: deploys, k8s, terraform, CI, Docker (e.g. `helm-chart`, \
     `terraform-aws-vpc`, `Dockerfile`)
   - `data`: tables, schemas, ETL, warehouses \
     (e.g. `dbo.tile_metrics`, `fact_orders`, `etl_runner`)
   - `unknown`: nothing fits
3. **confidence** — 0.0 to 1.0. Use < 0.6 whenever the token is ambiguous \
or you had to guess.

Always respond by calling the `classify_identifiers` tool. Return one entry \
per input token, preserving the `normalized_token` string exactly.\
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_user_message(batch: list[str], team_stack: list[str]) -> str:
    stack_lines = "\n".join(f"- {label}" for label in team_stack) or "- (none)"
    token_lines = "\n".join(f"- {tok}" for tok in batch)
    return (
        "## Team tech stack\n"
        f"{stack_lines}\n\n"
        "## Tokens to classify\n"
        f"{token_lines}\n\n"
        "Classify every token above and call `classify_identifiers`."
    )


async def _classify_batch(
    client: anthropic.AsyncAnthropic,
    batch_normalized: list[str],
    team_stack: list[str],
) -> dict[str, dict]:
    """Run one Claude call. Returns ``{normalized_token: {skill, domain, confidence}}``."""
    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": _build_user_message(batch_normalized, team_stack)}
            ],
            tools=[_IDENTIFIER_CLASSIFIER_TOOL],
            tool_choice={"type": "tool", "name": "classify_identifiers"},
        )
    except anthropic.AuthenticationError as exc:
        raise ValueError(
            "Invalid Anthropic API key. Please update your key in Settings."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            "Anthropic API rate limit reached. Please wait a moment and try again."
        ) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc.message}") from exc

    tool_block = next(
        (
            b
            for b in response.content
            if getattr(b, "type", None) == "tool_use"
            and getattr(b, "name", None) == "classify_identifiers"
        ),
        None,
    )
    if tool_block is None:
        logger.warning(
            "Claude did not return a classify_identifiers tool call; "
            "all %d tokens in batch will default to unknown.",
            len(batch_normalized),
        )
        return {}

    raw = tool_block.input.get("classifications", []) or []
    out: dict[str, dict] = {}
    for item in raw:
        norm = item.get("normalized_token")
        if not isinstance(norm, str):
            continue
        out[norm] = item
    return out


def _coerce_skill(raw_skill: object, team_stack: list[str]) -> str:
    """Coerce Claude's skill to a known label or 'unknown'.

    We accept either a verbatim team_stack label or the sentinel ``"unknown"``.
    Anything else (hallucinated label, casing drift) is coerced to ``"unknown"``.
    This keeps the downstream intensity service free of validation work.
    """
    if not isinstance(raw_skill, str):
        return "unknown"
    if raw_skill in team_stack:
        return raw_skill
    if raw_skill == "unknown":
        return "unknown"
    return "unknown"


def _coerce_domain(raw_domain: object) -> str | None:
    """Coerce domain to one of the valid buckets or None for 'unknown'/invalid."""
    if not isinstance(raw_domain, str) or raw_domain not in _VALID_DOMAINS:
        return None
    if raw_domain == "unknown":
        return None
    return raw_domain


def _coerce_confidence(raw_confidence: object) -> float:
    try:
        value = float(raw_confidence)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def classify_identifiers(
    tokens: list[tuple[str, str, int]],
    team_stack: list[str],
    anthropic_api_key: str,
    batch_size: int = 50,
) -> list[ClassifiedIdentifier]:
    """Classify identifier tokens into team-stack skills + domain via Claude.

    Args:
        tokens: ``[(raw_token, normalized_token, occurrence_count), ...]``.
            Caller is responsible for capping to the top-N (200) by
            occurrence frequency before calling.
        team_stack: The team's tech_stack labels, e.g.
            ``['SQL', 'Java/Spring Boot']``. Passed verbatim to Claude.
        anthropic_api_key: Resolved (decrypted) Anthropic key. The router
            owns key resolution; do not look it up here.
        batch_size: How many tokens to send per Claude call. Default 50,
            i.e. at most 4 calls for the top-200 cap.

    Returns:
        One :class:`ClassifiedIdentifier` per input token, in the input
        order. Tokens Claude failed to classify (missing from response,
        hallucinated skill, or invalid domain) default to
        ``skill="unknown"``, ``domain=None``, ``confidence=0.0``.

    Raises:
        ValueError: invalid Anthropic API key.
        RuntimeError: rate limit hit or other Anthropic API error.
    """
    if not tokens:
        return []
    if batch_size <= 0:
        raise ValueError("batch_size must be a positive integer.")

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

    # Aggregate Claude responses keyed by normalized_token across all batches.
    classified_map: dict[str, dict] = {}
    normalized_only = [t[1] for t in tokens]

    for i in range(0, len(normalized_only), batch_size):
        batch = normalized_only[i : i + batch_size]
        batch_result = await _classify_batch(client, batch, team_stack)
        # First-write wins per normalized_token — duplicate inputs are rare
        # but if Claude classifies a token twice we keep the first response.
        for norm, item in batch_result.items():
            classified_map.setdefault(norm, item)

    # Reattach raw_token + occurrence_count, coerce + default missing.
    results: list[ClassifiedIdentifier] = []
    for raw_token, normalized_token, occurrence_count in tokens:
        item = classified_map.get(normalized_token)
        if item is None:
            results.append(
                ClassifiedIdentifier(
                    token=raw_token,
                    normalized_token=normalized_token,
                    skill="unknown",
                    domain=None,
                    confidence=0.0,
                    occurrence_count=occurrence_count,
                )
            )
            continue

        results.append(
            ClassifiedIdentifier(
                token=raw_token,
                normalized_token=normalized_token,
                skill=_coerce_skill(item.get("skill"), team_stack),
                domain=_coerce_domain(item.get("domain")),
                confidence=_coerce_confidence(item.get("confidence")),
                occurrence_count=occurrence_count,
            )
        )

    return results
