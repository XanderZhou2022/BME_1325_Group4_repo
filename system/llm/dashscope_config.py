"""Load DashScope credentials from BME_1325_Group4_repo/api调用测试/.env (single source of truth)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_DASHSCOPE_MODEL = "qwen3-max"


def repo_root() -> Path:
    # system/llm/ -> parents[2] == BME_1325_Group4_repo
    return Path(__file__).resolve().parents[2]


def api_test_env_file() -> Path:
    return repo_root() / "api调用测试" / ".env"


def load_api_test_env(*, override: bool = False) -> bool:
    path = api_test_env_file()
    if path.is_file():
        load_dotenv(path, override=override)
        return True
    return False


def dashscope_api_key() -> str:
    load_api_test_env()
    return os.getenv("DASHSCOPE_API_KEY", "").strip()


def dashscope_model() -> str:
    load_api_test_env()
    return (os.getenv("DASHSCOPE_MODEL", DEFAULT_DASHSCOPE_MODEL) or DEFAULT_DASHSCOPE_MODEL).strip()


def chat_completions_url(base: str | None = None) -> str:
    b = (base or DASHSCOPE_BASE_URL).rstrip("/")
    if b.endswith("/chat/completions") or b.endswith("/start"):
        return b
    if b.endswith("/v1"):
        return b + "/chat/completions"
    return b + "/v1/chat/completions"
