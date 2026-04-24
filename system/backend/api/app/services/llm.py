from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_enabled and self.settings.llm_api_key)

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

        payload = {
            "model": self.settings.llm_model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    resp = client.post(
                        f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
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
