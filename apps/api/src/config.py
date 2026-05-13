from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for .env in the api directory, then fall back to repo root
_api_dir = Path(__file__).parent.parent
_env_files = [_api_dir / ".env", _api_dir.parent.parent / ".env"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=[str(p) for p in _env_files], env_file_encoding="utf-8")

    database_url: str
    database_url_sync: str
    redis_url: str = "redis://localhost:6379/0"

    clerk_secret_key: str
    clerk_publishable_key: str
    clerk_webhook_secret: str = ""

    jira_client_id: str = ""
    jira_client_secret: str = ""
    jira_redirect_uri: str = "http://localhost:8000/api/integrations/jira/callback"

    encryption_key: str  # 32-byte hex string

    environment: str = "local"
    frontend_url: str = "http://localhost:5174"
    api_url: str = "http://localhost:8000"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def allowed_origins(self) -> list[str]:
        origins = [
            o.strip() for o in self.frontend_url.split(",") if o.strip()
        ]
        if self.environment == "local":
            local_defaults = [
                "http://localhost:5173",
                "http://localhost:5174",
                "http://localhost:3000",
                "http://127.0.0.1:5174",
            ]
            for o in local_defaults:
                if o not in origins:
                    origins.append(o)
        return origins

    @property
    def feature_flags(self) -> dict[str, bool]:
        """Load feature flags from config/features/{environment}.yaml."""
        flag_file = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "features"
            / f"{self.environment}.yaml"
        )
        if not flag_file.exists():
            available = (
                sorted(p.name for p in flag_file.parent.glob("*.yaml"))
                if flag_file.parent.exists()
                else "directory missing"
            )
            raise RuntimeError(
                f"Feature flag file not found: {flag_file}. "
                f"Environment={self.environment}. Available: {available}"
            )
        with open(flag_file) as f:
            data = yaml.safe_load(f) or {}
        return data.get("features", {})

    def is_feature_enabled(self, flag_name: str) -> bool:
        """Return True if the named flag is enabled in the current environment."""
        return self.feature_flags.get(flag_name, False)

    @field_validator("database_url")
    @classmethod
    def _rewrite_to_asyncpg(cls, v: str) -> str:
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


settings = Settings()
