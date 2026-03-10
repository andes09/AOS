from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    database_url_sync: str
    redis_url: str = "redis://localhost:6379/0"

    clerk_secret_key: str
    clerk_publishable_key: str
    clerk_webhook_secret: str

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


settings = Settings()
