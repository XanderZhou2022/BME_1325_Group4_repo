from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


def _severity_rank(sev: str) -> int:
    return {"critical": 0, "warning": 1, "low": 2}.get(sev.lower(), 3)


def _vitals_ok(vitals: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    blockers: list[str] = []
    hr = vitals.get("heart_rate") or vitals.get("hr")
    spo2 = vitals.get("spo2")
    map_val = vitals.get("mean_arterial_pressure") or vitals.get("map")
    if hr is not None:
        try:
            hr_i = int(hr)
            if 55 <= hr_i <= 110:
                reasons.append(f"心率 {hr_i} bpm，处于可转出观察范围")
            else:
                blockers.append(f"心率 {hr_i} bpm 尚未稳定，暂不宜转出 ICU")
        except (TypeError, ValueError):
            pass
    if spo2 is not None:
        try:
            spo2_i = int(float(spo2))
            if spo2_i >= 94:
                reasons.append(f"血氧 SpO₂ {spo2_i}% 达标")
            else:
                blockers.append(f"血氧 SpO₂ {spo2_i}% 偏低，需继续在 ICU 监护")
        except (TypeError, ValueError):
            pass
    if map_val is not None:
        try:
            map_i = int(float(map_val))
            if 65 <= map_i <= 105:
                reasons.append(f"平均动脉压 MAP {map_i} mmHg 稳定")
            else:
                blockers.append(f"平均动脉压 MAP {map_i} mmHg 波动较大")
        except (TypeError, ValueError):
            pass
    return len(blockers) == 0, reasons + blockers


def evaluate_transfer_out(conn: Connection, admission_id: str) -> dict[str, Any]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.admission_id, a.encounter_id, a.patient_id, a.bed_id, a.status,
                   a.primary_diagnosis, a.severity_on_admission, a.admission_reason,
                   p.name, p.gender, p.age
            FROM admissions a
            JOIN patients p ON p.patient_id = a.patient_id
            WHERE a.admission_id = %s
            """,
            (admission_id,),
        )
        adm = cur.fetchone()
        if not adm:
            return {"eligible": False, "blockers": ["未找到该 ICU 入院记录"], "reasons": [], "admission_id": admission_id}

        cur.execute(
            """
            SELECT care_phase, active_risks, active_problems, current_vitals, latest_interventions
            FROM patient_state_current
            WHERE admission_id = %s
            """,
            (admission_id,),
        )
        state = cur.fetchone() or {}

        cur.execute(
            """
            SELECT payload
            FROM agent_outputs
            WHERE admission_id = %s AND agent_name = 'clinical_summary'
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (admission_id,),
        )
        cs_row = cur.fetchone()
        clinical_payload = (cs_row or {}).get("payload") or {}

    reasons: list[str] = []
    blockers: list[str] = []

    if str(adm.get("status")) != "active":
        blockers.append(f"患者状态为 {adm.get('status')}，非在院 active，无法转出")

    phase = str(state.get("care_phase") or adm.get("severity_on_admission") or "unknown").lower()
    if phase == "critical":
        blockers.append("care_phase 仍为 critical，病情尚未脱离重症监护需求")
    elif phase == "stable":
        reasons.append("care_phase 已转为 stable，符合 ICU 转出基本条件")
    elif phase == "unstable":
        blockers.append("care_phase 为 unstable，仍需 ICU 密切监测")
    else:
        reasons.append(f"当前 care_phase={phase}，可结合体征与风险综合评估")

    active_risks = state.get("active_risks") or []
    critical_risks = [
        r for r in active_risks
        if isinstance(r, dict) and str(r.get("severity", "")).lower() == "critical"
    ]
    warning_risks = [
        r for r in active_risks
        if isinstance(r, dict) and str(r.get("severity", "")).lower() == "warning"
    ]
    if critical_risks:
        blockers.append(f"仍有 {len(critical_risks)} 项 critical 风险未解除")
        for r in critical_risks[:2]:
            reasons.append(f"待解除风险：{r.get('risk_type', '未知')}")
    elif not active_risks:
        reasons.append("active_risks 已清空，无未处理高危项")
    elif warning_risks and not critical_risks:
        reasons.append(f"剩余 {len(warning_risks)} 项 warning 级风险，可在普通病房继续监测")

    vitals = state.get("current_vitals") or {}
    if isinstance(vitals, dict) and vitals:
        vitals_ok, vital_msgs = _vitals_ok(vitals)
        for msg in vital_msgs:
            if "不宜" in msg or "偏低" in msg or "波动" in msg:
                blockers.append(msg)
            else:
                reasons.append(msg)
        if not vitals_ok and not any("体征" in b for b in blockers):
            blockers.append("最新生命体征尚未达到转出安全阈值")
    else:
        blockers.append("缺少最新生命体征，无法确认转出安全性")

    disposition = str(clinical_payload.get("disposition_recommendation") or clinical_payload.get("recommended_disposition") or "").lower()
    if "ward" in disposition or "step" in disposition or "普通" in disposition:
        reasons.append("clinical_summary 建议降级至普通病房继续治疗")
    summary_text = str(clinical_payload.get("summary_text") or clinical_payload.get("narrative") or "")
    if "稳定" in summary_text and phase != "critical":
        reasons.append("临床摘要点评病情趋于稳定")

    if str(adm.get("severity_on_admission")) == "critical" and phase == "stable" and not critical_risks:
        reasons.append("入院时 critical，经 ICU 治疗后病情已稳定，具备转出指征")

    eligible = len(blockers) == 0 and phase == "stable" and not critical_risks

    ctas = "L3"
    if critical_risks or phase == "critical":
        ctas = "L1"
    elif warning_risks or phase == "unstable":
        ctas = "L2"

    primary_reason = ""
    if eligible:
        primary_reason = reasons[0] if reasons else "ICU 病情稳定，转入普通病房继续康复与观察"
    else:
        primary_reason = blockers[0] if blockers else "尚未满足 ICU 转出条件"

    return {
        "admission_id": admission_id,
        "encounter_id": adm.get("encounter_id"),
        "patient_id": adm.get("patient_id"),
        "patient_name": adm.get("name"),
        "bed_id": adm.get("bed_id"),
        "eligible": eligible,
        "ctas_level": ctas,
        "care_phase": phase,
        "primary_reason": primary_reason,
        "reasons": reasons,
        "blockers": blockers,
        "active_risk_count": len(active_risks),
        "critical_risk_count": len(critical_risks),
        "recommended_action": "transfer_to_inpatient" if eligible else "remain_in_icu",
        "target_group": "groupD.inpatient",
    }
