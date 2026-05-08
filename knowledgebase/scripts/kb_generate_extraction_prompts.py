#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


KB_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = KB_ROOT / "prompts"


PROMPTS = {
    "extract_guideline_cards.md": """# Extract ICU-Agent Guideline Cards

You are extracting structured ICU-Agent knowledge cards from the provided source text.

Rules:
- Only extract information explicitly supported by the provided source text.
- Do not invent recommendations.
- Do not generate medication dose recommendations.
- Do not generate direct treatment orders.
- Every card must include evidence_location.
- Every card must include allowed_use and forbidden_use.
- Every card must set human_review_required=true.
- Keep quotes short, maximum 1-2 sentences.
- If page evidence is uncertain, set confidence=\"low\" and add notes.

Return strict JSON: an array of guideline_card objects matching knowledgebase/schemas/guideline_card.schema.json.
""",
    "extract_computational_concepts.md": """# Extract ICU-Agent Computational Concepts

Extract only scoring systems, severity scores, data concepts, or benchmark concepts explicitly present in the provided source text.

Rules:
- Do not compute scores unless the source provides the formula and inputs.
- Do not make treatment, diagnosis, prognosis, or dosing recommendations.
- Every concept must include source_id, evidence_location, allowed_use, forbidden_use, and human_review_required=true.

Return strict JSON matching knowledgebase/schemas/computational_concept.schema.json.
""",
    "extract_agent_retrieval_keywords.md": """# Extract Agent Retrieval Keywords

Given a validated ICU-Agent card, propose retrieval_keywords for the named agent.

Rules:
- Prefer terms used in the source text and current ICU-Agent risk vocabulary.
- Include synonyms for escalation, summary, and family-communication use only when supported by the card.
- Do not add disease-specific keywords for shock, ARDS, or AKI unless the source directly supports that disease topic.

Return strict JSON with card_id and retrieval_keywords.
""",
}


def main() -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in PROMPTS.items():
        (PROMPTS_DIR / name).write_text(content, encoding="utf-8")
        print(f"Wrote {PROMPTS_DIR / name}")


if __name__ == "__main__":
    main()
