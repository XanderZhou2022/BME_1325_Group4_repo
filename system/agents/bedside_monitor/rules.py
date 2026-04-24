from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .schemas import UrineOutputPoint, VitalPoint

THRESHOLDS: dict[str, dict[str, Any]] = {
    "mean_arterial_pressure": {"warning_lt": 65.0, "critical_lt": 60.0, "critical_duration_minutes": 15},
    "spo2": {"warning_lt": 92.0, "critical_lt": 88.0},
    "heart_rate": {"warning_gt": 120.0, "critical_gt": 140.0, "warning_lt": 50.0, "critical_lt": 40.0},
    "respiratory_rate": {"warning_gt": 24.0, "critical_gt": 30.0, "critical_lt": 8.0},
    "temperature": {"warning_gte": 38.5, "critical_gte": 39.5, "warning_lt": 35.0},
    "gcs": {"warning_lt": 13.0, "critical_lte": 8.0},
}


def _to_float(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def _window(vitals: list[VitalPoint], end: datetime, minutes: int) -> list[VitalPoint]:
    start = end - timedelta(minutes=minutes)
    return [v for v in vitals if start <= v.timestamp <= end]


def _metric_points(vitals: list[VitalPoint], metric: str) -> list[tuple[datetime, float]]:
    out: list[tuple[datetime, float]] = []
    for v in vitals:
        value = _to_float(getattr(v, metric))
        if value is not None:
            out.append((v.timestamp, value))
    return out


def _duration_below(points: list[tuple[datetime, float]], threshold: float) -> int:
    if len(points) < 2:
        return 0
    duration = 0
    for idx in range(1, len(points)):
        prev_ts, prev_val = points[idx - 1]
        curr_ts, _curr_val = points[idx]
        if prev_val < threshold:
            duration += int((curr_ts - prev_ts).total_seconds() / 60)
    return max(0, duration)


def _build_abnormal_flags(vitals_90m: list[VitalPoint]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for metric, cfg in THRESHOLDS.items():
        points = _metric_points(vitals_90m, metric)
        if not points:
            continue
        latest_val = points[-1][1]
        severity = None
        threshold_text = ""
        duration_minutes = 0

        if metric == "mean_arterial_pressure":
            duration_minutes = _duration_below(points, cfg["critical_lt"])
            if latest_val < cfg["critical_lt"] and duration_minutes >= cfg["critical_duration_minutes"]:
                severity = "critical"
                threshold_text = "<60 for >=15m"
            elif latest_val < cfg["warning_lt"]:
                severity = "warning"
                threshold_text = "<65"
        elif metric == "spo2":
            if latest_val < cfg["critical_lt"]:
                severity = "critical"
                threshold_text = "<88"
            elif latest_val < cfg["warning_lt"]:
                severity = "warning"
                threshold_text = "<92"
        elif metric == "heart_rate":
            if latest_val > cfg["critical_gt"] or latest_val < cfg["critical_lt"]:
                severity = "critical"
                threshold_text = ">140 or <40"
            elif latest_val > cfg["warning_gt"] or latest_val < cfg["warning_lt"]:
                severity = "warning"
                threshold_text = ">120 or <50"
        elif metric == "respiratory_rate":
            if latest_val > cfg["critical_gt"] or latest_val < cfg["critical_lt"]:
                severity = "critical"
                threshold_text = ">30 or <8"
            elif latest_val > cfg["warning_gt"]:
                severity = "warning"
                threshold_text = ">24"
        elif metric == "temperature":
            if latest_val >= cfg["critical_gte"]:
                severity = "critical"
                threshold_text = ">=39.5"
            elif latest_val >= cfg["warning_gte"] or latest_val < cfg["warning_lt"]:
                severity = "warning"
                threshold_text = ">=38.5 or <35"
        elif metric == "gcs":
            if latest_val <= cfg["critical_lte"]:
                severity = "critical"
                threshold_text = "<=8"
            elif latest_val < cfg["warning_lt"]:
                severity = "warning"
                threshold_text = "<13"

        if severity:
            flags.append(
                {
                    "type": f"{metric}_{severity}",
                    "severity": severity,
                    "metric": metric,
                    "value": latest_val,
                    "threshold": threshold_text,
                    "duration_minutes": duration_minutes,
                }
            )
    return flags


def _trend_for_metric(vitals_6h: list[VitalPoint], metric: str, delta: float) -> dict[str, Any] | None:
    points = _metric_points(vitals_6h, metric)
    if len(points) < 2:
        return None
    first = points[0][1]
    last = points[-1][1]
    diff = last - first
    trend = "stable"
    if diff >= delta:
        trend = "increasing"
    elif diff <= -delta:
        trend = "decreasing"
    return {
        "metric": metric,
        "trend": trend,
        "evidence": f"{metric} changed from {first:.2f} to {last:.2f} in last 6h.",
    }


def _build_trend_labels(vitals_6h: list[VitalPoint]) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    configs = [
        ("mean_arterial_pressure", 10.0),
        ("heart_rate", 20.0),
        ("spo2", 4.0),
        ("temperature", 1.0),
    ]
    for metric, delta in configs:
        label = _trend_for_metric(vitals_6h, metric, delta)
        if label:
            labels.append(label)
    return labels


def _latest_vitals(vitals_90m: list[VitalPoint]) -> dict[str, Any]:
    if not vitals_90m:
        return {}
    last = vitals_90m[-1]
    return {
        "timestamp": last.timestamp.isoformat(),
        "heart_rate": _to_float(last.heart_rate),
        "mean_arterial_pressure": _to_float(last.mean_arterial_pressure),
        "respiratory_rate": _to_float(last.respiratory_rate),
        "temperature": _to_float(last.temperature),
        "spo2": _to_float(last.spo2),
        "gcs": _to_float(last.gcs),
    }


def _summary_stats(vitals_90m: list[VitalPoint]) -> dict[str, Any]:
    metrics = ("heart_rate", "mean_arterial_pressure", "respiratory_rate", "temperature", "spo2", "gcs")
    out: dict[str, Any] = {}
    for metric in metrics:
        values = [v for _, v in _metric_points(vitals_90m, metric)]
        if values:
            out[metric] = {"min": min(values), "max": max(values), "latest": values[-1]}
    return out


def _urgency(abnormal_flags: list[dict[str, Any]]) -> str:
    if any(f["severity"] == "critical" for f in abnormal_flags):
        return "critical"
    if any(f["severity"] == "warning" for f in abnormal_flags):
        return "warning"
    return "info"


def run_bedside_rules(
    *,
    vitals: list[VitalPoint],
    urine_output_points: list[UrineOutputPoint] | None,
    analysis_end: datetime,
    window_minutes: int = 90,
    trend_hours: int = 6,
) -> dict[str, Any]:
    if analysis_end.tzinfo is None:
        analysis_end = analysis_end.replace(tzinfo=timezone.utc)
    vitals_90m = _window(vitals, analysis_end, window_minutes)
    vitals_6h = _window(vitals, analysis_end, trend_hours * 60)
    abnormal_flags = _build_abnormal_flags(vitals_90m)
    trend_labels = _build_trend_labels(vitals_6h)
    urgency_level = _urgency(abnormal_flags)
    status = "ok" if vitals_90m else "degraded"

    missing_fields = []
    for metric in ("heart_rate", "mean_arterial_pressure", "respiratory_rate", "temperature", "spo2", "gcs"):
        if not _metric_points(vitals_6h, metric):
            missing_fields.append(metric)
    if urine_output_points is None:
        missing_fields.append("urine_output_points")

    if status == "degraded":
        summary = "No vitals found in the requested window; bedside monitor degraded."
    elif abnormal_flags:
        summary = "Bedside monitor detected active abnormal vital signs that require close follow-up."
    else:
        summary = "No threshold breach detected in current bedside window."

    next_action_hint = "Continue routine monitoring."
    if urgency_level == "warning":
        next_action_hint = "Recommend risk_sentinel review if abnormalities persist."
    elif urgency_level == "critical":
        next_action_hint = "Immediate risk_sentinel and ward escalation recommended."

    return {
        "status": status,
        "current_status_summary": summary,
        "abnormal_flags": abnormal_flags,
        "trend_labels": trend_labels,
        "evidence": {
            "latest_vitals": _latest_vitals(vitals_90m),
            "summary_stats": _summary_stats(vitals_90m),
            "data_points_count": len(vitals_90m),
            "data_quality": {"missing_fields": missing_fields},
        },
        "urgency_level": urgency_level,
        "next_action_hint": next_action_hint,
    }

