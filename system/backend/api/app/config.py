from __future__ import annotations

from functools import lru_cache
import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ICU_", env_file=".env", extra="ignore")

    pg_dsn: str = "dbname=icu_agent user=zhou host=localhost port=5432"
    api_title: str = "ICU Agent API"
    api_version: str = "0.1.0"
    cors_origins: str = "*"
    host: str = "0.0.0.0"
    port: int = 8000
    group_producer: str = "groupC.icu"

    # BME1325 contract — Redis (also read unprefixed env per §4.1)
    hospital_redis_host: str | None = None
    hospital_redis_port: int = 6379
    hospital_redis_db: int = 0
    hospital_redis_password: str | None = None

    # LLM: prefer teaching-gateway vars §7; ICU_* overrides for local dev
    llm_enabled: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 12.0
    llm_max_retries: int = 2

    hospital_llm_gateway_url: str | None = None
    hospital_llm_api_key: str | None = None

    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60

    def effective_llm_base_url(self) -> str:
        return (self.hospital_llm_gateway_url or self.llm_base_url).rstrip("/")

    def effective_llm_api_key(self) -> str:
        return self.hospital_llm_api_key or self.llm_api_key

    @property
    def hospital_bus_enabled(self) -> bool:
        return bool(self.hospital_redis_host)

    @model_validator(mode="after")
    def _fallback_unprefixed_contract_env(self) -> Settings:
        """§4 / §7: teaching env vars use HOSPITAL_* without ICU_ prefix."""
        if self.hospital_redis_host is None and os.getenv("HOSPITAL_REDIS_HOST"):
            object.__setattr__(self, "hospital_redis_host", os.getenv("HOSPITAL_REDIS_HOST"))
        if os.getenv("HOSPITAL_REDIS_PORT"):
            object.__setattr__(self, "hospital_redis_port", int(os.getenv("HOSPITAL_REDIS_PORT", "6379")))
        pw = os.getenv("HOSPITAL_REDIS_PASSWORD")
        if pw is not None:
            object.__setattr__(self, "hospital_redis_password", pw)
        if self.hospital_llm_gateway_url is None and os.getenv("HOSPITAL_LLM_GATEWAY_URL"):
            object.__setattr__(self, "hospital_llm_gateway_url", os.getenv("HOSPITAL_LLM_GATEWAY_URL"))
        if self.hospital_llm_api_key is None and os.getenv("HOSPITAL_LLM_API_KEY"):
            object.__setattr__(self, "hospital_llm_api_key", os.getenv("HOSPITAL_LLM_API_KEY"))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
