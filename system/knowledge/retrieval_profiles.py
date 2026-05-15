from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = REPO_ROOT / "knowledgebase" / "config" / "agent_retrieval_profiles.json"


class AgentRetrievalProfile(BaseModel):
    agent_name: str
    allowed_domains: list[str]
    allowed_card_types: list[str]
    allowed_use: list[str]
    forbidden_use: list[str]
    top_k: int = Field(default=5, ge=1, le=20)
    llm_enabled_default: bool = False


@lru_cache(maxsize=1)
def _load_profiles() -> dict[str, AgentRetrievalProfile]:
    with PROFILE_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    profiles: dict[str, AgentRetrievalProfile] = {}
    for agent_name, data in raw.items():
        profiles[agent_name] = AgentRetrievalProfile(agent_name=agent_name, **data)
    return profiles


def normalize_agent_name(agent_name: str) -> str:
    return agent_name.strip().replace("Agent", "").replace(" ", "_").lower()


def get_profile(agent_name: str) -> AgentRetrievalProfile:
    normalized = normalize_agent_name(agent_name)
    profiles = _load_profiles()
    if normalized not in profiles:
        raise KeyError(f"No retrieval profile configured for agent: {agent_name}")
    return profiles[normalized]
