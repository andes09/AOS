"""Typed failures for the Groq-backed LLM calls (interview, roadmap
generation, roadmap adjust).

Only one distinction matters today: a rate limit is *terminal* for the
current generation. Every other upstream failure is worth another attempt —
a malformed tool call, a dropped stream — but retrying into a 429 just burns
the same quota window and delays the user's error message. `LLMRateLimitError`
gives callers a way to say "stop here" instead of looping.

It subclasses RuntimeError deliberately: every existing
`except RuntimeError -> 502` arm keeps working unchanged, and the handlers
that care add a narrower arm in front of it.
"""

from openai import APIError, RateLimitError

RATE_LIMIT_MESSAGE = "Groq API rate limit reached. Please try again in a moment."

# Codes Groq has been observed to use for a rate limit delivered *inside* a
# stream (as an SSE error event) rather than as an HTTP 429 response.
_RATE_LIMIT_CODES = {"rate_limit_exceeded", "rate_limit_error", "rate_limited"}


class LLMRateLimitError(RuntimeError):
    """The upstream provider rate-limited us. Terminal for this generation:
    callers stop rather than retry."""


def is_rate_limit(exc: APIError) -> bool:
    """True when `exc` is a rate limit, however it arrived.

    A 429 *response* comes back as RateLimitError, but an error raised
    mid-stream reaches us as a bare APIError — the SDK doesn't map
    SSE-delivered error events onto status-code subclasses the way it does
    HTTP responses (the same quirk `_call_planner_stream` already works
    around for tool_use_failed), so the code/status have to be sniffed.
    """
    if isinstance(exc, RateLimitError):
        return True
    if getattr(exc, "status_code", None) == 429:
        return True
    return getattr(exc, "code", None) in _RATE_LIMIT_CODES
