from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGEBASE_ROOT = REPO_ROOT / "knowledgebase"


class CardEvidence(BaseModel):
    page_start: int | None = None
    page_end: int | None = None
    section_title: str = ""
    quote: str = ""


class KnowledgeCard(BaseModel):
    card_id: str
    source_id: str
    source_title: str
    domain: str
    card_type: str
    topic: str = ""
    clinical_context: str = ""
    trigger_signals: list[str] = Field(default_factory=list)
    related_risk_types: list[str] = Field(default_factory=list)
    used_by_agents: list[str] = Field(default_factory=list)
    allowed_use: list[str] = Field(default_factory=list)
    forbidden_use: list[str] = Field(default_factory=list)
    retrieval_keywords: list[str] = Field(default_factory=list)
    evidence: CardEvidence = Field(default_factory=CardEvidence)
    human_review_required: bool
    confidence: str = "medium"

    @model_validator(mode="before")
    @classmethod
    def _normalize_evidence(cls, data: Any) -> Any:
        if isinstance(data, dict) and "evidence" not in data:
            data = dict(data)
            data["evidence"] = data.get("evidence_location") or {}
        return data


def _iter_card_files() -> list[Path]:
    nested = sorted((KNOWLEDGEBASE_ROOT / "cards").glob("*/*.json"))
    flat_candidates = [
        KNOWLEDGEBASE_ROOT / "cards.json",
        KNOWLEDGEBASE_ROOT / "knowledge_cards.json",
    ]
    return nested + [p for p in flat_candidates if p.exists()]


def _load_json_file(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("cards"), list):
            return [x for x in data["cards"] if isinstance(x, dict)]
        return [data]
    return []


def _is_valid_card(raw: dict[str, Any], path: Path) -> bool:
    if "source_title" not in raw and ("concept_name" in raw or "source_id" in raw):
        raw["source_title"] = str(raw.get("concept_name") or raw.get("source_id"))
    required = [
        "card_id",
        "source_id",
        "source_title",
        "domain",
        "card_type",
        "trigger_signals",
        "related_risk_types",
        "used_by_agents",
        "allowed_use",
        "forbidden_use",
        "human_review_required",
    ]
    missing = [key for key in required if key not in raw]
    has_evidence = "evidence" in raw or "evidence_location" in raw
    if missing or not has_evidence:
        logger.warning("Skipping knowledge card with missing fields in %s: %s", path, missing)
        return False
    if raw.get("human_review_required") is not True:
        logger.warning("Skipping knowledge card without human_review_required=true: %s", raw.get("card_id"))
        return False
    return True


@lru_cache(maxsize=1)
def load_cards() -> list[KnowledgeCard]:
    cards: list[KnowledgeCard] = []
    for path in _iter_card_files():
        for raw in _load_json_file(path):
            if not _is_valid_card(raw, path):
                continue
            try:
                cards.append(KnowledgeCard.model_validate(raw))
            except Exception as exc:
                logger.warning("Skipping invalid knowledge card in %s: %s", path, exc)
    return cards
