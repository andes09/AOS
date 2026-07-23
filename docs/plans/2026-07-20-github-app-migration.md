# GitHub App Migration (OAuth App → GitHub App)

## Context

Follow-up to [docs/decisions/2026-07-20-github-oauth-app-vs-github-app.md](../decisions/2026-07-20-github-oauth-app-vs-github-app.md), approved 2026-07-20: switch the GitHub integration from a classic OAuth App (`repo` scope, non-expiring token) to a GitHub App (per-repo install, `contents: read`-only, hourly-refreshed installation tokens). Rationale, scope boundaries, and cost analysis live in that decision doc — this ticket is the implementation scope only.

**Interaction with `docs/plans/2026-07-20-github-task-autocomplete.md`**: that plan registers webhooks per-repo via `POST /repos/{owner}/{repo}/hooks` using the OAuth token, explicitly noting "no GitHub App migration needed" for that mechanism. Once this migration lands, that approach is obsolete: a GitHub App receives webhook events for every installed repo automatically, delivered to a single webhook URL configured at app registration — no per-repo hook creation, no per-repo admin-rights check, no `sync_mode: 'poll'` fallback for repos the token owner isn't admin on. If that plan is implemented before this one, its webhook registration step (`github_repo_sync_state.sync_mode`, per-repo `create_webhook`/`delete_webhook`) should be revisited once this migration ships, since the App-level webhook makes the poll-fallback path unnecessary for any repo the App is installed on. Sequencing recommendation: land this migration first, then build webhook-based auto-complete against the App's single webhook endpoint directly, skipping the per-repo hook/poll-fallback machinery entirely.

## Data model changes

1. **`github_connections` — new columns**:
   - `installation_id: int` (not null after backfill) — the GitHub App installation ID; replaces the implicit "one active OAuth token = one grant" model.
   - `target_login: str`, `target_type: str` (`'Organization'|'User'`) — the account the App is installed on, since installs aren't always to the same account as the connecting user.
   - Existing `encrypted_refresh_token`/`token_expires_at` columns are repurposed: they cache the installation access token and its ~1h expiry, not a user OAuth refresh token/expiry. No new columns needed there — just start writing to them.
2. **New migration**: add the above columns nullable, backfill is not meaningful for existing OAuth connections (they have no `installation_id`) — existing rows should be marked inactive and orgs re-prompted to reconnect via the App install flow (see Rollout below), not silently migrated in place.

## Backend changes

1. **GitHub App registration** (operational, not code): create the App in GitHub org settings — name, homepage URL, callback URL, webhook URL + secret, permissions requested (`Contents: Read`, `Metadata: Read`; add `Pull requests: Read` only if the autocomplete plan above lands and needs PR data), "Where can this be installed" scoped appropriately. Generate the private key (PEM) and store it as a Railway secret (`GITHUB_APP_PRIVATE_KEY`), alongside new settings `github_app_id`, `github_app_client_id`, `github_app_client_secret`, `github_app_slug` in `apps/api/src/config.py`.
2. **JWT + installation-token minting** (`apps/api/src/integrations/github/oauth.py`):
   - New function to mint a short-lived App JWT (RS256, signed with `GITHUB_APP_PRIVATE_KEY`, `iss = github_app_id`, ~9min expiry per GitHub's limit) — needs `PyJWT` (or equivalent) added as a dependency.
   - New function `get_installation_access_token(installation_id)`: `POST /app/installations/{id}/access_tokens` authenticated with the App JWT, returns a token + `expires_at` (~1h). Cache in `github_connections.encrypted_access_token`/`token_expires_at`; check expiry before each use in `router.py`'s existing call sites and refresh transparently rather than the current "assume the token never expires" behavior.
   - `get_authorization_url()` is replaced by the App's install URL (`https://github.com/apps/{github_app_slug}/installations/new`), optionally with `state` and `request_oauth_on_install` if user-level identity (not just installation access) is still wanted for the "connected by" attribution GitHub already tracks separately.
3. **Routes** (`apps/api/src/integrations/github/router.py`):
   - `/connect` — returns the install URL instead of the classic OAuth authorize URL.
   - `/callback` — GitHub redirects here after install with `installation_id` and `setup_action` (`install`/`update`) query params instead of (or alongside) `code`/`state`. Persist `installation_id`, `target_login`, `target_type` on the `GithubConnection` row; mint the first installation access token immediately rather than deferring to first use.
   - `/status`, `/disconnect`, `/repos` — largely unchanged; `/repos` should call `GET /installation/repositories` (the installation-scoped repo list) instead of `/user/repos`, since there's no "authenticated user" in the installation-token flow.
4. **`client.py`** — no changes expected; it already just takes whatever access token it's handed via the `access_token` dataclass field.
5. **Revocation handling** — keep the existing reactive 401→`is_active=False` fallback (`router.py:222-227`); a `POST /api/webhooks/github` receiver for `installation` / `installation_repositories` events (deleted, permissions changed) is a nice-to-have for faster detection but not required for this ticket — flag as follow-up if the autocomplete plan's webhook receiver is built first, since it can absorb these events cheaply.

## Frontend changes

- **`GithubStep.tsx`**: update copy now that the grant is actually read-only — the three bullets ("Read your repositories," "See languages & structure," "Read-only access") stay accurate but can now say so without the caveat that `repo` scope actually includes write; consider surfacing which repos were selected during install (from `GET /installation/repositories`) rather than implying "all repos."
- **`useGithubConnect.ts`** — the redirect result handling (`?github=connected|error`) needs to also accept the install-flow's `setup_action` outcome; confirm exact query param shape against GitHub's docs during implementation.

## Rollout

- Not a live migration of existing tokens (OAuth App tokens can't be converted to installation tokens). Existing `github_connections` rows with no `installation_id` should be treated as needing reconnect: on next `/status` check, if `is_active` but `installation_id IS NULL`, surface a "reconnect required" state and prompt through the new install flow. Given this is early-stage (pivot dated 2026-07-13), the number of existing connections to migrate is expected to be small — confirm actual count before deciding whether a forced reconnect banner is needed or whether direct outreach suffices.

## Out of scope (explicitly deferred)

- Webhook receiver implementation (belongs to the autocomplete plan, sequenced after this one per the Context note above).
- Marketplace listing / public distribution of the App (this is a single-tenant-per-install App for our own product, not a publicly listed integration).
- Org-level admin UI for managing which repos are installed (handled entirely on GitHub's side via the App's settings page for now).
