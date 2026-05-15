from __future__ import annotations

from typing import Any

from .card_loader import KnowledgeCard


def format_card_citation(card: KnowledgeCard) -> dict[str, Any]:
    page = ""
    if card.evidence.page_start and card.evidence.page_end:
        page = str(card.evidence.page_start) if card.evidence.page_start == card.evidence.page_end else f"{card.evidence.page_start}-{card.evidence.page_end}"
    elif card.evidence.page_start:
        page = str(card.evidence.page_start)
    return {
        "card_id": card.card_id,
        "source_title": card.source_title,
        "source_id": card.source_id,
        "page": page,
        "section": card.evidence.section_title,
        "quote": card.evidence.quote,
        "usage": "background_only",
    }
