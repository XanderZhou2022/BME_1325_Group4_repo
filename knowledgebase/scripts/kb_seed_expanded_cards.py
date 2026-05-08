#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


KB_ROOT = Path(__file__).resolve().parents[1]
CARDS_ROOT = KB_ROOT / "cards"
TEXT_ROOT = KB_ROOT / "extracted_text"
SOURCES_PATH = KB_ROOT / "registry" / "sources.json"
TODAY = date.today().isoformat()

FORBIDDEN = [
    "automatic diagnosis",
    "treatment order",
    "drug dose recommendation",
    "automatic treatment decision",
]

SOURCE_TITLES: dict[str, str] = {}
SOURCE_POPULATIONS: dict[str, str] = {}


def load_source_maps() -> None:
    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    for source in data["sources"]:
        SOURCE_TITLES[source["source_id"]] = source["title"]
        SOURCE_POPULATIONS[source["source_id"]] = source["population"]


def pages_for(source_id: str) -> list[dict[str, Any]]:
    return json.loads((TEXT_ROOT / f"{source_id}.pages.json").read_text(encoding="utf-8"))["pages"]


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def evidence_for(source_id: str, terms: list[str], fallback_section: str) -> dict[str, Any]:
    pages = pages_for(source_id)
    lowered_terms = [term.lower() for term in terms]
    best_page = pages[0]
    best_line = ""
    best_score = -1
    for page in pages:
        lines = [normalize_line(line) for line in page["text"].splitlines()]
        for line in lines:
            if len(line) < 20:
                continue
            low = line.lower()
            score = sum(1 for term in lowered_terms if term in low)
            if score > best_score:
                best_page = page
                best_line = line
                best_score = score
            if score == len(lowered_terms):
                quote = line[:220]
                return {
                    "page_start": int(page["page"]),
                    "page_end": int(page["page"]),
                    "section_title": fallback_section,
                    "quote": quote,
                }
    if not best_line:
        best_line = normalize_line(best_page["text"].splitlines()[0])[:220]
    return {
        "page_start": int(best_page["page"]),
        "page_end": int(best_page["page"]),
        "section_title": fallback_section,
        "quote": best_line[:220],
    }


def base_card(
    *,
    card_id: str,
    source_id: str,
    domain: str,
    subdomain: str,
    card_type: str,
    topic: str,
    clinical_context: str,
    key_points: list[str],
    trigger_signals: list[str],
    used_by_agents: list[str],
    retrieval_keywords: list[str],
    evidence_terms: list[str],
    section_title: str,
    related_risk_types: list[str] | None = None,
    allowed_use: list[str] | None = None,
    forbidden_use: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    card = {
        "card_id": card_id,
        "source_id": source_id,
        "source_title": SOURCE_TITLES[source_id],
        "domain": domain,
        "subdomain": subdomain,
        "population": SOURCE_POPULATIONS[source_id],
        "card_type": card_type,
        "topic": topic,
        "clinical_context": clinical_context,
        "key_points": key_points,
        "trigger_signals": trigger_signals,
        "related_risk_types": related_risk_types or [],
        "used_by_agents": used_by_agents,
        "allowed_use": allowed_use or ["risk explanation", "clinical summary", "human review escalation wording"],
        "forbidden_use": forbidden_use or FORBIDDEN,
        "retrieval_keywords": retrieval_keywords,
        "evidence_location": evidence_for(source_id, evidence_terms, section_title),
        "confidence": "high",
        "human_review_required": True,
        "last_updated": TODAY,
    }
    if extra:
        card.update(extra)
    return card


def write_cards(cards: list[dict[str, Any]]) -> None:
    for card in cards:
        folder = CARDS_ROOT / card["domain"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{card['card_id']}.json").write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clinical_deterioration_cards() -> list[dict[str, Any]]:
    specs = [
        ("timely_vitals", "Timely vital sign acquisition", ["vital sign", "timely"], ["abnormal vital signs", "late measurement"]),
        ("accurate_vitals", "Accurate vital sign acquisition", ["vital sign", "accurate"], ["measurement concern", "inconsistent vital signs"]),
        ("traditional_vitals", "Traditional vital sign elements", ["temperature", "heart rate"], ["temperature", "heart rate", "respiratory rate", "blood pressure", "oxygen saturation"]),
        ("oxygen_saturation", "Oxygen saturation as deterioration signal", ["oxygen", "saturation"], ["worsening oxygenation", "low oxygen saturation"]),
        ("respiratory_rate", "Respiratory rate as deterioration signal", ["respiratory rate"], ["tachypnea", "respiratory rate change"]),
        ("blood_pressure", "Blood pressure as deterioration signal", ["blood pressure"], ["persistent hypotension", "blood pressure change"]),
        ("mental_status", "Mental status in deterioration recognition", ["mental status"], ["new confusion", "decreased responsiveness"]),
        ("focused_education", "Focused education for deterioration signs", ["focused education", "deterioration"], ["staff uncertainty", "new deterioration"]),
        ("bedside_empowerment", "Bedside clinicians empowered to alert", ["empowered", "alert"], ["nurse concern", "staff concern"]),
        ("family_concerns", "Patient and family concerns in escalation", ["patient/family", "concerns"], ["family concern", "care partner concern"]),
        ("additional_opinions", "Obtaining additional opinions and help", ["additional opinions", "help"], ["request for additional help", "concern not resolved"]),
        ("rrt_deployment", "Hospital-wide rapid response team deployment", ["rapid response team", "deployment"], ["RRT activation", "medical emergency team"]),
        ("explicit_activation", "Explicit rapid response activation criteria", ["explicit", "activation criteria"], ["criteria met", "urgent escalation"]),
        ("responder_skillset", "Rapid response responder skill set", ["skill set", "responders"], ["complex deterioration", "RRT response"]),
        ("goals_of_care_rrt", "Goals of care during deterioration response", ["goals of care"], ["deterioration with goals question", "resuscitation status question"]),
        ("qi_process", "Quality improvement in rapid response systems", ["quality improvement", "rapid response"], ["RRT process review", "activation delay"]),
        ("continuous_monitoring_uncertainty", "Continuous vital sign monitoring uncertainty", ["continuous vital sign monitoring", "no recommendation"], ["unselected monitoring question"]),
        ("early_identification", "Early identification and prompt response", ["early identification", "prompt response"], ["early deterioration", "new decline"]),
        ("clinical_deterioration_definition", "Clinical deterioration as reversible risk context", ["Clinical deterioration", "morbidity"], ["deterioration", "reversible harm"]),
        ("documentation_goals", "Documentation of goals during response", ["documentation", "goals of care"], ["goals documented", "communication gap"]),
        ("activation_delays", "Rapid response activation delays as QI signal", ["activation delays"], ["delayed escalation", "delayed RRT"]),
        ("patient_advocacy", "Family activated response and patient advocacy", ["patient advocacy"], ["family advocacy", "care partner alert"]),
    ]
    cards = []
    for idx, (slug, topic, terms, triggers) in enumerate(specs, 1):
        cards.append(
            base_card(
                card_id=f"clinical_deterioration_{slug}_{idx:03d}",
                source_id="clinical_deterioration_rapid_response_2024_001",
                domain="clinical_deterioration",
                subdomain="recognition_response",
                card_type="escalation_principle" if "rrt" in slug or "activation" in slug else "risk_background",
                topic=topic,
                clinical_context="Use for human-reviewed recognition, explanation, and escalation of possible clinical deterioration.",
                key_points=[
                    f"The source explicitly discusses {topic.lower()} in the context of recognizing or responding to deterioration.",
                    "Use this as escalation or summary context only; it does not diagnose shock, respiratory failure, or AKI.",
                ],
                trigger_signals=triggers,
                related_risk_types=["persistent_shock_risk", "respiratory_failure_risk", "aki_risk"],
                used_by_agents=["BedsideMonitorAgent", "RiskSentinelAgent", "ClinicalSummaryAgent", "WardCoordinatorAgent"],
                retrieval_keywords=terms + triggers + ["clinical deterioration", "rapid response"],
                evidence_terms=terms,
                section_title="Recognizing and responding to clinical deterioration",
                extra={
                    "direct_risk_source": False,
                    "risk_use_note": "General deterioration and escalation context; not a disease-specific risk guideline.",
                    "time_window_hint": "Apply to sustained, repeated, or worsening findings in the agent's configured analysis window.",
                    "allowed_summary_language": ["A concerning deterioration signal is present and should be reviewed by the clinical team."],
                },
            )
        )
    return cards


def medication_cards() -> list[dict[str, Any]]:
    specs = [
        ("safe_medication_use", "Safe medication use practices", ["safe medication use"], ["medication review"]),
        ("medication_use_process", "Medication-use process review", ["medication use process"], ["prescribing", "dispensing", "administration"]),
        ("patient_safety_surveillance", "Patient safety surveillance system", ["patient safety surveillance"], ["safety surveillance"]),
        ("medication_errors", "Medication error detection context", ["medication errors"], ["medication error"]),
        ("adverse_drug_events", "Adverse drug event detection context", ["adverse drug events"], ["ADE", "adverse drug event"]),
        ("active_surveillance", "Active medication surveillance", ["active surveillance"], ["active surveillance"]),
        ("reporting_identification", "Reporting and identification of medication events", ["reporting", "identification"], ["event report"]),
        ("evaluation_monitoring", "Evaluation and monitoring after medication events", ["evaluation", "monitoring"], ["monitoring"]),
        ("high_risk_medications", "High-risk medication context", ["high-risk medications"], ["high-risk medication"]),
        ("renal_function", "Renal function in medication safety", ["renal function"], ["renal dysfunction", "AKI risk"]),
        ("hepatic_failure", "Hepatic failure in medication safety", ["hepatic failure"], ["hepatic dysfunction"]),
        ("cdss", "Clinical decision support and medication safety", ["CDSS"], ["decision support alert"]),
        ("standardized_concentrations", "Standardized IV concentration practices", ["standardized IV medication concentration"], ["IV medication"]),
        ("double_check", "Independent double checks for high-alert processes", ["double checking"], ["double check"]),
        ("bar_code", "Barcode medication administration context", ["BCMA"], ["barcode administration"]),
        ("smart_pump", "Smart pump or guardrail context", ["guardrails"], ["infusion guardrail"]),
        ("direct_observation", "Direct observation for medication surveillance", ["Direct Observation"], ["observed administration"]),
        ("chart_review", "Chart review for ADE surveillance", ["chart review"], ["manual chart review"]),
        ("trigger_system", "Trigger systems for ADE surveillance", ["trigger system"], ["ADE trigger"]),
        ("pharmacist_surveillance", "Pharmacist surveillance context", ["pharmacist surveillance"], ["pharmacist review"]),
        ("family_patient_reports", "Patient and family reports in medication safety", ["family", "patient safety"], ["family report"]),
        ("handoffs", "Medication handoff safety context", ["handoffs"], ["handoff"]),
        ("benchmarking", "Benchmarking medication safety surveillance", ["benchmarking"], ["benchmarking"]),
        ("safety_culture", "ICU medication safety culture", ["safety culture"], ["safety culture"]),
        ("near_misses", "Learning from near misses", ["near misses"], ["near miss"]),
        ("quality_improvement", "Medication safety quality improvement", ["quality improvement"], ["QI"]),
        ("resource_intensive", "Resource needs for medication surveillance", ["resource intensive"], ["surveillance burden"]),
        ("icu_specific_ade", "ICU-specific ADE surveillance", ["ICU-specific ADE surveillance"], ["ICU ADE"]),
    ]
    cards = []
    for idx, (slug, topic, terms, triggers) in enumerate(specs, 1):
        cards.append(
            base_card(
                card_id=f"medication_safety_{slug}_{idx:03d}",
                source_id="medication_safety_icu_001",
                domain="medication_safety",
                subdomain="medication_use_safety",
                card_type="medication_safety_context",
                topic=topic,
                clinical_context="Use for clinician or pharmacist review prompts around medication-related ICU events.",
                key_points=[
                    f"The source explicitly discusses {topic.lower()} as part of ICU medication safety.",
                    "This card supports review, monitoring, and summary language only and must not produce doses or medication orders.",
                ],
                trigger_signals=triggers,
                related_risk_types=["persistent_shock_risk", "respiratory_failure_risk", "aki_risk"] if slug in {"safe_medication_use", "adverse_drug_events", "renal_function"} else [],
                used_by_agents=["InterventionTrackerAgent", "RiskSentinelAgent", "ClinicalSummaryAgent"],
                retrieval_keywords=terms + triggers + ["medication safety", "ADE", "medication error"],
                evidence_terms=terms,
                section_title="Safe medication use in the ICU",
                extra={
                    "direct_risk_source": False,
                    "intervention_types": ["medication administration", "infusion", "medication review"],
                    "observation_targets": ["medication errors", "adverse drug events", "unexpected clinical change"],
                    "response_language": ["Flag medication safety context for clinician or pharmacist review without dose advice."],
                },
            )
        )
    return cards


def padis_cards() -> list[dict[str, Any]]:
    specs = [
        ("anxiety_domain", "Anxiety as an adult ICU symptom domain", ["anxiety"], ["anxiety"]),
        ("benzodiazepine_uncertainty", "No recommendation for benzodiazepines to treat anxiety", ["benzodiazepines", "anxiety"], ["benzodiazepine question"]),
        ("sedation_domain", "Agitation and sedation domain", ["agitation/sedation"], ["sedation"]),
        ("dexmedetomidine_propofol", "Dexmedetomidine versus propofol context", ["dexmedetomidine", "propofol"], ["mechanical ventilation", "sedation"]),
        ("light_sedation", "Light sedation priority context", ["light sedation"], ["light sedation"]),
        ("delirium_reduction", "Delirium reduction priority context", ["reduction in delirium"], ["delirium risk"]),
        ("clinical_judgment", "Clinical judgment in sedation decisions", ["clinical judgment"], ["sedation complexity"]),
        ("bradycardia_hypotension", "Bradycardia and hypotension considerations", ["bradycardia", "hypotension"], ["bradycardia", "hypotension"]),
        ("antipsychotic_uncertainty", "No recommendation for antipsychotics for delirium", ["antipsychotics", "delirium"], ["delirium treatment question"]),
        ("delirium_free_days", "Delirium-free days evidence context", ["delirium-free days"], ["delirium outcome"]),
        ("mobilization", "Enhanced mobilization and rehabilitation", ["enhanced mobilization"], ["immobility", "rehabilitation"]),
        ("usual_mobilization", "Enhanced versus usual mobilization context", ["usual care mobilization"], ["usual mobilization"]),
        ("mobility_adverse_event", "Mobility adverse event context", ["adverse event"], ["arrhythmia", "mobility safety"]),
        ("melatonin", "Melatonin sleep and delirium context", ["melatonin"], ["sleep disruption"]),
        ("sleep_quality", "Sleep quality in ICU symptom management", ["sleep quality"], ["poor sleep"]),
        ("circadian_disruption", "Circadian disruption context", ["circadian"], ["sleep disruption"]),
        ("post_icu_anxiety", "Post-ICU anxiety/PTSD outcome context", ["post-ICU anxiety"], ["post ICU anxiety"]),
        ("icu_survivor_input", "ICU survivor input in guideline panel", ["ICU survivors"], ["survivor perspective"]),
        ("patient_important_outcomes", "Patient-important outcomes in PADIS", ["PATIENT-IMPORTANT OUTCOMES"], ["patient outcome"]),
        ("nonpharm_anxiety", "Nonpharmacologic anxiety research context", ["nonpharmacologic", "anxiety"], ["anxiety support"]),
        ("deep_sedation", "Deep sedation special context", ["deep sedation"], ["deep sedation"]),
        ("mechanical_ventilation", "Mechanical ventilation and sedation context", ["mechanically ventilated"], ["ventilator", "sedation"]),
    ]
    cards = []
    for idx, (slug, topic, terms, triggers) in enumerate(specs, 1):
        compassion = slug in {"anxiety_domain", "melatonin", "sleep_quality", "mechanical_ventilation", "antipsychotic_uncertainty"}
        used = ["BedsideMonitorAgent", "InterventionTrackerAgent", "PatientMemoryAgent", "ClinicalSummaryAgent"]
        if compassion:
            used.append("CompassionAgent")
        extra = {
            "professional_summary_template": f"{topic}: summarize as ICU symptom-management context requiring clinician interpretation.",
            "allowed_terms": terms + ["ICU context"],
            "avoid_terms": ["dose", "automatic medication order", "definitive treatment"],
        }
        if compassion:
            extra.update(
                {
                    "requires_clinician_approval": True,
                    "not_for_direct_family_delivery": True,
                    "family_friendly_language": ["The ICU team can explain how symptoms, sedation, sleep, or confusion affect communication and comfort."],
                    "professional_preview_language": ["Review against current clinical status before family-facing use."],
                    "phrases_to_avoid": ["This guarantees recovery.", "The agent recommends this medicine."],
                }
            )
        cards.append(
            base_card(
                card_id=f"padis_{slug}_{idx:03d}",
                source_id="padis_update_2025_001",
                domain="padis_sedation_delirium",
                subdomain="padis_symptom_management",
                card_type="guideline_context",
                topic=topic,
                clinical_context="Use for adult ICU symptom-management summaries and human-reviewed intervention tracking.",
                key_points=[
                    f"The source explicitly discusses {topic.lower()} in adult ICU PADIS symptom-management context.",
                    "This card must not be used to select, order, or dose a sedative, antipsychotic, or sleep medication.",
                ],
                trigger_signals=triggers,
                related_risk_types=["respiratory_failure_risk"] if "ventilat" in " ".join(terms + triggers).lower() else [],
                used_by_agents=used,
                retrieval_keywords=terms + triggers + ["PADIS", "ICU", "delirium", "sedation"],
                evidence_terms=terms,
                section_title="PADIS focused update",
                extra=extra,
            )
        )
    return cards


def triage_cards() -> list[dict[str, Any]]:
    specs = [
        ("admission_prioritization", "ICU admission prioritization models", "adult_icu_admission_triage_001", ["prioritization model"], ["ICU admission"]),
        ("diagnosis_model", "Diagnosis-based admission model", "adult_icu_admission_triage_001", ["diagnosis model"], ["diagnosis context"]),
        ("objective_parameters", "Objective parameters for ICU admission", "adult_icu_admission_triage_001", ["objective parameters"], ["objective criteria"]),
        ("priority_framework", "ICU admission priority framework", "adult_icu_admission_triage_001", ["ICU Admission Prioritization Framework"], ["priority level"]),
        ("imminent_decline", "High risk for imminent decline", "adult_icu_admission_triage_001", ["high risk for imminent decline"], ["imminent decline"]),
        ("resource_allocation", "Resource allocation for intensive monitoring", "adult_icu_admission_triage_001", ["resource allocation"], ["resource need"]),
        ("nursing_resources", "Nursing resources and ratios", "adult_icu_admission_triage_001", ["nursing resources"], ["nursing workload"]),
        ("triage_decision_factors", "Factors that affect triage decisions", "adult_icu_admission_triage_001", ["Factors That Affect Triage Decisions"], ["triage decision"]),
        ("triage_elements", "Triage elements and documentation", "adult_icu_admission_triage_001", ["patient assessment", "documentation"], ["triage documentation"]),
        ("fair_just_process", "Explicit fair and just triage process", "adult_icu_admission_triage_001", ["fair", "just"], ["fairness"]),
        ("bed_shortage", "ICU bed shortage triage context", "adult_icu_admission_triage_001", ["ICU bed shortages"], ["bed shortage"]),
        ("discharge_lower_care", "Discharge to lower level of care context", "adult_icu_admission_triage_001", ["lower level of care"], ["lower level care"]),
        ("night_discharge", "Evening or night ICU discharge risk context", "adult_icu_admission_triage_001", ["evening or night"], ["night discharge"]),
        ("admission_delays", "ICU admission delay tracking", "adult_icu_admission_triage_001", ["Admission delays"], ["admission delay"]),
        ("denied_admissions", "Denied ICU admission metrics", "adult_icu_admission_triage_001", ["Denied admissions"], ["denied admission"]),
        ("rrs_referral", "Rapid response referral admissions", "adult_icu_admission_triage_001", ["Admissions via RRS referral"], ["RRS referral"]),
        ("crisis_shortages", "Crisis-level shortages definition", "crisis_resource_allocation_2026_001", ["Crisis-level shortages"], ["crisis shortage"]),
        ("ventilator_shortage", "Ventilator shortage as critical resource context", "crisis_resource_allocation_2026_001", ["ventilators"], ["ventilator shortage"]),
        ("personnel_shortage", "Personnel shortage as critical resource context", "crisis_resource_allocation_2026_001", ["personnel"], ["staff shortage"]),
        ("facilities_shortage", "Facilities shortage and ICU beds", "crisis_resource_allocation_2026_001", ["facilities", "ICU beds"], ["ICU bed shortage"]),
        ("objective_triage_tool", "Objective triage tool evidence context", "crisis_resource_allocation_2026_001", ["objective triage tool"], ["triage tool"]),
        ("dynamic_adjustment", "Dynamic adjustment during shortages", "crisis_resource_allocation_2026_001", ["adjusting dynamically"], ["dynamic triage"]),
        ("transfer_facility", "Transfer to another facility during shortage", "crisis_resource_allocation_2026_001", ["another facility"], ["transfer"]),
        ("palliative_services", "Palliative care services during limited resources", "crisis_resource_allocation_2026_001", ["palliative care services"], ["palliative care"]),
        ("research_gaps", "Triage research gaps", "crisis_resource_allocation_2026_001", ["lack of evidence"], ["evidence gap"]),
        ("essential_services", "Access to essential critical care services", "crisis_resource_allocation_2026_001", ["essential critical care services"], ["essential care"]),
        ("fairness_variation", "Fairness and variation in triage practice", "crisis_resource_allocation_2026_001", ["fairness", "variation"], ["fairness"]),
        ("surge_capacity", "Surge capacity resource context", "crisis_resource_allocation_2026_001", ["surge capacity"], ["surge"]),
    ]
    cards = []
    for idx, (slug, topic, source_id, terms, triggers) in enumerate(specs, 1):
        cards.append(
            base_card(
                card_id=f"triage_resource_allocation_{slug}_{idx:03d}",
                source_id=source_id,
                domain="triage_resource_allocation",
                subdomain="icu_triage_operations",
                card_type="icu_operations_context" if source_id == "adult_icu_admission_triage_001" else "ethical_policy",
                topic=topic,
                clinical_context="Use for ward coordination, resource-context summaries, and human review of triage-related signals.",
                key_points=[
                    f"The source explicitly discusses {topic.lower()} in ICU admission, discharge, triage, or crisis allocation context.",
                    "This card supports prioritization reminders and documentation only; it must not decide admission, discharge, transfer, or resource denial.",
                ],
                trigger_signals=triggers,
                related_risk_types=["persistent_shock_risk", "respiratory_failure_risk", "aki_risk"],
                used_by_agents=["WardCoordinatorAgent", "ClinicalSummaryAgent", "RiskSentinelAgent"],
                retrieval_keywords=terms + triggers + ["ICU triage", "resource allocation", "bed priority"],
                evidence_terms=terms,
                section_title="ICU triage and resource allocation",
                extra={
                    "priority_factors": ["clinical urgency", "need for ICU-level monitoring", "available resources", "patient preferences", "potential to benefit"],
                    "resource_context": "Use for human-reviewed ICU bed, staffing, transfer, and resource limitation context.",
                    "fairness_or_ethics_note": "Use explicit and fair processes; do not automate allocation decisions.",
                },
            )
        )
    return cards


def family_ethics_cards() -> list[dict[str, Any]]:
    specs = [
        ("eol_decision_making", "End-of-life decision-making support", "adult_eol_icu_2025_001", "end_of_life_ethics", "ethical_policy", ["decision-making"], ["goals of care"]),
        ("eol_conflict_mitigation", "Conflict mitigation in adult ICU EOL care", "adult_eol_icu_2025_001", "end_of_life_ethics", "ethical_policy", ["mitigate conflict"], ["conflict"]),
        ("eol_suffering", "Addressing suffering in EOL context", "adult_eol_icu_2025_001", "end_of_life_ethics", "ethical_policy", ["suffering"], ["suffering"]),
        ("eol_capacity", "Capacity for adult EOL care in ICU", "adult_eol_icu_2025_001", "end_of_life_ethics", "ethical_policy", ["capacity"], ["EOL capacity"]),
        ("eol_multidisciplinary", "Multidisciplinary approach to EOL care", "adult_eol_icu_2025_001", "end_of_life_ethics", "ethical_policy", ["multidisciplinary"], ["team meeting"]),
        ("eol_organ_donation_scope", "Organ donation beyond EOL guideline scope", "adult_eol_icu_2025_001", "end_of_life_ethics", "ethical_policy", ["organ donation"], ["organ donation question"]),
        ("potentially_inappropriate_term", "Use potentially inappropriate instead of futile", "potentially_inappropriate_treatments_001", "end_of_life_ethics", "ethical_policy", ["potentially inappropriate"], ["treatment conflict"]),
        ("futile_restricted", "Restricting the term futile", "potentially_inappropriate_treatments_001", "end_of_life_ethics", "ethical_policy", ["futile"], ["futility language"]),
        ("conflict_resolution", "Fair conflict-resolution process", "potentially_inappropriate_treatments_001", "end_of_life_ethics", "ethical_policy", ["conflict resolution"], ["unresolved conflict"]),
        ("hospital_review", "Hospital review in treatment conflict", "potentially_inappropriate_treatments_001", "end_of_life_ethics", "ethical_policy", ["hospital review"], ["ethics review"]),
        ("external_review", "External review opportunity", "potentially_inappropriate_treatments_001", "end_of_life_ethics", "ethical_policy", ["external review"], ["external review"]),
        ("willing_provider", "Attempt to find willing provider", "potentially_inappropriate_treatments_001", "end_of_life_ethics", "ethical_policy", ["willing provider"], ["transfer request"]),
        ("proactive_communication", "Proactive communication to prevent conflicts", "potentially_inappropriate_treatments_001", "family_communication", "communication_principle", ["proactive communication"], ["family meeting"]),
        ("early_consultants", "Early involvement of expert consultants", "potentially_inappropriate_treatments_001", "family_communication", "communication_principle", ["expert consultants"], ["ethics consult"]),
        ("shared_decision_making", "Shared decision-making context", "potentially_inappropriate_treatments_001", "family_communication", "communication_principle", ["shared decision making"], ["shared decision"]),
        ("clinician_explain_advocate", "Clinician explanation and advocacy for appropriate plan", "potentially_inappropriate_treatments_001", "family_communication", "communication_principle", ["explain and advocate"], ["plan explanation"]),
        ("family_concerns_heard", "Family concerns heard and addressed", "clinical_deterioration_rapid_response_2024_001", "family_communication", "communication_principle", ["heard and addressed"], ["family concern"]),
        ("family_additional_help", "Family concern can inform additional help", "clinical_deterioration_rapid_response_2024_001", "family_communication", "communication_principle", ["additional opinions", "help"], ["additional help"]),
        ("sedation_explanation", "Sedation family explanation", "padis_update_2025_001", "family_communication", "communication_principle", ["agitation/sedation"], ["sedation explanation"]),
        ("delirium_explanation", "Delirium family explanation", "padis_update_2025_001", "family_communication", "communication_principle", ["delirium"], ["delirium explanation"]),
        ("anxiety_explanation", "Anxiety family explanation", "padis_update_2025_001", "family_communication", "communication_principle", ["anxiety"], ["anxiety explanation"]),
        ("sleep_explanation", "Sleep disruption family explanation", "padis_update_2025_001", "family_communication", "communication_principle", ["sleep disruption"], ["sleep explanation"]),
        ("immobility_explanation", "Immobility family explanation", "padis_update_2025_001", "family_communication", "communication_principle", ["immobility"], ["immobility explanation"]),
        ("goals_of_care_family", "Goals of care family-facing draft context", "adult_eol_icu_2025_001", "family_communication", "communication_principle", ["goals"], ["family meeting"]),
    ]
    cards = []
    for idx, (slug, topic, source_id, domain, card_type, terms, triggers) in enumerate(specs, 1):
        cards.append(
            base_card(
                card_id=f"{domain}_{slug}_{idx:03d}",
                source_id=source_id,
                domain=domain,
                subdomain="family_ethics_communication",
                card_type=card_type,
                topic=topic,
                clinical_context="Use only for clinician-reviewed ethical context or family communication draft language.",
                key_points=[
                    f"The source explicitly discusses {topic.lower()} in ICU communication, end-of-life, or ethical conflict context.",
                    "This card is not for direct family delivery and cannot announce prognosis, futility, or treatment withdrawal recommendations.",
                ],
                trigger_signals=triggers,
                used_by_agents=["CompassionAgent", "PatientMemoryAgent", "ClinicalSummaryAgent", "WardCoordinatorAgent"] if domain == "end_of_life_ethics" else ["CompassionAgent", "PatientMemoryAgent", "ClinicalSummaryAgent"],
                allowed_use=["family communication draft", "ethical context", "clinician-reviewed summary"],
                forbidden_use=["direct family delivery without clinician approval", "definitive prognosis", "treatment withdrawal recommendation", "futility judgment"],
                retrieval_keywords=terms + triggers + ["family communication", "ICU ethics"],
                evidence_terms=terms,
                section_title="Family communication and ICU ethics",
                extra={
                    "requires_clinician_approval": True,
                    "not_for_direct_family_delivery": True,
                    "family_friendly_language": ["A clinician can review and adapt this into language that reflects the patient's current situation."],
                    "professional_preview_language": ["Use as draft context only; verify current goals, surrogate, and attending clinician plan."],
                    "phrases_to_avoid": ["Care is futile.", "There is no hope.", "The agent recommends stopping treatment."],
                },
            )
        )
    return cards


def design_and_concept_cards() -> list[dict[str, Any]]:
    design_specs = [
        ("visibility", "High-visibility ICU layout", ["high-visibility"], ["ICU design"]),
        ("windows", "Windows in patient rooms", ["windows"], ["patient room"]),
        ("natural_lighting", "Natural lighting and recovery context", ["natural lighting"], ["natural light"]),
        ("staff_respite", "Integrated staff break and respite spaces", ["break/respite"], ["staff respite"]),
        ("infection_prevention", "Infection prevention design features", ["infection prevention"], ["infection control"]),
        ("surge_capacity", "Flexible surge capacity in ICU design", ["surge capacity"], ["surge design"]),
        ("hvac_uncertainty", "Advanced HVAC evidence uncertainty", ["heating, ventilation"], ["HVAC"]),
        ("decentralized_charting", "Decentralized charting uncertainty", ["decentralized charting"], ["charting"]),
    ]
    cards: list[dict[str, Any]] = []
    for idx, (slug, topic, terms, triggers) in enumerate(design_specs, 1):
        cards.append(
            base_card(
                card_id=f"icu_design_context_{slug}_{idx:03d}",
                source_id="adult_icu_design_2024_001",
                domain="icu_design_context",
                subdomain="adult_icu_design",
                card_type="design_context",
                topic=topic,
                clinical_context="Use only for ICU environment/design background, not clinical risk scoring.",
                key_points=[
                    f"The source explicitly discusses {topic.lower()} as an adult ICU design issue.",
                    "This card is excluded from RiskSentinelAgent default retrieval.",
                ],
                trigger_signals=triggers,
                used_by_agents=["ClinicalSummaryAgent"],
                allowed_use=["ICU design background", "environment context"],
                forbidden_use=["risk scoring", "automatic clinical decision", "treatment order", "resource triage decision"],
                retrieval_keywords=terms + triggers + ["ICU design", "architecture"],
                evidence_terms=terms,
                section_title="Adult ICU design",
            )
        )
    concept_specs = [
        ("temperature", "APACHE II temperature input", "temperature"),
        ("map", "APACHE II mean arterial pressure input", "平均动脉"),
        ("heart_rate", "APACHE II heart rate input", "心率"),
        ("respiratory_rate", "APACHE II respiratory rate input", "呼吸频率"),
        ("oxygenation", "APACHE II oxygenation input", "氧合"),
        ("ph", "APACHE II arterial pH input", "pH"),
        ("sodium", "APACHE II serum sodium input", "钠"),
        ("potassium", "APACHE II serum potassium input", "钾"),
        ("creatinine", "APACHE II serum creatinine input", "肌酐"),
        ("hematocrit", "APACHE II hematocrit input", "血细胞"),
        ("wbc", "APACHE II white blood cell input", "白细胞"),
        ("gcs", "APACHE II Glasgow Coma Scale input", "Glasgow"),
        ("age", "APACHE II age input", "年龄"),
        ("chronic_health", "APACHE II chronic health points", "慢性"),
    ]
    for idx, (slug, topic, term) in enumerate(concept_specs, 1):
        evidence = evidence_for("msd_critical_illness_scoring_001", [term], "APACHE II")
        card = {
            "concept_id": f"apache_ii_{slug}_{idx:03d}",
            "card_id": f"apache_ii_{slug}_{idx:03d}",
            "source_id": "msd_critical_illness_scoring_001",
            "concept_name": topic,
            "domain": "computational_concepts",
            "card_type": "scoring_context",
            "topic": topic,
            "concept_type": "severity_score_input",
            "purpose": "Explain one APACHE II input for dashboard, benchmark, or summary context.",
            "inputs": [topic],
            "outputs": ["severity score context"],
            "key_points": [
                f"The MSD manual APACHE II table includes {topic.lower()} as scoring context.",
                "Use for explanation only; do not compute prognosis or make clinical decisions automatically.",
            ],
            "trigger_signals": [term, "APACHE II"],
            "related_risk_types": ["persistent_shock_risk", "respiratory_failure_risk", "aki_risk"],
            "used_by_agents": ["RiskSentinelAgent", "ClinicalSummaryAgent", "WardCoordinatorAgent"],
            "allowed_use": ["score explanation", "dashboard context", "benchmark support"],
            "forbidden_use": ["direct clinical decision", "automatic prognosis announcement", "treatment order", "drug dose recommendation"],
            "retrieval_keywords": [term, "APACHE II", "severity score", topic],
            "evidence_location": evidence,
            "confidence": "high",
            "human_review_required": True,
            "last_updated": TODAY,
        }
        cards.append(card)
    return cards


def memory_summary_cards() -> list[dict[str, Any]]:
    specs = [
        ("major_deterioration_event", "Major deterioration event memory tag", "clinical_deterioration_rapid_response_2024_001", "clinical_deterioration", ["clinical deterioration"], ["deterioration"]),
        ("intervention_response", "Intervention response monitoring memory tag", "clinical_deterioration_rapid_response_2024_001", "clinical_deterioration", ["response to clinical deterioration"], ["intervention response"]),
        ("unresolved_problem", "Unresolved problem summary context", "adult_icu_admission_triage_001", "general_icu_operations", ["quality assurance"], ["unresolved problem"]),
        ("round_summary", "Round summary context", "adult_icu_admission_triage_001", "general_icu_operations", ["clinical operations"], ["round summary"]),
        ("problem_list", "Problem list context", "adult_icu_admission_triage_001", "general_icu_operations", ["institutional policies"], ["problem list"]),
        ("triage_status", "Triage status summary context", "adult_icu_admission_triage_001", "general_icu_operations", ["Triage"], ["triage status"]),
        ("medication_safety_summary", "Medication safety summary context", "medication_safety_icu_001", "general_icu_operations", ["safe medication use"], ["medication safety summary"]),
        ("sedation_status", "Sedation status memory tag", "padis_update_2025_001", "general_icu_operations", ["agitation/sedation"], ["sedation_status"]),
        ("delirium_context", "Delirium context memory tag", "padis_update_2025_001", "general_icu_operations", ["delirium"], ["delirium_context"]),
        ("family_communication_event", "Family communication event memory tag", "clinical_deterioration_rapid_response_2024_001", "general_icu_operations", ["patient/family"], ["family_communication"]),
        ("ethical_decision", "Ethical decision memory tag", "potentially_inappropriate_treatments_001", "general_icu_operations", ["ethical"], ["ethical_decision"]),
        ("triage_priority", "Triage priority memory tag", "adult_icu_admission_triage_001", "general_icu_operations", ["priority"], ["triage_priority"]),
    ]
    cards = []
    for idx, (slug, topic, source_id, domain, terms, triggers) in enumerate(specs, 1):
        cards.append(
            base_card(
                card_id=f"{domain}_{slug}_{idx:03d}",
                source_id=source_id,
                domain=domain,
                subdomain="memory_summary_support",
                card_type="icu_operations_context" if domain == "general_icu_operations" else "guideline_context",
                topic=topic,
                clinical_context="Use to help PatientMemoryAgent and ClinicalSummaryAgent label ICU events for longitudinal summaries.",
                key_points=[
                    f"The source supports {topic.lower()} as contextual information for ICU event summaries.",
                    "Use as semantic tagging and summary support only; do not infer diagnoses or treatments.",
                ],
                trigger_signals=triggers,
                used_by_agents=["PatientMemoryAgent", "ClinicalSummaryAgent"],
                retrieval_keywords=terms + triggers + ["memory tag", "clinical summary"],
                evidence_terms=terms,
                section_title="Patient memory and summary support",
                extra={
                    "memory_tags": triggers,
                    "professional_summary_template": f"{topic}: document observed event and human-reviewed interpretation.",
                    "allowed_terms": triggers + ["context", "summary"],
                    "avoid_terms": ["diagnosed by agent", "treatment ordered by agent"],
                },
            )
        )
    return cards


def main() -> None:
    load_source_maps()
    cards = []
    cards.extend(clinical_deterioration_cards())
    cards.extend(medication_cards())
    cards.extend(padis_cards())
    cards.extend(triage_cards())
    cards.extend(family_ethics_cards())
    cards.extend(design_and_concept_cards())
    cards.extend(memory_summary_cards())
    write_cards(cards)
    print(f"Wrote {len(cards)} expanded knowledge cards.")


if __name__ == "__main__":
    main()
