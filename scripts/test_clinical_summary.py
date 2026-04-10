"""
Test Scenario: Septic Shock Deterioration
Tests the Clinical Summary Agent by simulating aggregated inputs from downstream agents.
"""
import os
import sys
from datetime import datetime, timezone

# Adjust path to allow importing from system root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from system.agents.clinical_summary.schemas import (
    ClinicalSummaryRequest,
    VitalsSummary,
    InterventionResponse,
    ActiveRisk,
    MemoryContext,
)
from system.agents.clinical_summary.service import generate_summary


def run_test():
    print("=" * 60)
    print("TEST CASE: Septic Shock Deterioration")
    print("=" * 60)

    # 1. Simulate Bedside Monitor Output
    # Detected hypotension, tachycardia, and oliguria
    vitals_summary = VitalsSummary(
        abnormal_flags=["persistent_hypotension", "tachycardia", "oliguria"],
        trend_labels=["downward_map", "declining_uo"],
        evidence=[
            {"metric": "MAP", "value": 58, "unit": "mmHg"},
            {"metric": "HR", "value": 115, "unit": "bpm"},
            {"metric": "UrineOutput", "value": 0.4, "unit": "ml/kg/h"}
        ]
    )

    # 2. Simulate Intervention Tracker Output
    # Fluid bolus was given, but patient was non-responsive
    intervention_responses = [
        InterventionResponse(
            intervention_id="INT_FLUID_001",
            intervention_type="fluid",
            intervention_time=datetime(2023, 10, 27, 10, 0, 0, tzinfo=timezone.utc),
            response_assessment="non_responsive",
            target_metrics={"MAP_target": 65},
            before_after_comparison={"MAP_before": 60, "MAP_after": 58}
        )
    ]

    # 3. Simulate Risk Sentinel Output
    # High risk of Shock
    active_risks = [
        ActiveRisk(
            risk_type="Shock Risk",
            confidence=0.95,
            evidence="Persistent hypotension despite fluid resuscitation. Lactate rising.",
            urgency_level="critical"
        )
    ]

    # 4. Simulate Patient Memory Context
    memory_context = MemoryContext(
        admission_reason="Community Acquired Pneumonia leading to Sepsis",
        major_icu_course=["Intubated", "Started Broad Spectrum Antibiotics"],
        unresolved_problems=["Hemodynamic instability", "Source control pending"],
        key_turning_points=["Deterioration at 10:00"]
    )

    # Construct the Request
    request = ClinicalSummaryRequest(
        patient_id="PAT_001",
        bed_id="BED_ICU_1",
        admission_id="ADM_001",
        vitals_summary=vitals_summary,
        intervention_responses=intervention_responses,
        active_risks=active_risks,
        memory_context=memory_context
    )

    try:
        # Generate Summary
        response = generate_summary(request)

        print("\n--- AGENT OUTPUT ---")
        print(f"Generated At: {response.generated_at}")
        print(f"\nProblem List (Prioritized):")
        for i, p in enumerate(response.problem_list):
            print(f"  {i+1}. [{p.urgency.upper()}] {p.problem}")
            print(f"     Status: {p.intervention_status}")
            print(f"     Evidence: {p.evidence}")

        print(f"\nFocus Areas:")
        for f in response.focus_areas_for_today:
            print(f"  - {f}")

        print(f"\nClinical Narrative:")
        print(f"  {response.clinical_narrative}")

        # Assertions
        print("\n--- VALIDATION ---")
        problems = {p.problem: p for p in response.problem_list}
        
        # Check if Hemodynamic Instability is Critical
        if "Hemodynamic Instability" in problems:
            prob = problems["Hemodynamic Instability"]
            if prob.urgency == "critical":
                print("[PASS] Hemodynamic Instability correctly identified as CRITICAL.")
            else:
                print("[FAIL] Hemodynamic Instability should be CRITICAL.")
        else:
            print("[FAIL] Hemodynamic Instability missing from Problem List.")

        # Check Focus Areas for Vasopressor suggestion
        if any("vasopressor" in f.lower() for f in response.focus_areas_for_today):
            print("[PASS] Agent correctly suggested considering vasopressors.")
        else:
            print("[FAIL] Agent should suggest vasopressors for non-responsive fluid shock.")

    except Exception as e:
        print(f"--- TEST FAILED ---\nError: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()