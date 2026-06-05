from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_DASHSCOPE_MODEL = "qwen3-max"
_GENAI_MARKERS = ("genaiapi.shanghaitech", "genaiapi", "/api/v1/start")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_api_test_env() -> None:
    from dotenv import load_dotenv

    api_env = _repo_root() / "api调用测试" / ".env"
    if api_env.is_file():
        load_dotenv(api_env, override=False)


def _is_genai_url(url: str | None) -> bool:
    if not url:
        return False
    return any(m in url for m in _GENAI_MARKERS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ICU_", env_file=".env", extra="ignore")

    pg_dsn: str = "dbname=icu_agent user=zhou host=localhost port=5432"
    api_title: str = "ICU Agent API"
    api_version: str = "0.1.0"
    cors_origins: str = "*"
    host: str = "0.0.0.0"
    port: int = 8000
    group_producer: str = "groupC.icu"

    hospital_redis_host: str | None = None
    hospital_redis_port: int = 6379
    hospital_redis_db: int = 0
    hospital_redis_password: str | None = None

    # LLM：阿里云百炼 DashScope（与 api调用测试/api使用.py 一致）
    llm_enabled: bool = False
    llm_base_url: str = DASHSCOPE_BASE_URL
    llm_api_key: str = ""
    llm_model: str = DEFAULT_DASHSCOPE_MODEL
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_max_concurrency: int = 100
    # Demo / clinical thread pool cap (separate from in-flight LLM HTTP slots).
    demo_parallel_workers: int = 5

    hospital_llm_gateway_url: str | None = None
    hospital_llm_api_key: str | None = None

    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60

    # simi_hospital MDT consultation API (mdt_consultation_api, default port 8001)
    simi_mdt_base_url: str = "http://127.0.0.1:8001"
    simi_mdt_timeout_seconds: float = 300.0
    simi_mdt_workflow_path: str = "/api/v1/integration/icu/workflow"

    # wizicu / groupD inpatient intake bridge (default port 8010)
    inpatient_bridge_base_url: str = "http://127.0.0.1:8010"
    inpatient_bridge_timeout_seconds: float = 15.0

    @property
    def hospital_bus_enabled(self) -> bool:
        return bool(self.hospital_redis_host)

    def simi_mdt_workflow_url(self) -> str:
        base = self.simi_mdt_base_url.rstrip("/")
        path = self.simi_mdt_workflow_path if self.simi_mdt_workflow_path.startswith("/") else f"/{self.simi_mdt_workflow_path}"
        return f"{base}{path}"

    def effective_llm_base_url(self) -> str:
        return self.llm_base_url.rstrip("/")

    def effective_llm_api_key(self) -> str:
        return self.llm_api_key

    @model_validator(mode="after")
    def _fallback_unprefixed_contract_env(self) -> Settings:
        """§4: Redis 仍可读 HOSPITAL_REDIS_*；LLM 仅使用 api调用测试/.env 的 DashScope。"""
        if self.hospital_redis_host is None and os.getenv("HOSPITAL_REDIS_HOST"):
            object.__setattr__(self, "hospital_redis_host", os.getenv("HOSPITAL_REDIS_HOST"))
        if os.getenv("HOSPITAL_REDIS_PORT"):
            object.__setattr__(self, "hospital_redis_port", int(os.getenv("HOSPITAL_REDIS_PORT", "6379")))
        pw = os.getenv("HOSPITAL_REDIS_PASSWORD")
        if pw is not None:
            object.__setattr__(self, "hospital_redis_password", pw)
        return self._apply_dashscope_from_api_test_env()

    def _apply_dashscope_from_api_test_env(self) -> Settings:
        _load_api_test_env()
        dash_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        dash_model = (os.getenv("DASHSCOPE_MODEL") or DEFAULT_DASHSCOPE_MODEL).strip()
        dash_base = (os.getenv("DASHSCOPE_BASE_URL") or DASHSCOPE_BASE_URL).strip()

        object.__setattr__(self, "hospital_llm_gateway_url", None)
        object.__setattr__(self, "hospital_llm_api_key", None)

        if _is_genai_url(self.llm_base_url):
            object.__setattr__(self, "llm_base_url", dash_base)

        legacy_models = {"gpt-4o-mini", "GPT-5.2", "GPT-5", "gpt-4o"}
        if self.llm_model in legacy_models:
            object.__setattr__(self, "llm_model", dash_model)

        if not os.getenv("ICU_LLM_API_KEY") and dash_key:
            object.__setattr__(self, "llm_api_key", dash_key)
        if not os.getenv("ICU_LLM_BASE_URL"):
            object.__setattr__(self, "llm_base_url", dash_base)
        if not os.getenv("ICU_LLM_MODEL"):
            object.__setattr__(self, "llm_model", dash_model)

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
