# Extract ICU-Agent Guideline Cards

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
- If page evidence is uncertain, set confidence="low" and add notes.

Return strict JSON: an array of guideline_card objects matching knowledgebase/schemas/guideline_card.schema.json.
