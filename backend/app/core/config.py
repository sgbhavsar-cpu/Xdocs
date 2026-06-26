"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    api_base_path: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://xdocs:xdocs@localhost:5432/xdocs"
    redis_url: str = "redis://localhost:6379/0"

    # Auth — host-issued JWT validated against the host IdP's JWKS (design §16.1).
    jwt_issuer: str = "https://mock-idp.local"
    jwt_audience: str = "xdocs"
    jwt_algorithms: str = "RS256"
    jwks_url: str = "http://localhost:8080/.well-known/jwks.json"

    cors_allowed_origins: str = "http://localhost:8080"

    # LLM / embeddings (default to offline mock; design §16.2).
    llm_provider: str = "mock"  # mock | openai | azure
    openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    llm_embed_model: str = "text-embedding-3-small"
    llm_chat_model: str = "gpt-4o"

    @property
    def algorithms(self) -> list[str]:
        return [a.strip() for a in self.jwt_algorithms.split(",") if a.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
