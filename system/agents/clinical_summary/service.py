"""Service logic for Clinical Summary Agent."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .schemas import (
    ClinicalSummaryRequest,
    ClinicalSummaryResponse,
    ProblemListItem,
)
from .templates import (
    deduce_problems,
    generate_summary_text,
    generate_focus_areas,
)


def generate_summary(req: ClinicalSummaryRequest) -> ClinicalSummaryResponse:
    """
    Generate clinical summary by aggregating outputs from downstream agents.
    """

    # 1. Deduce and prioritize clinical problems
    problems: List[ProblemListItem] = deduce_problems(
        vitals_summary=req.vitals_summary,
        active_risks=req.active_risks,
        intervention_responses=req.intervention_responses,
    )

    # 2. Generate 24h round summary text
    summary_text = generate_summary_text(
        admission_reason=req.memory_context.admission_reason,
        problems=problems,
        interventions=req.intervention_responses,
        unresolved_problems=req.memory_context.unresolved_problems,
    )

    # 3. Determine focus areas for the next period
    focus_areas = generate_focus_areas(
        problems=problems,
        interventions=req.intervention_responses,
    )

    # 4. Compose clinical narrative
    # A concise string combining admission reason, key problems, and status.
    problem_str = (
        ", ".join([f"{p.problem} ({p.urgency})" for p in problems])
        if problems
        else "None identified"
    )
    narrative_parts = [
        f"Patient admitted for {req.memory_context.admission_reason}.",
        f"Current active problems: {problem_str}.",
        f"Summary: {summary_text}",
        f"Focus: {', '.join(focus_areas)}.",
    ]
    clinical_narrative = " ".join(narrative_parts)

    return ClinicalSummaryResponse(
        patient_id=req.patient_id,
        bed_id=req.bed_id,
        admission_id=req.admission_id,
        generated_at=datetime.now(timezone.utc),
        twenty_four_hour_summary=summary_text,
        problem_list=problems,
        focus_areas_for_today=focus_areas,
        clinical_narrative=clinical_narrative,
    )