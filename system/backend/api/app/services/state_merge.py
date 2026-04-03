from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from app.schemas import CarePhase


def json_or_obj(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def infer_care_phase_from_vitals(vitals: dict[str, Any]) -> CarePhase:
    map_val = vitals.get("mean_arterial_pressure")
    spo2 = vitals.get("spo2")
    try:
        if map_val is not None and float(map_val) < 65:
            return "critical"
        if spo2 is not None and float(spo2) < 88:
            return "critical"
        if map_val is not None and float(map_val) < 70:
            return "unstable"
        if spo2 is not None and float(spo2) < 92:
            return "unstable"
    except (TypeError, ValueError):
        pass
    return "stable"


def merge_vitals_into_current(
    existing_vitals: dict[str, Any],
    new_vitals: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing_vitals)
    for k, v in new_vitals.items():
        if v is None:
            continue
        merged[k] = float(v) if isinstance(v, Decimal) else v
    return merged


def merge_lab_into_problems(
    existing: list[Any],
    lab_type: str,
    abnormal_flag: str,
) -> list[Any]:
    problems = list(existing) if isinstance(existing, list) else []
    tag = f"lab_{lab_type}_{abnormal_flag}"
    if tag not in problems and abnormal_flag != "normal":
        problems.append(tag)
    return problems


def merge_intervention_into_latest(
    existing: list[Any],
    item: dict[str, Any],
    max_items: int = 10,
) -> list[Any]:
    latest = list(existing) if isinstance(existing, list) else []
    latest.insert(0, item)
    return latest[:max_items]
