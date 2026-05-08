#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


KB_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_DIR = KB_ROOT / "original"
REGISTRY_DIR = KB_ROOT / "registry"


SOURCE_RECORDS = {
    "Responding-Requests-for-Potentially-Inappropriate-Treatments-ICU.pdf": {
        "source_id": "potentially_inappropriate_treatments_001",
        "title": "Responding to Requests for Potentially Inappropriate Treatments in Intensive Care Units",
        "domain": "end_of_life_ethics",
        "population": "adult",
        "source_type": "policy_statement",
        "priority": "P2",
        "used_by_agents": ["CompassionAgent", "PatientMemoryAgent", "ClinicalSummaryAgent", "WardCoordinatorAgent"],
        "notes": "Multisociety policy statement for ICU conflicts about treatments clinicians consider potentially inappropriate.",
    },
    "a_focused_update_to_the_clinical_practice.17.pdf": {
        "source_id": "padis_update_2025_001",
        "title": "Focused Update to ICU PADIS Guidelines: Pain, Anxiety, Sedation, Delirium, Immobility, and Sleep",
        "domain": "padis_sedation_delirium",
        "population": "adult",
        "source_type": "clinical_guideline",
        "priority": "P1",
        "used_by_agents": ["BedsideMonitorAgent", "InterventionTrackerAgent", "PatientMemoryAgent", "ClinicalSummaryAgent", "CompassionAgent"],
        "notes": "Adult ICU symptom management context for sedation, delirium, mobility, sleep, and family-facing explanation drafts.",
    },
    "clinical_practice_guideline__safe_medication_use.32.pdf": {
        "source_id": "medication_safety_icu_001",
        "title": "Clinical Practice Guideline: Safe Medication Use in the ICU",
        "domain": "medication_safety",
        "population": "mixed",
        "source_type": "clinical_guideline",
        "priority": "P1",
        "used_by_agents": ["InterventionTrackerAgent", "RiskSentinelAgent", "ClinicalSummaryAgent"],
        "notes": "Medication-use-process and safety-surveillance guidance for critically ill patients; no dosing recommendations are extracted.",
    },
    "criteria_for_critical_care_infants_and_children_.7.pdf": {
        "source_id": "picu_admission_triage_001",
        "title": "Criteria for Critical Care Infants and Children: PICU Admission, Discharge, and Triage",
        "domain": "triage_resource_allocation",
        "population": "pediatric",
        "source_type": "clinical_guideline",
        "priority": "P2",
        "used_by_agents": ["WardCoordinatorAgent", "ClinicalSummaryAgent"],
        "notes": "PICU-specific guidance retained for pediatric context; not included by default in adult ICU retrieval profiles.",
    },
    "icu_admission,_discharge,_and_triage_guidelines__a.15.pdf": {
        "source_id": "adult_icu_admission_triage_001",
        "title": "ICU Admission, Discharge, and Triage Guidelines",
        "domain": "triage_resource_allocation",
        "population": "adult",
        "source_type": "clinical_guideline",
        "priority": "P1",
        "used_by_agents": ["WardCoordinatorAgent", "ClinicalSummaryAgent", "RiskSentinelAgent"],
        "notes": "Adult ICU operational framework for admission, discharge, triage, and institutional policy development.",
    },
    "society_of_critical_care_medicine_2024_guidelines.15.pdf": {
        "source_id": "adult_icu_design_2024_001",
        "title": "Society of Critical Care Medicine 2024 Guidelines on Adult ICU Design",
        "domain": "icu_design_context",
        "population": "adult",
        "source_type": "design_guideline",
        "priority": "P2",
        "used_by_agents": ["ClinicalSummaryAgent"],
        "notes": "ICU design and environment background; excluded from RiskSentinel default retrieval.",
    },
    "society_of_critical_care_medicine_clinical.32.pdf": {
        "source_id": "adult_eol_icu_2025_001",
        "title": "SCCM Clinical Practice Guidelines on Adult End-of-Life Care in the ICU",
        "domain": "end_of_life_ethics",
        "population": "adult",
        "source_type": "clinical_guideline",
        "priority": "P1",
        "used_by_agents": ["CompassionAgent", "PatientMemoryAgent", "ClinicalSummaryAgent", "WardCoordinatorAgent"],
        "notes": "Adult ICU end-of-life decision-making, symptom, conflict, and communication context with clinician review required.",
    },
    "society_of_critical_care_medicine_guidelines_for.20.pdf": {
        "source_id": "crisis_resource_allocation_2026_001",
        "title": "SCCM Guidelines for Allocation of Critical Care Resources During Crisis-Level Shortages",
        "domain": "triage_resource_allocation",
        "population": "adult",
        "source_type": "clinical_guideline",
        "priority": "P1",
        "used_by_agents": ["WardCoordinatorAgent", "ClinicalSummaryAgent", "RiskSentinelAgent"],
        "notes": "Adult crisis-level triage and scarce-resource allocation context; supports review prompts, not automated allocation decisions.",
    },
    "society_of_critical_care_medicine_guidelines_on.14.pdf": {
        "source_id": "clinical_deterioration_rapid_response_2024_001",
        "title": "SCCM Guidelines on Recognizing and Responding to Clinical Deterioration Outside the ICU",
        "domain": "clinical_deterioration",
        "population": "mixed",
        "source_type": "clinical_guideline",
        "priority": "P1",
        "used_by_agents": ["BedsideMonitorAgent", "RiskSentinelAgent", "InterventionTrackerAgent", "ClinicalSummaryAgent", "WardCoordinatorAgent"],
        "notes": "General deterioration recognition and rapid response guidance. Supports shock/respiratory/AKI escalation context but is not disease-specific.",
    },
    "危重病人评分系统 - 急救医学 - MSD诊疗手册专业版.pdf": {
        "source_id": "msd_critical_illness_scoring_001",
        "title": "危重病人评分系统 - MSD诊疗手册专业版",
        "domain": "computational_concepts",
        "population": "general",
        "source_type": "scoring_system",
        "priority": "P1",
        "used_by_agents": ["RiskSentinelAgent", "ClinicalSummaryAgent", "WardCoordinatorAgent"],
        "notes": "Chinese manual reference for critical illness scoring systems, including APACHE II scoring context.",
    },
}


def main() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    missing = []
    for filename, metadata in SOURCE_RECORDS.items():
        path = ORIGINAL_DIR / filename
        if not path.exists():
            missing.append(filename)
            continue
        item = {
            **metadata,
            "filename": filename,
            "relative_path": str(path.relative_to(KB_ROOT)),
            "use_now": True,
            "human_review_required": True,
            "registry_last_updated": date.today().isoformat(),
        }
        records.append(item)

    extra_pdfs = sorted(p.name for p in ORIGINAL_DIR.glob("*.pdf") if p.name not in SOURCE_RECORDS)
    output = {
        "schema_version": "icu_agent.sources.v1",
        "generated_at": date.today().isoformat(),
        "sources": sorted(records, key=lambda x: x["source_id"]),
        "warnings": {
            "missing_expected_pdfs": missing,
            "unregistered_pdfs": extra_pdfs,
            "known_core_guideline_gaps": [
                "sepsis/shock disease-specific guideline",
                "ARDS/respiratory failure disease-specific guideline",
                "AKI disease-specific guideline",
            ],
        },
    }
    (REGISTRY_DIR / "sources.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {REGISTRY_DIR / 'sources.json'} with {len(records)} sources.")


if __name__ == "__main__":
    main()
