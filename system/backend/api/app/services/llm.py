from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings
from llm.concurrency import llm_request_slot
from llm.dashscope_config import chat_completions_url, dashscope_model, load_api_test_env

logger = logging.getLogger(__name__)

load_api_test_env()


def _resolve_model(model: str) -> str:
    m = (model or "").strip()
    if m.startswith("qwen") or m.startswith("gpt-") or m.startswith("deepseek-"):
        return m
    logger.warning("LLM model %s not recognized; using %s", model, dashscope_model())
    return dashscope_model()


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_enabled and self.settings.effective_llm_api_key())

    def ask_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback: dict[str, Any],
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not self.enabled:
            return fallback

        model = _resolve_model(self.settings.llm_model)
        payload = {
            "model": model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        url = chat_completions_url(self.settings.effective_llm_base_url())
        key = self.settings.effective_llm_api_key()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                with llm_request_slot(), httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    resp = client.post(url, json=payload, headers=headers)
                if resp.status_code == 429:
                    logger.warning("LLM rate limited")
                    last_error = RuntimeError("LLM_RATE_LIMITED")
                    continue
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                data = json.loads(content)
                if isinstance(data, dict):
                    return data
                logger.warning("LLM response is not a dict; fallback applied.")
                return fallback
            except Exception as exc:  # pragma: no cover - defensive path
                last_error = exc
                logger.warning("LLM call failed on attempt %s: %s", attempt + 1, exc)
        logger.error("LLM unavailable after retries, fallback applied: %s", last_error)
        return fallback


llm_client = LLMClient()
