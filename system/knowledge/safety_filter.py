from __future__ import annotations

import logging

from .card_loader import KnowledgeCard
from .retrieval_profiles import AgentRetrievalProfile

logger = logging.getLogger(__name__)

AGENT_NAME_ALIASES = {
    "risk_sentinel": "RiskSentinelAgent",
    "clinical_summary": "ClinicalSummaryAgent",
    "bedside_monitor": "BedsideMonitorAgent",
    "intervention_tracker": "InterventionTrackerAgent",
    "patient_memory": "PatientMemoryAgent",
    "ward_coordinator": "WardCoordinatorAgent",
    "compassion_family_communication": "CompassionAgent",
    "icu_orchestrator": "ICUOrchestratorAgent",
}


def validate_retrieved_cards(
    agent_name: str,
    cards: list[KnowledgeCard],
    profile: AgentRetrievalProfile,
) -> list[KnowledgeCard]:
    canonical = AGENT_NAME_ALIASES.get(agent_name, agent_name)
    valid: list[KnowledgeCard] = []
    for card in cards:
        reason = ""
        if card.human_review_required is not True:
            reason = "human_review_required is not true"
        elif canonical not in card.used_by_agents and agent_name not in card.used_by_agents:
            reason = "agent not listed in used_by_agents"
        elif card.domain not in profile.allowed_domains:
            reason = "domain not allowed"
        elif card.card_type not in profile.allowed_card_types:
            reason = "card_type not allowed"
        elif not card.allowed_use:
            reason = "allowed_use is empty"

        if reason:
            logger.info("Filtered knowledge card %s for %s: %s", card.card_id, agent_name, reason)
            continue
        valid.append(card)
    return valid
