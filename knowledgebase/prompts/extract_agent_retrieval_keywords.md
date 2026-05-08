# Extract Agent Retrieval Keywords

Given a validated ICU-Agent card, propose retrieval_keywords for the named agent.

Rules:
- Prefer terms used in the source text and current ICU-Agent risk vocabulary.
- Include synonyms for escalation, summary, and family-communication use only when supported by the card.
- Do not add disease-specific keywords for shock, ARDS, or AKI unless the source directly supports that disease topic.

Return strict JSON with card_id and retrieval_keywords.
