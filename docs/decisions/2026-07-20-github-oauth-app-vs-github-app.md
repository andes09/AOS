# Decision: GitHub OAuth App vs. GitHub App

**Status:** Approved — switch to a GitHub App
**Date:** 2026-07-20
**Owner:** Ansh Desai
**Timebox:** 2 days investigation (this doc is the output)

## Context

The GitHub integration (`apps/api/src/integrations/github/`) currently uses a classic **OAuth App** with the `repo read:user user:email` scope, one active connection per org (`github_connections` table, one `is_active=true` row per `organization_id`). It backs the onboarding v2 flow (`GithubStep.tsx`) where the roadmap AI reads a connected org's repos.

The schema already has nullable `encrypted_refresh_token` and `token_expires_at` columns, added specifically so a later GitHub App switch wouldn't need a migration (see comment in `models/github_connection.py:17-19`).

## Finding: current OAuth scope over-grants relative to what the product promises

`GithubStep.tsx:12` tells the user Omada gets "Read-only access" and "never writes to your repos." But `repo` is GitHub's broadest OAuth-App scope — it grants **read and write** to code, commit statuses, and deployments on every repo (public and private) the authorizing user can access. There is no narrower OAuth-App scope that covers private-repo read without also including write. This is a real gap between the product's stated promise and the actual grant, independent of which path we choose — it's the strongest argument for the GitHub App path, which can request `contents: read` only.

## Comparison

| | OAuth App (current) | GitHub App |
|---|---|---|
| **Consent UX** | Single GitHub-hosted consent screen listing scopes (`repo`, `read:user`, `user:email`). User cannot exclude repos or narrow to read-only — the `repo` scope is all-or-nothing and includes write. | Install flow lets the installing admin pick "All repositories" or specific repos, and permissions are fine-grained (e.g. `contents: read`, `metadata: read`) with no write grant needed. Materially better match to what the product actually needs and what it tells the user. Install can be combined with user authorization in one redirect (`request_oauth_on_install`). |
| **Token lifecycle** | Access token from `exchange_code_for_tokens()` does not expire under classic OAuth App defaults; `token_expires_at` and `encrypted_refresh_token` exist in the schema but are unused today (no expiry, no refresh logic anywhere in the codebase). Revocation is only detected reactively, on a 401 from GitHub (`router.py:222-227`). | Installation access tokens expire in ~1 hour and must be regenerated server-to-server via a JWT signed with the GitHub App's private key (`POST /app/installations/{id}/access_tokens`). This requires new logic that doesn't exist today: JWT signing, a private key secret, and a refresh-before-use check against `token_expires_at` — which conveniently is already a column, just not wired to anything yet. |
| **Rate limits** | Flat 5,000 requests/hour per user token, regardless of org size. | Scales with installation size (base allowance plus a per-repository/per-org multiplier), giving significantly more headroom for repo-heavy analysis workloads as customer orgs grow. |
| **Migration cost from current schema** | N/A (already in place). | Low-to-moderate. Additive, not destructive: `github_connections` needs one new required field (`installation_id`; possibly `target_login`/`target_type` for the installed account). Existing nullable `token_expires_at`/`encrypted_refresh_token` columns get finally put to use (refresh caching, not user refresh tokens, since installation tokens aren't tied to a user refresh grant). `client.py` is unchanged — it just takes whatever access token it's handed, so the API-call layer doesn't care which auth path produced the token. `oauth.py`/`router.py` need real changes: new install+callback handling (`installation_id`, `setup_action` query params), JWT/installation-token minting, and a private key stored as a Railway secret. One-time operational step: register the GitHub App in the GitHub org (name, callback URL, permissions requested, generate private key). |

## Recommendation: switch to a GitHub App

Rationale:
1. **It's the only path that matches what the product already promises.** The UI says read-only; only a GitHub App can actually grant read-only (`contents: read`) without bundling in write access. This is not a nice-to-have — it's closing a real gap between stated and actual scope.
2. **Enterprise-readiness risk with OAuth Apps.** Security-conscious orgs (a plausible customer segment for a roadmap/planning tool that reads private code) increasingly restrict third-party OAuth Apps org-wide via GitHub's OAuth App access restrictions policy, while allowlisting specific GitHub Apps. Staying on OAuth App risks being blocked entirely for exactly the customers who care most about repo access scope.
3. **Rate limit headroom** matters more as the product scales to orgs with many repos, and GitHub Apps scale rather than staying flat.
4. **The schema cost was already paid.** The nullable refresh/expiry columns exist for this exact reason; this isn't a from-scratch migration, it's finishing what the schema anticipated.

Real cost to acknowledge: token-lifecycle logic (JWT signing, 1-hour refresh) doesn't exist today in any form and has to be built new — this is the bulk of the implementation effort, not the schema or the API client.

## Next step if approved

If this recommendation is signed off, a separate implementation ticket should be opened scoping: GitHub App registration, JWT/installation-token minting in `oauth.py`, updated `/connect` and `/callback` routes for the install+authorize flow, the `installation_id` migration, and updated consent copy in `GithubStep.tsx` to reflect the narrower, now-accurate read-only grant. That ticket is out of scope for this spike.

---

**Sign-off:** Approved by Ansh Desai, 2026-07-20. Follow-up: [docs/plans/2026-07-20-github-app-migration.md](../plans/2026-07-20-github-app-migration.md)
