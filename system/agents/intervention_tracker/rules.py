from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from .schemas import InterventionType, ResponseAssessment, VitalPoint


MAP_TARGET = 65.0
MAP_RESPONSIVE_DELTA = 5.0
MAP_PARTIALLY_RESPONSIVE_DELTA = 3.0
MAP_DETERIORATE_DELTA = -2.0

SPO2_TARGET = 90.0
SPO2_RESPONSIVE_DELTA = 3.0
SPO2_PARTIALLY_RESPONSIVE_DELTA = 1.5
SPO2_DETERIORATE_DELTA = -3.0


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values)) / len(values)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(statistics.pstdev(values))


def _mean_metric(vitals: list[VitalPoint], metric: str) -> float | None:
    vals: list[float] = []
    for v in vitals:
        x = getattr(v, metric)
        if x is None:
            continue
        vals.append(float(x))
    return _mean(vals)


def _values_metric(vitals: list[VitalPoint], metric: str) -> list[float]:
    out: list[float] = []
    for v in vitals:
        x = getattr(v, metric)
        if x is None:
            continue
        out.append(float(x))
    return out


def _canonical_intervention_type(intervention_type: InterventionType) -> InterventionType:
    if intervention_type == "fluid":
        return "fluid_bolus"
    if intervention_type == "vasopressor":
        return "vasopressor_adjustment"
    if intervention_type == "ventilator_change":
        return "ventilator_adjustment"
    return intervention_type


def _assess_map_response(*, pre: list[VitalPoint], post: list[VitalPoint]) -> tuple[ResponseAssessment, dict[str, Any], list[dict[str, Any]]]:
    pre_vals = _values_metric(pre, "mean_arterial_pressure")
    post_vals = _values_metric(post, "mean_arterial_pressure")
    pre_mean = _mean(pre_vals)
    post_mean = _mean(post_vals)
    delta = None if pre_mean is None or post_mean is None else post_mean - pre_mean

    evidence: list[dict[str, Any]] = [
        {"metric": "MAP", "kind": "pre", "values": pre_vals, "mean": pre_mean, "stdev": _stdev(pre_vals)},
        {"metric": "MAP", "kind": "post", "values": post_vals, "mean": post_mean, "stdev": _stdev(post_vals)},
    ]

    if pre_mean is None or post_mean is None or delta is None:
        return (
            "not_enough_data",
            {"metric": "MAP", "pre_mean": pre_mean, "post_mean": post_mean, "delta": delta, "reason": "insufficient_data"},
            evidence,
        )

    # Decision logic: separate "reachable target" from "direction of change".
    if post_mean >= MAP_TARGET and delta >= MAP_RESPONSIVE_DELTA:
        assessment: ResponseAssessment = "responsive"
    elif (post_mean >= MAP_TARGET and delta >= MAP_PARTIALLY_RESPONSIVE_DELTA) or (
        delta >= MAP_PARTIALLY_RESPONSIVE_DELTA and post_mean < MAP_TARGET
    ):
        assessment = "partially_responsive"
    elif MAP_DETERIORATE_DELTA < delta < MAP_PARTIALLY_RESPONSIVE_DELTA and abs(delta) < 2.0:
        # delta near zero -> no clear expected change
        assessment = "non_responsive"
    elif delta <= MAP_DETERIORATE_DELTA:
        assessment = "deteriorating_despite_intervention"
    else:
        assessment = "non_responsive"

    target_metrics = {
        "metric": "MAP",
        "target": MAP_TARGET,
        "pre_mean": pre_mean,
        "post_mean": post_mean,
        "delta": delta,
        "thresholds": {"responsive_delta": MAP_RESPONSIVE_DELTA, "partial_delta": MAP_PARTIALLY_RESPONSIVE_DELTA},
    }
    before_after = {"pre_mean": pre_mean, "post_mean": post_mean, "delta": delta}
    return assessment, {**target_metrics, **before_after}, evidence


def _assess_ventilator_response(
    *, pre: list[VitalPoint], post: list[VitalPoint]
) -> tuple[ResponseAssessment, dict[str, Any], list[dict[str, Any]]]:
    pre_spo2_vals = _values_metric(pre, "spo2")
    post_spo2_vals = _values_metric(post, "spo2")
    pre_rr_vals = _values_metric(pre, "respiratory_rate")
    post_rr_vals = _values_metric(post, "respiratory_rate")

    pre_spo2_mean = _mean(pre_spo2_vals)
    post_spo2_mean = _mean(post_spo2_vals)
    pre_rr_mean = _mean(pre_rr_vals)
    post_rr_mean = _mean(post_rr_vals)

    delta_spo2 = None if pre_spo2_mean is None or post_spo2_mean is None else post_spo2_mean - pre_spo2_mean
    delta_rr = None if pre_rr_mean is None or post_rr_mean is None else post_rr_mean - pre_rr_mean

    evidence: list[dict[str, Any]] = [
        {"metric": "SpO2", "kind": "pre", "values": pre_spo2_vals, "mean": pre_spo2_mean, "stdev": _stdev(pre_spo2_vals)},
        {"metric": "SpO2", "kind": "post", "values": post_spo2_vals, "mean": post_spo2_mean, "stdev": _stdev(post_spo2_vals)},
        {"metric": "RR", "kind": "pre", "values": pre_rr_vals, "mean": pre_rr_mean, "stdev": _stdev(pre_rr_vals)},
        {"metric": "RR", "kind": "post", "values": post_rr_vals, "mean": post_rr_mean, "stdev": _stdev(post_rr_vals)},
    ]

    if pre_spo2_mean is None or post_spo2_mean is None or delta_spo2 is None:
        return (
            "not_enough_data",
            {
                "metric": "SpO2/RR",
                "pre_spo2_mean": pre_spo2_mean,
                "post_spo2_mean": post_spo2_mean,
                "delta_spo2": delta_spo2,
                "reason": "insufficient_data",
            },
            evidence,
        )

    rr_improved = None
    if pre_rr_mean is not None and post_rr_mean is not None and delta_rr is not None:
        # Lower RR is usually better for oxygenation in this simplified rule set.
        rr_improved = delta_rr <= -1.0

    if post_spo2_mean >= SPO2_TARGET and delta_spo2 >= SPO2_RESPONSIVE_DELTA and (rr_improved is not False):
        assessment: ResponseAssessment = "responsive"
    elif (post_spo2_mean >= SPO2_TARGET and delta_spo2 >= SPO2_PARTIALLY_RESPONSIVE_DELTA) or (
        delta_spo2 >= SPO2_RESPONSIVE_DELTA and post_spo2_mean < SPO2_TARGET
    ):
        assessment = "partially_responsive"
    elif (abs(delta_spo2) < 1.0) and (delta_rr is None or abs(delta_rr) < 1.0):
        assessment = "non_responsive"
    elif delta_spo2 <= SPO2_DETERIORATE_DELTA:
        assessment = "deteriorating_despite_intervention"
    else:
        assessment = "non_responsive"

    target_metrics = {
        "metric": "SpO2/RR",
        "spo2_target": SPO2_TARGET,
        "pre_spo2_mean": pre_spo2_mean,
        "post_spo2_mean": post_spo2_mean,
        "delta_spo2": delta_spo2,
        "pre_rr_mean": pre_rr_mean,
        "post_rr_mean": post_rr_mean,
        "delta_rr": delta_rr,
        "thresholds": {"spo2_responsive_delta": SPO2_RESPONSIVE_DELTA, "spo2_partial_delta": SPO2_PARTIALLY_RESPONSIVE_DELTA},
    }
    before_after = {"delta_spo2": delta_spo2, "delta_rr": delta_rr}
    return assessment, {**target_metrics, **before_after}, evidence


def _assess_antibiotic_response(*, pre: list[VitalPoint], post: list[VitalPoint]) -> tuple[ResponseAssessment, dict[str, Any], list[dict[str, Any]]]:
    pre_temp = _mean_metric(pre, "temperature")
    post_temp = _mean_metric(post, "temperature")
    pre_lac = _mean_metric(pre, "lactate")
    post_lac = _mean_metric(post, "lactate")
    pre_map = _mean_metric(pre, "mean_arterial_pressure")
    post_map = _mean_metric(post, "mean_arterial_pressure")
    evidence = [
        {"metric": "Temp", "pre_mean": pre_temp, "post_mean": post_temp},
        {"metric": "lactate", "pre_mean": pre_lac, "post_mean": post_lac},
        {"metric": "MAP", "pre_mean": pre_map, "post_mean": post_map},
    ]
    if post_temp is None and post_lac is None and post_map is None:
        return "not_enough_data", {"reason": "insufficient_antibiotic_followup"}, evidence
    improved_temp = pre_temp is not None and post_temp is not None and post_temp <= pre_temp - 0.5
    improved_lac = pre_lac is not None and post_lac is not None and post_lac <= pre_lac - 0.3
    improved_map = pre_map is not None and post_map is not None and post_map >= pre_map + 3.0
    worsened = (
        (pre_temp is not None and post_temp is not None and post_temp > pre_temp + 0.3)
        or (pre_lac is not None and post_lac is not None and post_lac > pre_lac + 0.2)
        or (pre_map is not None and post_map is not None and post_map < pre_map - 3.0)
    )
    score = int(improved_temp) + int(improved_lac) + int(improved_map)
    if worsened:
        assessment: ResponseAssessment = "deteriorating_despite_intervention"
    elif score >= 2:
        assessment = "responsive"
    elif score == 1:
        assessment = "partially_responsive"
    else:
        assessment = "non_responsive"
    return assessment, {"metric": "sepsis_bundle_response", "improvement_score": score}, evidence


def run_intervention_tracker(
    *,
    intervention_type: InterventionType,
    intervention_time: datetime,
    pre_vitals: list[VitalPoint],
    post_vitals: list[VitalPoint],
    observation_window: str,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    canonical_type = _canonical_intervention_type(intervention_type)
    if canonical_type in ("fluid_bolus", "vasopressor_adjustment"):
        assessment, metrics_and_comp, ev = _assess_map_response(pre=pre_vitals, post=post_vitals)
        evidence = ev
        target_metrics = {k: metrics_and_comp[k] for k in metrics_and_comp.keys() if k not in ("pre_mean", "post_mean", "delta")}
        before_after = {
            "pre_mean": metrics_and_comp.get("pre_mean"),
            "post_mean": metrics_and_comp.get("post_mean"),
            "delta": metrics_and_comp.get("delta"),
        }
    elif canonical_type == "ventilator_adjustment":
        assessment, metrics_and_comp, ev = _assess_ventilator_response(pre=pre_vitals, post=post_vitals)
        evidence = ev
        target_metrics = {
            "metric": "SpO2/RR",
            "spo2_target": metrics_and_comp.get("spo2_target"),
            "pre_spo2_mean": metrics_and_comp.get("pre_spo2_mean"),
            "post_spo2_mean": metrics_and_comp.get("post_spo2_mean"),
            "delta_spo2": metrics_and_comp.get("delta_spo2"),
            "pre_rr_mean": metrics_and_comp.get("pre_rr_mean"),
            "post_rr_mean": metrics_and_comp.get("post_rr_mean"),
        }
        before_after = {"delta_spo2": metrics_and_comp.get("delta_spo2"), "delta_rr": metrics_and_comp.get("delta_rr")}
    else:
        assessment, metrics_and_comp, ev = _assess_antibiotic_response(pre=pre_vitals, post=post_vitals)
        evidence = ev
        target_metrics = metrics_and_comp
        before_after = metrics_and_comp

    if assessment == "not_enough_data":
        hint = "Post-intervention data are not enough; keep pending and re-evaluate at next checkpoint."
    elif assessment == "responsive":
        hint = "干预后，监测指标在预期方向出现改善；继续密切监测。"
    elif assessment == "partially_responsive":
        hint = "干预后观察窗口内仅见部分生理改善；建议结合临床评估重新解读趋势。"
    elif assessment == "deteriorating_despite_intervention":
        hint = "干预后生理指标未见预期改善，且呈恶化趋势；建议进一步评估原因。"
    else:
        hint = "干预后观察窗口内未见明确的预期反应；建议按流程复核监测与干预执行情况。"

    return {
        "response_assessment": assessment,
        "response_label": assessment,
        "target_metrics": target_metrics,
        "before_after_comparison": before_after,
        "evidence": evidence,
        "escalation_hint": hint,
        "observation_window": observation_window,
        "intervention_time": intervention_time,
        "canonical_intervention_type": canonical_type,
    }

