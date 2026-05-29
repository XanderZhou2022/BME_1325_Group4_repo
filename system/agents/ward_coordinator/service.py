from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id
from knowledge.retriever import retrieve_cards
from llm.client import generate_structured_output
from llm.prompt_loader import load_prompt_template
from llm.schemas import WardCoordinatorLLMOutput
from .schemas import ICUStatus, MergedAlertGroup, WardCoordinatorEvaluateRequest, WardCoordinatorEvaluateResponse, WardPriorityItem

RISK_SCORE = {"low": 1, "moderate": 2, "warning": 2, "high": 4, "critical": 6}
WARD_REMINDER = [
    "Do not use this queue as automatic bed allocation.",
    "Do not use this queue as ICU admission or discharge decision.",
    "Clinician review is required.",
]


def _ensure_ward_tables(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ward_priority_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                generated_at TIMESTAMPTZ NOT NULL,
                occupied_beds INT,
                critical_patients INT,
                high_risk_patients INT,
                new_deteriorations INT,
                priority_queue JSONB NOT NULL DEFAULT '[]'::jsonb,
                merged_alerts JSONB NOT NULL DEFAULT '[]'::jsonb,
                ward_summary TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ward_priority_events (
                event_id TEXT PRIMARY KEY,
                generated_at TIMESTAMPTZ NOT NULL,
                bed_id TEXT,
                patient_id TEXT,
                priority_level TEXT,
                priority_score INT,
                reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_risk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )


def _latest_agent_output(conn: Connection, admission_id: str, agent_name: str) -> dict[str, Any]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT output_id, generated_at, payload
            FROM agent_outputs
            WHERE admission_id = %s AND agent_name = %s
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (admission_id, agent_name),
        )
        row = cur.fetchone()
    if not row:
        return {}
    return {"output_id": row["output_id"], "generated_at": row["generated_at"], "payload": row["payload"] or {}}


def _priority_level(score: int) -> str:
    if score >= 9:
        return "immediate"
    if score >= 6:
        return "urgent"
    if score >= 3:
        return "watch"
    return "routine"


def _suggested_attention(level: str) -> str:
    return {
        "immediate": "immediate bedside review",
        "urgent": "urgent human review",
        "watch": "close watch in next round",
        "routine": "routine monitoring",
    }.get(level, "routine monitoring")


def _topic_from_reason(reason: str) -> str:
    low = reason.lower()
    if "shock" in low or "hypotension" in low:
        return "shock_related_alerts"
    if "resp" in low or "spo2" in low or "oxygen" in low:
        return "respiratory_related_alerts"
    if "aki" in low or "renal" in low or "creatinine" in low:
        return "aki_related_alerts"
    return "general_risk_alerts"


def _compute_priority_score(
    *,
    overall_risk: str,
    active_risk_count: int,
    trajectory: str,
    is_new_deterioration: bool,
    response_label: str,
    has_unresolved_critical_issue: bool,
) -> tuple[int, list[str]]:
    score = RISK_SCORE.get(overall_risk, 1)
    reasons = [f"risk level={overall_risk}"]
    if active_risk_count > 1:
        bonus = active_risk_count - 1
        score += bonus
        reasons.append(f"multiple active risks +{bonus}")
    if trajectory == "worsening":
        score += 2
        reasons.append("worsening trajectory +2")
    if is_new_deterioration:
        score += 2
        reasons.append("new deterioration within 1h +2")
    if response_label == "deteriorating_despite_intervention":
        score += 3
        reasons.append("deteriorating despite intervention +3")
    elif response_label == "non_responsive":
        score += 2
        reasons.append("non-responsive intervention +2")
    if has_unresolved_critical_issue:
        score += 2
        reasons.append("unresolved critical issue +2")
    return score, reasons


def _rule_based_ward_rationale(
    *,
    item: WardPriorityItem,
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    reason_text = "; ".join(item.reason[:5]) if item.reason else "structured ward priority scoring"
    risk_text = ", ".join(item.active_risks[:5]) if item.active_risks else "no active risk labels"
    return {
        "bed_id": item.bed_id,
        "priority_rank": item.rank,
        "rule_based_priority_score": item.priority_score,
        "rationale": (
            f"Rank {item.rank} is based on a {item.priority_level} priority score of {item.priority_score}. "
            f"Contributing reasons: {reason_text}. Active risk context: {risk_text}. Clinician review is required."
        ),
        "supporting_risk_types": item.active_risks,
        "supporting_card_ids": [str(card.get("card_id")) for card in cards if card.get("card_id")][:5],
        "human_review_required": True,
    }


def _enrich_ward_queue(
    *,
    queue: list[WardPriorityItem],
    generated_at: datetime,
    icu_status: ICUStatus,
    ward_load_indicator: str,
    merged_alerts: list[MergedAlertGroup],
    pending_actions: list[str],
    llm_enabled: bool | None = None,
) -> dict[str, Any]:
    risk_types = list(dict.fromkeys(rt for item in queue for rt in item.active_risks))
    query = " ".join(risk_types + [reason for item in queue for reason in item.reason])
    retrieval = retrieve_cards(
        "ward_coordinator",
        {"ward_id": "icu_01"},
        risk_types=risk_types,
        trigger_signals=query.split(),
        query=query,
    )
    cards = retrieval["retrieved_cards"]
    prompt = load_prompt_template("ward_coordinator_rationale_prompt.md")
    input_payload = {
        "agent_name": "ward_coordinator",
        "prompt_template_name": "ward_coordinator_rationale_prompt.md",
        "ward_id": "icu_01",
        "generated_at": generated_at.isoformat(),
        "icu_status": icu_status.model_dump(mode="json"),
        "ward_load_indicator": ward_load_indicator,
        "merged_alerts": [m.model_dump(mode="json") for m in merged_alerts],
        "pending_actions": pending_actions,
        "priority_queue": [
            {
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "bed_id": item.bed_id,
                "care_phase": item.care_phase,
                "priority_rank": item.rank,
                "priority_level": item.priority_level,
                "rule_based_priority_score": item.priority_score,
                "active_risks": item.active_risks,
                "reasons": item.reason,
                "summary_hint": item.summary_hint,
                "suggested_attention": item.suggested_attention,
            }
            for item in queue
        ],
        "retrieved_knowledge_cards": cards,
        "requested_sections": [
            "概述 ICU 内所有患者整体情况",
            "解释当前排序原因",
            "说明参考了哪些规则/知识卡",
            "列出下一步计划",
            "指出重点关注对象及原因",
        ],
        "global_forbidden_use": ["automatic_bed_assignment", "icu_admission_or_discharge_decision", "withholding_treatment_decision", "treatment_recommendation"],
    }
    result = generate_structured_output(
        "ward_coordinator_priority_rationale",
        prompt,
        input_payload,
        WardCoordinatorLLMOutput,
        llm_enabled=llm_enabled,
    )
    output = result.output.model_dump(mode="json")
    rationales = {str(item["bed_id"]): item for item in output.get("priority_rationales", [])}
    immediate = [item.bed_id for item in queue if item.priority_level == "immediate"]
    urgent = [item.bed_id for item in queue if item.priority_level == "urgent"]
    global_watch_items = list(output.get("global_watch_items") or [])
    if immediate:
        global_watch_items.append("Immediate-priority beds require clinician review: " + ", ".join(immediate[:5]) + ".")
    if urgent:
        global_watch_items.append("Urgent-priority beds should remain visible in the next ward review: " + ", ".join(urgent[:5]) + ".")
    if not global_watch_items:
        global_watch_items.append("Review the priority queue with routine clinical judgment.")
    for item in queue:
        rat = rationales.get(item.bed_id, {})
        item.rationale = rat.get("rationale") or "This bed is ranked by structured rule scoring and requires clinician review."
        item.knowledge_background = cards
        item.human_review_required = True
    return {
        "knowledge_context": cards,
        "ward_overview": output.get("ward_overview") or "",
        "priority_reasoning": output.get("priority_reasoning") or "",
        "references_used": output.get("references_used") or [str(c.get("title") or c.get("card_id")) for c in cards[:5]],
        "next_step_plan": output.get("next_step_plan") or [],
        "focus_points": output.get("focus_points") or global_watch_items,
        "global_watch_items": global_watch_items,
        "review_reminders": output.get("review_reminders") or ["Ward Coordinator output requires clinician review."],
        "forbidden_use_reminder": output.get("forbidden_use_reminder") or WARD_REMINDER,
        "knowledge_used": bool(cards),
        "llm_used": result.llm_used,
        "fallback_used": result.fallback_used,
        "audit_log_id": result.audit_log_id,
        "human_review_required": True,
    }


def evaluate_ward(conn: Connection, req: WardCoordinatorEvaluateRequest) -> WardCoordinatorEvaluateResponse:
    _ensure_ward_tables(conn)
    conn.row_factory = dict_row
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.admission_id, a.patient_id, a.bed_id, COALESCE(ps.care_phase, a.severity_on_admission) AS care_phase,
                   COALESCE(ps.active_risks, '[]'::jsonb) AS active_risks
            FROM admissions a
            LEFT JOIN patient_state_current ps ON ps.admission_id = a.admission_id
            WHERE a.status = 'active'
            ORDER BY a.admit_time DESC
            """
        )
        rows = cur.fetchall()

    queue: list[WardPriorityItem] = []
    score_debug: list[dict[str, Any]] = []
    alert_summary = {"critical": 0, "warning": 0, "info": 0}
    merged_map: dict[str, set[str]] = {}
    new_deteriorations = 0
    high_risk_patients = 0
    critical_patients = 0

    for r in rows:
        risks = r["active_risks"] or []
        admission_id = str(r["admission_id"])
        risk_out = _latest_agent_output(conn, admission_id, "risk_sentinel")
        cs_out = _latest_agent_output(conn, admission_id, "clinical_summary")
        mem_out = _latest_agent_output(conn, admission_id, "patient_memory")
        intv_out = _latest_agent_output(conn, admission_id, "intervention_tracker")
        bedside_out = _latest_agent_output(conn, admission_id, "bedside_monitor")

        risk_payload = risk_out.get("payload") or {}
        cs_payload = cs_out.get("payload") or {}
        mem_payload = mem_out.get("payload") or {}
        intv_payload = intv_out.get("payload") or {}
        bedside_payload = bedside_out.get("payload") or {}

        overall_risk = str(risk_payload.get("overall_risk_level") or risk_payload.get("escalation_level") or "low").lower()
        if overall_risk not in RISK_SCORE:
            overall_risk = "low"

        source_risk_ids: list[str] = []
        source_event_ids: list[str] = [x for x in [risk_out.get("output_id"), cs_out.get("output_id"), mem_out.get("output_id"), intv_out.get("output_id"), bedside_out.get("output_id")] if x]

        active_risk_items = risk_payload.get("active_risks") or risk_payload.get("risks") or risks
        active_risk_names = [
            str((risk_item or {}).get("risk_type"))
            for risk_item in active_risk_items
            if isinstance(risk_item, dict) and (risk_item or {}).get("risk_type")
        ] if isinstance(active_risk_items, list) else []
        active_risk_count = len(active_risk_items) if isinstance(active_risk_items, list) else 0
        if overall_risk in ("high", "critical"):
            high_risk_patients += 1
        if overall_risk == "critical":
            critical_patients += 1
        for risk_item in active_risk_items if isinstance(active_risk_items, list) else []:
            rid = str((risk_item or {}).get("risk_id") or "")
            if rid:
                source_risk_ids.append(rid)
            topic_seed = str((risk_item or {}).get("risk_type") or "")
            if topic_seed:
                merged_map.setdefault(_topic_from_reason(topic_seed), set()).add(str(r["bed_id"]))

        risk_generated_at = risk_out.get("generated_at")
        is_new_deterioration = bool(isinstance(risk_generated_at, datetime) and risk_generated_at >= now - timedelta(hours=1) and overall_risk in ("high", "critical"))
        if is_new_deterioration:
            new_deteriorations += 1
        response = str(intv_payload.get("response_label") or intv_payload.get("response_assessment") or "").lower()
        trajectory = str(risk_payload.get("trajectory") or "").lower()
        unresolved = mem_payload.get("unresolved_issues") or []
        unresolved_critical = bool(isinstance(unresolved, list) and any("critical" in str(u).lower() or "shock" in str(u).lower() for u in unresolved))
        score, reasons = _compute_priority_score(
            overall_risk=overall_risk,
            active_risk_count=active_risk_count,
            trajectory=trajectory,
            is_new_deterioration=is_new_deterioration,
            response_label=response,
            has_unresolved_critical_issue=unresolved_critical,
        )

        bedside_urgency = str(bedside_payload.get("urgency_level") or "info")
        if bedside_urgency == "critical":
            alert_summary["critical"] += 1
        elif bedside_urgency == "warning":
            alert_summary["warning"] += 1
        else:
            alert_summary["info"] += 1

        for rsn in reasons:
            merged_map.setdefault(_topic_from_reason(rsn), set()).add(str(r["bed_id"]))

        phase = str(r["care_phase"] or "stable")
        level = _priority_level(score)
        queue.append(
            WardPriorityItem(
                admission_id=admission_id,
                patient_id=str(r["patient_id"]),
                bed_id=str(r["bed_id"]),
                care_phase=phase,
                priority_score=score,
                priority_level=level,  # type: ignore[arg-type]
                reason=reasons,
                suggested_attention=_suggested_attention(level),
                source_risk_ids=source_risk_ids,
                source_event_ids=source_event_ids,
                summary_hint=str(cs_payload.get("one_line_status") or ""),
                active_risks=active_risk_names,
            )
        )
        score_debug.append({"admission_id": admission_id, "score": score, "reasons": reasons})

    queue.sort(key=lambda x: x.priority_score, reverse=True)
    for idx, item in enumerate(queue, start=1):
        item.rank = idx
    top = queue[: req.top_k]

    merged_alerts = [
        MergedAlertGroup(alert_group=group, beds=sorted(list(beds)), count=len(beds))
        for group, beds in merged_map.items()
        if beds
    ]

    if alert_summary["critical"] >= 5:
        load = "high"
    elif alert_summary["critical"] >= 2 or alert_summary["warning"] >= 5:
        load = "medium"
    else:
        load = "normal"

    pending = [f"review_{item.bed_id}" for item in top if item.priority_level in ("urgent", "immediate")][:3]
    icu_status = ICUStatus(
        occupied_beds=len(rows),
        critical_patients=critical_patients,
        high_risk_patients=high_risk_patients,
        new_deteriorations=new_deteriorations,
    )
    ward_meta = _enrich_ward_queue(
        queue=top,
        generated_at=now,
        icu_status=icu_status,
        ward_load_indicator=load,
        merged_alerts=merged_alerts,
        pending_actions=pending,
    )
    top_line = f"Top priority bed {top[0].bed_id}" if top else "No active bed priority"
    ward_summary = (
        f"ICU has {icu_status.critical_patients} critical and {icu_status.high_risk_patients} high-risk patients; "
        f"new deteriorations in last hour: {icu_status.new_deteriorations}. {top_line}."
    )
    out = WardCoordinatorEvaluateResponse(
        generated_at=now,
        active_admission_count=len(rows),
        icu_status=icu_status,
        priority_queue=top,
        merged_alerts=merged_alerts,
        ward_summary=ward_summary,
        pending_actions=pending,
        ward_load_indicator=load,
        alert_storm_summary=alert_summary,
        debug_scoring=score_debug,
        ward_overview=ward_meta["ward_overview"],
        priority_reasoning=ward_meta["priority_reasoning"],
        references_used=ward_meta["references_used"],
        next_step_plan=ward_meta["next_step_plan"],
        focus_points=ward_meta["focus_points"],
        global_watch_items=ward_meta["global_watch_items"],
        review_reminders=ward_meta["review_reminders"],
        forbidden_use_reminder=ward_meta["forbidden_use_reminder"],
        knowledge_used=ward_meta["knowledge_used"],
        llm_used=ward_meta["llm_used"],
        fallback_used=ward_meta["fallback_used"],
        audit_log_id=ward_meta["audit_log_id"],
        human_review_required=True,
    )
    anchor_admission = top[0].admission_id if top else None
    anchor_patient = top[0].patient_id if top else None
    anchor_bed = top[0].bed_id if top else None
    if anchor_admission and anchor_patient and anchor_bed:
        payload = {
            "scope": "global",
            "active_admission_count": out.active_admission_count,
            "icu_status": out.icu_status.model_dump(mode="json"),
            "priority_queue": [item.model_dump(mode="json") for item in out.priority_queue],
            "merged_alerts": [m.model_dump(mode="json") for m in out.merged_alerts],
            "ward_summary": out.ward_summary,
            "pending_actions": out.pending_actions,
            "ward_load_indicator": out.ward_load_indicator,
            "alert_storm_summary": out.alert_storm_summary,
            "generated_at": out.generated_at.isoformat(),
            "ward_id": out.ward_id,
            "ward_overview": out.ward_overview,
            "priority_reasoning": out.priority_reasoning,
            "references_used": out.references_used,
            "next_step_plan": out.next_step_plan,
            "focus_points": out.focus_points,
            "global_watch_items": out.global_watch_items,
            "review_reminders": out.review_reminders,
            "forbidden_use_reminder": out.forbidden_use_reminder,
            "knowledge_used": out.knowledge_used,
            "llm_used": out.llm_used,
            "fallback_used": out.fallback_used,
            "audit_log_id": out.audit_log_id,
            "human_review_required": True,
        }
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                    VALUES ('ward_coordinator', '["risk_assessment_ready","clinical_summary_ready","patient_memory_ready","intervention_tracker_ready","bedside_analysis_ready","admission_state_change"]'::jsonb, 'ward_coordinator_ready', 'v1.1', TRUE)
                    ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                    """
                )
                cur.execute(
                    """
                    INSERT INTO agent_events (
                        event_id, admission_id, patient_id, bed_id, producer_agent,
                        event_type, schema_version, produced_at, output_id, payload
                    ) VALUES (%s, %s, %s, %s, 'ward_coordinator', 'ward_coordinator.started', 'v1.1', %s, NULL, %s::jsonb)
                    """,
                    (new_id("aevt"), anchor_admission, anchor_patient, anchor_bed, out.generated_at, Json({"top_k": req.top_k, "active_admission_count": len(rows)})),
                )
                output_id = new_id("out")
                event_id = new_id("aevt")
                cur.execute(
                    """
                    INSERT INTO agent_outputs (
                        output_id, admission_id, patient_id, bed_id, agent_name,
                        schema_version, output_type, generated_at, payload
                    ) VALUES (%s, %s, %s, %s, 'ward_coordinator', 'v1.1', 'ward_coordinator_ready', %s, %s::jsonb)
                    """,
                    (output_id, anchor_admission, anchor_patient, anchor_bed, out.generated_at, Json(payload)),
                )
                cur.execute(
                    """
                    INSERT INTO agent_events (
                        event_id, admission_id, patient_id, bed_id, producer_agent,
                        event_type, schema_version, produced_at, output_id, payload
                    ) VALUES (%s, %s, %s, %s, 'ward_coordinator', 'ward_coordinator_ready', 'v1.1', %s, %s, %s::jsonb)
                    """,
                    (event_id, anchor_admission, anchor_patient, anchor_bed, out.generated_at, output_id, Json(payload)),
                )
                cur.execute(
                    """
                    INSERT INTO ward_priority_snapshots (
                        snapshot_id, generated_at, occupied_beds, critical_patients, high_risk_patients, new_deteriorations,
                        priority_queue, merged_alerts, ward_summary
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                    """,
                    (
                        new_id("wsnp"),
                        out.generated_at,
                        out.icu_status.occupied_beds,
                        out.icu_status.critical_patients,
                        out.icu_status.high_risk_patients,
                        out.icu_status.new_deteriorations,
                        Json([item.model_dump(mode="json") for item in out.priority_queue]),
                        Json([m.model_dump(mode="json") for m in out.merged_alerts]),
                        out.ward_summary,
                    ),
                )
                for item in out.priority_queue:
                    cur.execute(
                        """
                        INSERT INTO ward_priority_events (
                            event_id, generated_at, bed_id, patient_id, priority_level, priority_score, reasons, source_risk_ids
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        """,
                        (
                            new_id("wevt"),
                            out.generated_at,
                            item.bed_id,
                            item.patient_id,
                            item.priority_level,
                            item.priority_score,
                            Json(item.reason),
                            Json(item.source_risk_ids),
                        ),
                    )
                cur.execute(
                    """
                    INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                    VALUES (%s, %s, 'agent', 'ward_coordinator', 'run_agent', 'ward', %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        new_id("log"),
                        out.generated_at,
                        anchor_admission,
                        Json({"top_k": req.top_k, "inputs": ["risk_sentinel", "clinical_summary", "patient_memory", "intervention_tracker", "bedside_monitor"]}),
                        Json({
                            "queue_size": len(out.priority_queue),
                            "critical_patients": out.icu_status.critical_patients,
                            "output_id": output_id,
                            "retrieved_card_ids": [c["card_id"] for c in ward_meta["knowledge_context"]],
                            "llm_audit_log_id": ward_meta["audit_log_id"],
                        }),
                    ),
                )
    return out
