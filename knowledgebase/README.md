# ICU-Agent Knowledgebase

`knowledgebase/original` is the immutable source directory for original ICU PDF references. Do not delete, rename, or move these PDFs as part of extraction or indexing.

`registry/sources.json` records each PDF source, source domain, population, priority, intended agent use, and safety restrictions. `registry/extraction_status.json` records text extraction status, including empty pages. `registry/card_manifest.json` records generated knowledge cards.

`extracted_text/` contains extracted plain text and page-level JSON for each registered source. Agent code should not read these files directly during normal operation.

`cards/` contains structured ICU-Agent knowledge cards. Cards are organized by domain and are intended to be auditable, individually retrievable units rather than arbitrary PDF chunks.

`indexes/` is the retrieval entry point for downstream agents. Agents should retrieve cards through `agent_retrieval_profiles.json`, `cards.jsonl`, `cards_minimal.jsonl`, and the BM25 keyword index instead of opening original PDFs.

This knowledgebase is only for ICU agent risk explanation, evidence background, clinical summary, escalation reminder wording, family communication drafts, rule checking, and demonstration or benchmark support.

This knowledgebase must not be used for automatic diagnosis, automatic treatment, automatic medication ordering, automatic dose adjustment, or replacing clinicians when communicating prognosis or treatment decisions to families.

All clinical, ethical, and family communication content is human-in-the-loop. Cards set `human_review_required=true`; CompassionAgent cards additionally require clinician approval and are not for direct family delivery.

Current materials cover ICU workflow and operations, rapid response and deterioration recognition, sepsis/septic shock context, ARDS/acute respiratory failure context, AKI/renal failure context, cardiogenic shock/ACS context, stroke/status epilepticus context, DKA/HHS context, severe electrolyte disorder context, trauma/major bleeding context, medication safety, PADIS/sedation/delirium context, adult end-of-life and ethics, ICU design, pediatric critical care context, and APACHE II-style scoring background.

Known source gaps remain: this repository should add acute liver failure and pancreatitis ICU guidance, toxicology/overdose ICU guidance, obstetric critical care guidance, burn critical care guidance, and more detailed ICU infection-specific guidance to better cover future admission scenarios. Disease-specific sepsis/shock, ARDS/respiratory failure, AKI, cardiac, neurocritical, metabolic/electrolyte, and trauma/bleeding cards now provide initial coverage for common ICU risks, but all clinical use remains human-in-the-loop.

Run the current pipeline:

```bash
python knowledgebase/scripts/kb_build_sources_registry.py
python knowledgebase/scripts/kb_extract_text.py
python knowledgebase/scripts/kb_generate_extraction_prompts.py
python knowledgebase/scripts/kb_validate_cards.py
python knowledgebase/scripts/kb_build_indexes.py
python knowledgebase/scripts/kb_search_demo.py --agent RiskSentinelAgent --query "patient has persistent hypotension and worsening trend" --risk_type persistent_shock_risk --top_k 5
```
