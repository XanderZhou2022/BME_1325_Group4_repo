from __future__ import annotations

import re
from typing import Any

from .card_loader import KnowledgeCard, load_cards
from .citation_formatter import format_card_citation
from .retrieval_profiles import get_profile, normalize_agent_name
from .safety_filter import AGENT_NAME_ALIASES, validate_retrieved_cards


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in re.split(r"[^a-zA-Z0-9_]+", text.lower()) if len(t) >= 3}


def _score_card(
    card: KnowledgeCard,
    *,
    risk_types: list[str],
    trigger_signals: list[str],
    query: str | None,
    allowed_use: list[str],
) -> tuple[int, list[str]]:
    score = 0
    matched: list[str] = []
    if set(card.related_risk_types) & set(risk_types):
        score += 4
        matched.append("related_risk_types")
    if set(card.trigger_signals) & set(trigger_signals):
        score += 3
        matched.append("trigger_signals")
    if set(card.allowed_use) & set(allowed_use):
        score += 2
        matched.append("allowed_use")
    score += 2
    matched.append("card_type")

    query_tokens = _tokens(query)
    if query_tokens:
        searchable = " ".join(
            [
                card.topic,
                card.source_title,
                card.evidence.quote,
                " ".join(card.trigger_signals),
                " ".join(card.retrieval_keywords),
            ]
        )
        if query_tokens & _tokens(searchable):
            score += 1
            matched.append("query")
    return score, matched


def _card_to_result(card: KnowledgeCard, score: int, matched_fields: list[str]) -> dict[str, Any]:
    citation = format_card_citation(card)
    return {
        "card_id": card.card_id,
        "source_id": card.source_id,
        "source_title": card.source_title,
        "domain": card.domain,
        "card_type": card.card_type,
        "score": score,
        "matched_fields": matched_fields,
        "allowed_use": card.allowed_use,
        "forbidden_use": card.forbidden_use,
        "evidence": citation,
        "human_review_required": True,
    }


def retrieve_cards(
    agent_name: str,
    patient_context: dict[str, Any],
    risk_types: list[str] | None = None,
    trigger_signals: list[str] | None = None,
    query: str | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    normalized = normalize_agent_name(agent_name)
    profile = get_profile(normalized)
    canonical = AGENT_NAME_ALIASES.get(normalized, agent_name)
    limit = top_k or profile.top_k
    risks = risk_types or []
    signals = trigger_signals or []

    candidates = [
        card
        for card in load_cards()
        if card.human_review_required is True
        and (canonical in card.used_by_agents or normalized in card.used_by_agents)
        and card.domain in profile.allowed_domains
        and card.card_type in profile.allowed_card_types
    ]
    valid = validate_retrieved_cards(normalized, candidates, profile)

    scored: list[tuple[int, KnowledgeCard, list[str]]] = []
    for card in valid:
        score, matched = _score_card(card, risk_types=risks, trigger_signals=signals, query=query, allowed_use=profile.allowed_use)
        scored.append((score, card, matched))
    scored.sort(key=lambda item: (item[0], item[1].confidence == "high", item[1].card_id), reverse=True)
    selected = scored[:limit]

    return {
        "agent_name": normalized,
        "query": query or "",
        "patient_id": patient_context.get("patient_id") or patient_context.get("bed_id") or "",
        "risk_types": risks,
        "trigger_signals": signals,
        "retrieved_cards": [_card_to_result(card, score, matched) for score, card, matched in selected],
        "safety_notice": "Knowledge cards provide background only and require human review.",
    }
