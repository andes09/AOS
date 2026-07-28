"""
GitHub App webhook signature verification — HMAC-SHA256 over the raw request
body, checked against the `X-Hub-Signature-256` header GitHub sends on every
delivery (https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).

One app-level secret (`settings.github_app_webhook_secret`) for the whole
GitHub App, not one per connection/org — there's a single webhook URL
configured once in the App's own settings, so there's no per-org secret to
generate or store (see docs/plans/2026-07-20-github-task-autocomplete.md).
"""

import hashlib
import hmac


def verify_signature(secret: str, payload: bytes, signature_header: str | None) -> bool:
    """Constant-time comparison via `hmac.compare_digest` — a naive `==` would
    leak timing information an attacker could use to forge a valid signature
    byte-by-byte."""
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)
