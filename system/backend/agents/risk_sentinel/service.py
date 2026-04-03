from .schemas import RiskAssessmentRequest, RiskAssessment, ApacheIIBreakdown, EvidenceItem
from . import apache_ii_rules
from datetime import datetime
from typing import List, Optional
import math

def calculate_risk(request: RiskAssessmentRequest) -> RiskAssessment:
    """
    Calculate APACHE II risk score based on temporal state and patient info.
    """
    state = request.temporal_state
    vitals = state.get("current_vitals", {})
    
    evidence: List[EvidenceItem] = []
    physio_score = 0
    
    # Helper to accumulate scores and evidence
    def add_evidence(param: str, score_func, value: Optional[float], reason: str = "Based on window worst value"):
        if value is None:
            return 0
        score = score_func(value)
        physio_score_local = score # Just for local calc
        if score > 0:
             evidence.append(EvidenceItem(param=param, worst_value=value, score=score, reason=reason))
        return score

    # 1. Physiology Scoring
    # Temperature
    physio_score += add_evidence("temperature", apache_ii_rules.get_temp_score, vitals.get("temperature"))
    # MAP
    physio_score += add_evidence("mean_arterial_pressure", apache_ii_rules.get_map_score, vitals.get("mean_arterial_pressure"))
    # Heart Rate
    physio_score += add_evidence("heart_rate", apache_ii_rules.get_hr_score, vitals.get("heart_rate"))
    # Respiratory Rate
    physio_score += add_evidence("respiratory_rate", apache_ii_rules.get_rr_score, vitals.get("respiratory_rate"))
    # Oxygenation (Simplified: PaO2 check if FiO2 not high, else A-aDO2)
    # Note: Actual APACHE II logic is complex here, we use the helper.
    fio2 = vitals.get("fio2")
    pao2 = vitals.get("pao2")
    aado2 = vitals.get("aado2")
    oxy_score = apache_ii_rules.get_oxygen_score(fio2, pao2, aado2)
    if oxy_score > 0:
        evidence.append(EvidenceItem(param="oxygenation", worst_value=pao2 or fio2, score=oxy_score, reason="Based on window worst value"))
    physio_score += oxy_score
    
    # pH
    physio_score += add_evidence("ph", apache_ii_rules.get_ph_score, vitals.get("ph"))
    
    # Sodium, Potassium, Creatinine (assuming labs might be merged or passed separately, 
    # but here we check if they exist in vitals or we assume 0 if missing)
    # In a real scenario, these would come from lab_events.
    # We skip for now to keep strict alignment with provided vital_sign_events schema.
    
    # 2. Age Scoring
    age_score = apache_ii_rules.get_age_score(request.age)
    
    # 3. Chronic Health Scoring
    chronic_score = apache_ii_rules.get_chronic_health_score(request.chronic_health_status, request.is_elective_surgery)
    
    total_score = physio_score + age_score + chronic_score
    
    # 4. Severity Logic
    # <10 low, 10-14 medium, 15-25 high, >25 critical
    if total_score <= 9: 
        severity = "low"
    elif total_score <= 14: 
        severity = "warning" 
    elif total_score <= 25: 
        severity = "warning" # Maps to high
    else: 
        severity = "critical"
        
    # 5. Intervention Impact Logic
    # Check latest_interventions for response hints
    urgency_adjusted = False
    trend_direction = "stable"
    latest_interventions = state.get("latest_interventions", [])
    
    for inv in latest_interventions:
        # Handle both dict (from JSON) and Pydantic model (if passed as object)
        hint = None
        if isinstance(inv, dict):
            hint = inv.get("response_hint")
        else:
            hint = getattr(inv, 'response_hint', None)
            
        if hint in ["non_responsive", "deteriorating_despite_intervention"]:
            urgency_adjusted = True
            # Bump severity if needed
            if severity == "low": 
                severity = "warning"
            elif severity == "warning": 
                severity = "critical"
            
            trend_direction = "worsening"
            break
            
    if not urgency_adjusted:
        trend_direction = "stable" # Simplified
        if total_score > 15: # If high score but no worsening trend yet
            trend_direction = "worsening"
            
    # 6. Confidence calculation
    # Based on data completeness from memory agent
    completeness = state.get("data_completeness_ratio", 1.0)
    confidence = max(0.1, completeness) 
    
    breakdown = ApacheIIBreakdown(
        physiology=physio_score,
        age=age_score,
        chronic_health=chronic_score,
        total=total_score
    )
    
    # Recommended Action
    recommended_action = "Continue monitoring"
    if severity == "warning" and not urgency_adjusted:
        recommended_action = "Review patient state and trends"
    elif severity == "critical" or urgency_adjusted:
        recommended_action = "Urgent clinical review required"
        
    return RiskAssessment(
        admission_id=request.admission_id,
        timestamp=datetime.utcnow(),
        risk_type="apache_ii_comprehensive",
        confidence=confidence,
        severity=severity,
        evidence=evidence,
        time_window=f"last_{request.window_hours}h",
        recommended_action=recommended_action,
        apache_ii_breakdown=breakdown,
        intervention_context_impact="none" if not urgency_adjusted else "negative_response",
        urgency_adjusted=urgency_adjusted,
        trend_direction=trend_direction
    )