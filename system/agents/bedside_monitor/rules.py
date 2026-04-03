from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from .schemas import UrineOutputPoint, VitalPoint


# --- Rule thresholds (simulation defaults; adjust later if you add richer patient context) ---
MAP_PERSISTENT_THRESHOLD = 65.0  # mmHg
SPO2_PERSISTENT_THRESHOLD = 90.0  # %
HR_TACHYCARDIA_THRESHOLD = 110.0  # bpm
TEMP_FEVER_THRESHOLD = 38.0  # Celsius

MAP_PERSISTENT_MINUTES = 30
SPO2_PERSISTENT_MINUTES = 30
HR_PERSISTENT_MINUTES = 20
TEMP_PERSISTENT_MINUTES = 10

# Oliguria (simulation convention): urine_output_ml_per_hour <= threshold_ml_per_hour
# Typical clinical rule is < 0.5 ml/kg/hr; we approximate without weight.
DEFAULT_OLIGURIA_THRESHOLD_ML_PER_HOUR = 30.0
OLIGURIA_LOOKBACK_MINUTES = 60

# Trend analysis window (per tasks book first-layer requirement)
TREND_MINUTES = 45

MIN_POINTS_FOR_PERSISTENT_RULE = 2


def _to_float(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, float):
        return x
    if isinstance(x, int):
        return float(x)
    # psycopg often returns Decimal for NUMERIC columns.
    try:
        return float(x)
    except Exception:
        return None


def _window_points(
    points: list[VitalPoint],
    metric: str,
    *,
    end: datetime,
    minutes: int,
) -> list[float]:
    start = end - timedelta(minutes=minutes)
    out: list[float] = []
    for p in points:
        if p.timestamp < start or p.timestamp > end:
            continue
        v = getattr(p, metric)
        fv = _to_float(v)
        if fv is None:
            continue
        out.append(fv)
    return out


def _window_last_value(
    points: list[VitalPoint],
    metric: str,
    *,
    end: datetime,
    minutes: int,
) -> float | None:
    start = end - timedelta(minutes=minutes)
    last_ts: datetime | None = None
    last_val: float | None = None
    for p in points:
        if p.timestamp < start or p.timestamp > end:
            continue
        v = getattr(p, metric)
        fv = _to_float(v)
        if fv is None:
            continue
        if last_ts is None or p.timestamp > last_ts:
            last_ts = p.timestamp
            last_val = fv
    return last_val


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values)) / len(values)


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return 0.0
    return float(statistics.pstdev(values))


def _classify_direction(first: float, last: float, *, stable_ratio: float) -> str:
    denom = max(abs(first), 1e-9)
    ratio = (last - first) / denom
    if abs(ratio) <= stable_ratio:
        return "stable"
    if ratio < 0:
        return "downtrend"
    return "uptrend"


def _trend_labels(vitals: list[VitalPoint], *, analysis_end: datetime) -> tuple[list[str], list[dict[str, Any]]]:
    labels: list[str] = []
    evidence: list[dict[str, Any]] = []

    # MAP
    map_vals = _window_points(vitals, "mean_arterial_pressure", end=analysis_end, minutes=TREND_MINUTES)
    map_last = _window_last_value(vitals, "mean_arterial_pressure", end=analysis_end, minutes=TREND_MINUTES)
    if map_vals and map_last is not None:
        first = map_vals[0]
        direction = _classify_direction(first, map_last, stable_ratio=0.05)
        if direction == "downtrend":
            labels.append("MAP_downtrend")
        elif direction == "uptrend":
            labels.append("MAP_uptrend")
        evidence.append(
            {"kind": "trend", "metric": "MAP", "window_minutes": TREND_MINUTES, "first": first, "last": map_last}
        )

    # SpO2: unstable detection + direction
    spo2_vals = _window_points(vitals, "spo2", end=analysis_end, minutes=TREND_MINUTES)
    spo2_last = _window_last_value(vitals, "spo2", end=analysis_end, minutes=TREND_MINUTES)
    if spo2_vals and spo2_last is not None:
        first = spo2_vals[0]
        std = _std(spo2_vals) or 0.0
        rng = max(spo2_vals) - min(spo2_vals) if len(spo2_vals) >= 2 else 0.0
        if rng >= 10.0 or std >= 5.0:
            labels.append("SpO2_unstable")
        else:
            direction = _classify_direction(first, spo2_last, stable_ratio=0.05)
            if direction == "downtrend":
                labels.append("SpO2_downtrend")
        evidence.append(
            {
                "kind": "trend",
                "metric": "SpO2",
                "window_minutes": TREND_MINUTES,
                "first": first,
                "last": spo2_last,
                "std": std,
                "range": rng,
            }
        )

    # HR
    hr_vals = _window_points(vitals, "heart_rate", end=analysis_end, minutes=TREND_MINUTES)
    hr_last = _window_last_value(vitals, "heart_rate", end=analysis_end, minutes=TREND_MINUTES)
    if hr_vals and hr_last is not None:
        first = hr_vals[0]
        direction = _classify_direction(first, hr_last, stable_ratio=0.05)
        if direction == "uptrend":
            labels.append("HR_uptrend")
        elif direction == "downtrend":
            labels.append("HR_downtrend")
        evidence.append(
            {"kind": "trend", "metric": "HR", "window_minutes": TREND_MINUTES, "first": first, "last": hr_last}
        )

    # Temp
    temp_vals = _window_points(vitals, "temperature", end=analysis_end, minutes=TREND_MINUTES)
    temp_last = _window_last_value(vitals, "temperature", end=analysis_end, minutes=TREND_MINUTES)
    if temp_vals and temp_last is not None:
        first = temp_vals[0]
        direction = _classify_direction(first, temp_last, stable_ratio=0.03)
        if direction == "uptrend":
            labels.append("Temp_rising")
        elif direction == "downtrend":
            labels.append("Temp_falling")
        evidence.append(
            {"kind": "trend", "metric": "Temp", "window_minutes": TREND_MINUTES, "first": first, "last": temp_last}
        )

    return labels, evidence


def _detect_persistent_flags(vitals: list[VitalPoint], *, analysis_end: datetime) -> tuple[list[str], list[dict[str, Any]]]:
    flags: list[str] = []
    evidence: list[dict[str, Any]] = []

    # persistent_hypotension: MAP < 65 in last 30 minutes
    map_recent = _window_points(vitals, "mean_arterial_pressure", end=analysis_end, minutes=MAP_PERSISTENT_MINUTES)
    map_last = _window_last_value(vitals, "mean_arterial_pressure", end=analysis_end, minutes=MAP_PERSISTENT_MINUTES)
    if len(map_recent) >= MIN_POINTS_FOR_PERSISTENT_RULE and map_last is not None:
        map_mean = _mean(map_recent) or float("nan")
        if map_mean < MAP_PERSISTENT_THRESHOLD and map_last < MAP_PERSISTENT_THRESHOLD:
            flags.append("persistent_hypotension")
            evidence.append(
                {
                    "kind": "abnormal_flag",
                    "flag": "persistent_hypotension",
                    "metric": "MAP",
                    "threshold": MAP_PERSISTENT_THRESHOLD,
                    "window_minutes": MAP_PERSISTENT_MINUTES,
                    "recent_mean": map_mean,
                    "recent_values": map_recent,
                    "last_value": map_last,
                }
            )

    # hypoxemia: SpO2 < 90 in last 30 minutes
    spo2_recent = _window_points(vitals, "spo2", end=analysis_end, minutes=SPO2_PERSISTENT_MINUTES)
    spo2_last = _window_last_value(vitals, "spo2", end=analysis_end, minutes=SPO2_PERSISTENT_MINUTES)
    if len(spo2_recent) >= MIN_POINTS_FOR_PERSISTENT_RULE and spo2_last is not None:
        spo2_mean = _mean(spo2_recent) or float("nan")
        if spo2_mean < SPO2_PERSISTENT_THRESHOLD and spo2_last < SPO2_PERSISTENT_THRESHOLD:
            flags.append("hypoxemia")
            evidence.append(
                {
                    "kind": "abnormal_flag",
                    "flag": "hypoxemia",
                    "metric": "SpO2",
                    "threshold": SPO2_PERSISTENT_THRESHOLD,
                    "window_minutes": SPO2_PERSISTENT_MINUTES,
                    "recent_mean": spo2_mean,
                    "recent_values": spo2_recent,
                    "last_value": spo2_last,
                }
            )

    # tachycardia: HR > 110 in last 20 minutes
    hr_recent = _window_points(vitals, "heart_rate", end=analysis_end, minutes=HR_PERSISTENT_MINUTES)
    hr_last = _window_last_value(vitals, "heart_rate", end=analysis_end, minutes=HR_PERSISTENT_MINUTES)
    if len(hr_recent) >= MIN_POINTS_FOR_PERSISTENT_RULE and hr_last is not None:
        hr_mean = _mean(hr_recent) or float("nan")
        if hr_mean > HR_TACHYCARDIA_THRESHOLD and hr_last > HR_TACHYCARDIA_THRESHOLD:
            flags.append("tachycardia")
            evidence.append(
                {
                    "kind": "abnormal_flag",
                    "flag": "tachycardia",
                    "metric": "HR",
                    "threshold": HR_TACHYCARDIA_THRESHOLD,
                    "window_minutes": HR_PERSISTENT_MINUTES,
                    "recent_mean": hr_mean,
                    "recent_values": hr_recent,
                    "last_value": hr_last,
                }
            )

    # fever: Temp >= 38 in last 10 minutes
    temp_recent = _window_points(vitals, "temperature", end=analysis_end, minutes=TEMP_PERSISTENT_MINUTES)
    temp_last = _window_last_value(vitals, "temperature", end=analysis_end, minutes=TEMP_PERSISTENT_MINUTES)
    if len(temp_recent) >= MIN_POINTS_FOR_PERSISTENT_RULE and temp_last is not None:
        temp_mean = _mean(temp_recent) or float("nan")
        if temp_mean >= TEMP_FEVER_THRESHOLD and temp_last >= TEMP_FEVER_THRESHOLD:
            flags.append("fever")
            evidence.append(
                {
                    "kind": "abnormal_flag",
                    "flag": "fever",
                    "metric": "Temp",
                    "threshold": TEMP_FEVER_THRESHOLD,
                    "window_minutes": TEMP_PERSISTENT_MINUTES,
                    "recent_mean": temp_mean,
                    "recent_values": temp_recent,
                    "last_value": temp_last,
                }
            )

    return flags, evidence


def _detect_oliguria(
    urine_points: list[UrineOutputPoint],
    *,
    analysis_end: datetime,
) -> tuple[list[str], list[dict[str, Any]]]:
    if not urine_points:
        return [], []

    start = analysis_end - timedelta(minutes=OLIGURIA_LOOKBACK_MINUTES)
    recent = [p for p in urine_points if start <= p.timestamp <= analysis_end]
    if len(recent) < 2:
        return [], []

    values = [float(p.urine_output_ml_per_hour) for p in recent]
    first = values[0]
    last = values[-1]
    recent_mean = float(sum(values)) / len(values)

    flags: list[str] = []
    evidence: list[dict[str, Any]] = []

    # Oliguria: mean is below a threshold AND trend is decreasing.
    if recent_mean <= DEFAULT_OLIGURIA_THRESHOLD_ML_PER_HOUR and last < first:
        flags.append("oliguria")
        evidence.append(
            {
                "kind": "abnormal_flag",
                "flag": "oliguria",
                "metric": "urine_output_ml_per_hour",
                "threshold_ml_per_hour": DEFAULT_OLIGURIA_THRESHOLD_ML_PER_HOUR,
                "window_minutes": OLIGURIA_LOOKBACK_MINUTES,
                "recent_mean": recent_mean,
                "first": first,
                "last": last,
                "recent_values": values,
            }
        )

    # Add trend evidence only when it's meaningfully decreasing.
    if last < first and abs(first - last) / max(abs(first), 1e-9) >= 0.1:
        evidence.append(
            {
                "kind": "trend",
                "flag": "urine_output_decreasing",
                "first": first,
                "last": last,
            }
        )

    return flags, evidence


def _urgency_from_flags(flags: list[str], *, vitals: list[VitalPoint]) -> str:
    score = 0

    if "persistent_hypotension" in flags:
        score = max(score, 3)
    if "hypoxemia" in flags:
        score = max(score, 3)
    if "tachycardia" in flags:
        score = max(score, 2)
    if "oliguria" in flags:
        score = max(score, 2)
    if "fever" in flags:
        # Make higher fever more urgent if available.
        last_temp = _window_last_value(vitals, "temperature", end=max(p.timestamp for p in vitals), minutes=TEMP_PERSISTENT_MINUTES)
        if last_temp is not None and last_temp >= 39.5:
            score = max(score, 3)
        else:
            score = max(score, 1)

    if score >= 3:
        return "critical"
    if score >= 2:
        return "warning"
    return "info"


def _build_summary(
    flags: list[str],
    *,
    vitals: list[VitalPoint],
    urine_output_points: list[UrineOutputPoint] | None,
    analysis_end: datetime,
) -> str:
    sentences: list[str] = []

    if "persistent_hypotension" in flags:
        map_recent = _window_points(vitals, "mean_arterial_pressure", end=analysis_end, minutes=MAP_PERSISTENT_MINUTES)
        map_mean = _mean(map_recent) or float("nan")
        map_last = _window_last_value(vitals, "mean_arterial_pressure", end=analysis_end, minutes=MAP_PERSISTENT_MINUTES)
        sentences.append(
            f"过去 {MAP_PERSISTENT_MINUTES} 分钟 MAP 持续低于 {MAP_PERSISTENT_THRESHOLD:.0f}（最近平均 {map_mean:.1f}，当前 {map_last:.1f}），循环状态仍不稳定。"
        )

    if "hypoxemia" in flags:
        spo2_recent = _window_points(vitals, "spo2", end=analysis_end, minutes=SPO2_PERSISTENT_MINUTES)
        spo2_mean = _mean(spo2_recent) or float("nan")
        spo2_last = _window_last_value(vitals, "spo2", end=analysis_end, minutes=SPO2_PERSISTENT_MINUTES)
        sentences.append(
            f"过去 {SPO2_PERSISTENT_MINUTES} 分钟 SpO2 持续低于 {SPO2_PERSISTENT_THRESHOLD:.0f}%（最近平均 {spo2_mean:.1f}，当前 {spo2_last:.1f}），提示氧合仍受损。"
        )

    if "tachycardia" in flags:
        hr_recent = _window_points(vitals, "heart_rate", end=analysis_end, minutes=HR_PERSISTENT_MINUTES)
        hr_mean = _mean(hr_recent) or float("nan")
        hr_last = _window_last_value(vitals, "heart_rate", end=analysis_end, minutes=HR_PERSISTENT_MINUTES)
        sentences.append(
            f"过去 {HR_PERSISTENT_MINUTES} 分钟心率保持高于 {HR_TACHYCARDIA_THRESHOLD:.0f}（最近平均 {hr_mean:.0f}，当前 {hr_last:.0f}），提示持续心动过速。"
        )

    if "fever" in flags:
        temp_recent = _window_points(vitals, "temperature", end=analysis_end, minutes=TEMP_PERSISTENT_MINUTES)
        temp_mean = _mean(temp_recent) or float("nan")
        temp_last = _window_last_value(vitals, "temperature", end=analysis_end, minutes=TEMP_PERSISTENT_MINUTES)
        sentences.append(
            f"过去 {TEMP_PERSISTENT_MINUTES} 分钟体温维持在 {TEMP_FEVER_THRESHOLD:.1f}°C 以上（最近平均 {temp_mean:.1f}，当前 {temp_last:.1f}），提示发热趋势。"
        )

    if "oliguria" in flags:
        if urine_output_points:
            start = analysis_end - timedelta(minutes=OLIGURIA_LOOKBACK_MINUTES)
            recent = [p for p in urine_output_points if start <= p.timestamp <= analysis_end]
            values = [float(p.urine_output_ml_per_hour) for p in recent]
            first = values[0]
            last = values[-1]
            recent_mean = float(sum(values)) / len(values)
            sentences.append(
                f"过去 {OLIGURIA_LOOKBACK_MINUTES} 分钟尿量呈下降趋势（最近平均 {recent_mean:.1f} ml/h，当前 {last:.1f} ml/h）。"
            )

    if not sentences:
        return "过去一段时间未见主要生命体征持续异常；监测值整体稳定或处于可解释的波动范围。"

    # Keep it short: this is a bedside-level summary, not a long narrative.
    return " ".join(sentences)


def run_bedside_monitor(
    *,
    vitals: list[VitalPoint],
    urine_output_points: list[UrineOutputPoint] | None,
    analysis_end: datetime,
) -> dict[str, Any]:
    if analysis_end.tzinfo is None:
        analysis_end = analysis_end.replace(tzinfo=timezone.utc)

    abnormal_flags, abnormal_evidence = _detect_persistent_flags(vitals, analysis_end=analysis_end)

    urine_flags: list[str] = []
    urine_evidence: list[dict[str, Any]] = []
    urine_trend_labels: list[str] = []
    if urine_output_points:
        urine_flags, urine_evidence = _detect_oliguria(urine_output_points, analysis_end=analysis_end)
        if "urine_output_decreasing" in [e.get("flag") for e in urine_evidence if e.get("kind") == "trend"]:
            urine_trend_labels.append("urine_output_decreasing")

    abnormal_flags = abnormal_flags + urine_flags

    trend_labels, trend_evidence = _trend_labels(vitals, analysis_end=analysis_end)

    # Ensure urine trend label if present (rule output already includes evidence).
    if urine_trend_labels:
        trend_labels = list(dict.fromkeys(trend_labels + urine_trend_labels))

    all_evidence = abnormal_evidence + urine_evidence + trend_evidence

    urgency_level = _urgency_from_flags(abnormal_flags, vitals=vitals)
    current_status_summary = _build_summary(
        abnormal_flags,
        vitals=vitals,
        urine_output_points=urine_output_points,
        analysis_end=analysis_end,
    )

    return {
        "current_status_summary": current_status_summary,
        "abnormal_flags": abnormal_flags,
        "trend_labels": trend_labels,
        "evidence": all_evidence,
        "urgency_level": urgency_level,
    }

