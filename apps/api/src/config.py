from pathlib import Path

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

    environment: str = "development"
    frontend_url: str = "http://localhost:5174"
    api_url: str = "http://localhost:8000"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def allowed_origins(self) -> list[str]:
        return [u.strip() for u in self.frontend_url.split(",")]


settings = Settings()
