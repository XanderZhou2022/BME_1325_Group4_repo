# Extract ICU-Agent Computational Concepts

Extract only scoring systems, severity scores, data concepts, or benchmark concepts explicitly present in the provided source text.

Rules:
- Do not compute scores unless the source provides the formula and inputs.
- Do not make treatment, diagnosis, prognosis, or dosing recommendations.
- Every concept must include source_id, evidence_location, allowed_use, forbidden_use, and human_review_required=true.

Return strict JSON matching knowledgebase/schemas/computational_concept.schema.json.
