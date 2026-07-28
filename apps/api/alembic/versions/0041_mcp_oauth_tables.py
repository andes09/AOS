"""oauth_clients / oauth_authorization_codes / oauth_tokens — MCP OAuth 2.1 AS

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-28

Omada MCP Server build (docs/plans/2026-07-20-omada-mcp-server.md). Raw-SQL
style matching 0022 (oauth_states), this repo's existing precedent for
short-TTL DB-backed OAuth rows.

Note: `oauth_clients.client_secret_enc` (not `client_secret_hash` as the
original plan named it) — reversibly encrypted, not hashed. See
src/models/oauth_client.py's docstring for why: the MCP SDK's own
ClientAuthenticator compares this value in plaintext via hmac.compare_digest,
so a one-way hash would never match.
"""
from alembic import op


revision = '0041'
down_revision = '0040'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS oauth_clients (
            client_id                      VARCHAR(64) PRIMARY KEY,
            client_secret_enc              TEXT,
            client_name                    VARCHAR(255),
            redirect_uris                  JSONB NOT NULL,
            grant_types                    JSONB NOT NULL,
            response_types                 JSONB NOT NULL DEFAULT '[]',
            token_endpoint_auth_method     VARCHAR(30) NOT NULL DEFAULT 'none',
            scope                           VARCHAR(255),
            client_id_issued_at            INTEGER,
            client_secret_expires_at       INTEGER,
            created_at                     TIMESTAMP NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
            code                            VARCHAR(128) PRIMARY KEY,
            client_id                       VARCHAR(64) NOT NULL REFERENCES oauth_clients(client_id),
            redirect_uri                    TEXT NOT NULL,
            redirect_uri_provided_explicitly BOOLEAN NOT NULL DEFAULT TRUE,
            code_challenge                  VARCHAR(255) NOT NULL,
            scope                            VARCHAR(255),
            clerk_user_id                    VARCHAR(255) NOT NULL,
            clerk_org_id                     VARCHAR(255) NOT NULL,
            developer_id                     UUID NOT NULL REFERENCES developers(id),
            expires_at                       TIMESTAMP NOT NULL,
            used_at                          TIMESTAMP,
            created_at                       TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_authorization_codes_client_id "
        "ON oauth_authorization_codes(client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_authorization_codes_developer_id "
        "ON oauth_authorization_codes(developer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_authorization_codes_expires_at "
        "ON oauth_authorization_codes(expires_at)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id                UUID PRIMARY KEY,
            token_hash        VARCHAR(64) NOT NULL,
            token_type        VARCHAR(10) NOT NULL,
            client_id         VARCHAR(64) NOT NULL REFERENCES oauth_clients(client_id),
            clerk_user_id     VARCHAR(255) NOT NULL,
            clerk_org_id      VARCHAR(255) NOT NULL,
            developer_id      UUID NOT NULL REFERENCES developers(id),
            scope             VARCHAR(255),
            parent_token_id   UUID REFERENCES oauth_tokens(id),
            expires_at        TIMESTAMP NOT NULL,
            revoked_at        TIMESTAMP,
            created_at        TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_oauth_tokens_token_hash "
        "ON oauth_tokens(token_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_tokens_client_id ON oauth_tokens(client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_tokens_developer_id ON oauth_tokens(developer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_tokens_expires_at ON oauth_tokens(expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS oauth_tokens")
    op.execute("DROP INDEX IF EXISTS ix_oauth_authorization_codes_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_oauth_authorization_codes_developer_id")
    op.execute("DROP INDEX IF EXISTS ix_oauth_authorization_codes_client_id")
    op.execute("DROP TABLE IF EXISTS oauth_authorization_codes")
    op.execute("DROP TABLE IF EXISTS oauth_clients")
