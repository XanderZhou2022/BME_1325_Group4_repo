from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ICU_", env_file=".env", extra="ignore")

    pg_dsn: str = "dbname=icu_agent user=zhou host=localhost port=5432"
    api_title: str = "ICU Agent API"
    api_version: str = "0.1.0"
    cors_origins: str = "*"
    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
