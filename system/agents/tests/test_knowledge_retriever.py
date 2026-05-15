from __future__ import annotations

import os
import sys

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "api"))
if API_ROOT not in sys.path:
    sys.path.append(API_ROOT)

from knowledge.card_loader import KnowledgeCard  # noqa: E402
from knowledge import retriever as retriever_module  # noqa: E402
from knowledge.retriever import retrieve_cards  # noqa: E402


def test_retriever_filters_by_agent_profile() -> None:
    result = retrieve_cards("risk_sentinel", {"patient_id": "P-test"}, query="family communication", top_k=20)
    assert result["retrieved_cards"]
    assert all(card["domain"] != "family_communication" for card in result["retrieved_cards"])

    result = retrieve_cards("clinical_summary", {"patient_id": "P-test"}, query="icu design windows", top_k=20)
    assert all(card["domain"] != "icu_design_context" for card in result["retrieved_cards"])


def test_retriever_rejects_non_human_review_cards(monkeypatch) -> None:
    bad = KnowledgeCard.model_validate(
        {
            "card_id": "bad_card",
            "source_id": "src",
            "source_title": "Unsafe source",
            "domain": "clinical_deterioration",
            "card_type": "risk_background",
            "trigger_signals": ["persistent_hypotension"],
            "related_risk_types": ["persistent_shock_risk"],
            "used_by_agents": ["RiskSentinelAgent"],
            "allowed_use": ["risk explanation"],
            "forbidden_use": ["automatic diagnosis"],
            "evidence": {"quote": "unsafe"},
            "human_review_required": True,
        }
    )
    object.__setattr__(bad, "human_review_required", False)
    monkeypatch.setattr(retriever_module, "load_cards", lambda: [bad])
    result = retrieve_cards("risk_sentinel", {"patient_id": "P-test"}, risk_types=["persistent_shock_risk"])
    assert result["retrieved_cards"] == []


def test_retriever_scores_matching_risk_types_higher(monkeypatch) -> None:
    matching = KnowledgeCard.model_validate(
        {
            "card_id": "matching",
            "source_id": "src",
            "source_title": "Matching",
            "domain": "clinical_deterioration",
            "card_type": "risk_background",
            "topic": "Shock risk",
            "trigger_signals": [],
            "related_risk_types": ["persistent_shock_risk"],
            "used_by_agents": ["RiskSentinelAgent"],
            "allowed_use": ["risk explanation"],
            "forbidden_use": ["automatic diagnosis"],
            "evidence": {"quote": "background"},
            "human_review_required": True,
        }
    )
    keyword_only = KnowledgeCard.model_validate(
        {
            "card_id": "keyword_only",
            "source_id": "src",
            "source_title": "Persistent shock keyword",
            "domain": "clinical_deterioration",
            "card_type": "risk_background",
            "topic": "Persistent shock keyword",
            "trigger_signals": [],
            "related_risk_types": [],
            "used_by_agents": ["RiskSentinelAgent"],
            "allowed_use": ["risk explanation"],
            "forbidden_use": ["automatic diagnosis"],
            "evidence": {"quote": "persistent shock"},
            "human_review_required": True,
        }
    )
    monkeypatch.setattr(retriever_module, "load_cards", lambda: [keyword_only, matching])
    result = retrieve_cards("risk_sentinel", {"patient_id": "P-test"}, risk_types=["persistent_shock_risk"], query="persistent shock", top_k=2)
    assert [card["card_id"] for card in result["retrieved_cards"]][0] == "matching"
