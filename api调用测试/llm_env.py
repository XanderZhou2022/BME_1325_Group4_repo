"""阿里云百炼 DashScope（OpenAI 兼容）— 项目唯一 LLM 配置入口。

密钥与模型写在同目录 `.env`：
  DASHSCOPE_API_KEY=sk-...
  DASHSCOPE_MODEL=qwen3-max

后端 `system/backend/api` 启动时会自动加载本文件。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_DIR = Path(__file__).resolve().parent
ENV_FILE = ENV_DIR / ".env"

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3-max"


def load_env(*, override: bool = False) -> bool:
    if ENV_FILE.is_file():
        load_dotenv(ENV_FILE, override=override)
        return True
    return False


# 导入时加载一次，供 api使用.py 等脚本使用
load_env()


def get_api_key() -> str:
    return os.getenv("DASHSCOPE_API_KEY", "").strip()


def get_model() -> str:
    return (os.getenv("DASHSCOPE_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL).strip()


def chat_completions_url(base: str | None = None) -> str:
    b = (base or DASHSCOPE_BASE_URL).rstrip("/")
    if b.endswith("/chat/completions") or b.endswith("/start"):
        return b
    if b.endswith("/v1"):
        return b + "/chat/completions"
    return b + "/v1/chat/completions"
