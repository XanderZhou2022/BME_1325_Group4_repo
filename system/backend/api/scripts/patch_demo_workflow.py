"""Patch demo batch workflow: defer ward per-patient, run ward once at step end."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = Path(__file__).resolve().parents[1]


def patch_dispatcher() -> None:
    p = API / "app" / "orchestrator" / "event_dispatcher.py"
    t = p.read_text(encoding="utf-8")
    if "defer_ward_coordinator" in t:
        print("dispatcher: already patched")
        return
    t = t.replace(
        "    detail_id: str,\n) -> dict[str, Any]:",
        "    detail_id: str,\n    defer_ward_coordinator: bool = False,\n) -> dict[str, Any]:",
        1,
    )
    for old, new in [
        (
            '                run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "risk_change"})',
            '                if not defer_ward_coordinator:\n                    run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "risk_change"})',
        ),
        (
            '            run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "intervention_deterioration"})',
            '            if not defer_ward_coordinator:\n                run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "intervention_deterioration"})',
        ),
        (
            '                run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "lab_risk_change"})',
            '                if not defer_ward_coordinator:\n                    run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "lab_risk_change"})',
        ),
    ]:
        if old not in t:
            raise SystemExit(f"dispatcher missing block: {old[:60]}...")
        t = t.replace(old, new, 1)
    p.write_text(t, encoding="utf-8")
    print("dispatcher: patched")


def patch_action_requests() -> None:
    p = API / "app" / "services" / "agent_action_requests.py"
    t = p.read_text(encoding="utf-8")
    if "defer_ward_coordinator" in t:
        print("action_requests: already patched")
        return
    t = t.replace(
        "def _fulfill_lab_request(\n    conn: Connection,\n    request: dict[str, Any],\n    *,\n    sim_time: datetime,\n) -> dict[str, Any]:",
        "def _fulfill_lab_request(\n    conn: Connection,\n    request: dict[str, Any],\n    *,\n    sim_time: datetime,\n    defer_ward_coordinator: bool = False,\n) -> dict[str, Any]:",
        1,
    )
    t = t.replace(
        "        detail_id=write_result[\"detail_id\"],\n    )",
        "        detail_id=write_result[\"detail_id\"],\n        defer_ward_coordinator=defer_ward_coordinator,\n    )",
        1,
    )
    t = t.replace(
        "def fulfill_pending_requests_for_admission(\n    conn: Connection,\n    admission: dict[str, Any],\n    *,\n    sim_time: datetime,\n) -> list[dict[str, Any]]:",
        "def fulfill_pending_requests_for_admission(\n    conn: Connection,\n    admission: dict[str, Any],\n    *,\n    sim_time: datetime,\n    defer_ward_coordinator: bool = False,\n) -> list[dict[str, Any]]:",
        1,
    )
    t = t.replace(
        "            results.append(_fulfill_lab_request(conn, req, sim_time=sim_time))",
        "            results.append(_fulfill_lab_request(conn, req, sim_time=sim_time, defer_ward_coordinator=defer_ward_coordinator))",
        1,
    )
    p.write_text(t, encoding="utf-8")
    print("action_requests: patched")


def patch_demo_service() -> None:
    p = API / "app" / "demo" / "service.py"
    t = p.read_text(encoding="utf-8")

    if "from agents.ward_coordinator.schemas import WardCoordinatorEvaluateRequest" not in t:
        t = t.replace(
            "from app.services.agent_action_requests import fulfill_pending_requests_for_admission",
            "from app.services.agent_action_requests import fulfill_pending_requests_for_admission\n"
            "from agents.ward_coordinator.schemas import WardCoordinatorEvaluateRequest\n"
            "from agents.ward_coordinator.service import evaluate_ward\n"
            "from app.services.agent_observability import emit_agent_lifecycle_event",
            1,
        )

    if "_write_random_event" in t and "defer_ward_coordinator" not in t.split("_write_random_event")[1][:800]:
        t = t.replace(
            "def _write_random_event(conn: Connection, admission: dict[str, Any], sim_time: datetime, event_type: str) -> tuple[dict[str, Any], dict[str, Any]]:",
            "def _write_random_event(\n    conn: Connection,\n    admission: dict[str, Any],\n    sim_time: datetime,\n    event_type: str,\n    *,\n    defer_ward_coordinator: bool = False,\n) -> tuple[dict[str, Any], dict[str, Any]]:",
            1,
        )
        for et, call in [
            (
                'dispatch_event_chain(conn, admission_id=admission_id, event_type="vital_sign", detail_id=out["detail_id"])',
                'dispatch_event_chain(conn, admission_id=admission_id, event_type="vital_sign", detail_id=out["detail_id"], defer_ward_coordinator=defer_ward_coordinator)',
            ),
            (
                'dispatch_event_chain(conn, admission_id=admission_id, event_type="lab", detail_id=out["detail_id"])',
                'dispatch_event_chain(conn, admission_id=admission_id, event_type="lab", detail_id=out["detail_id"], defer_ward_coordinator=defer_ward_coordinator)',
            ),
            (
                'dispatch_event_chain(conn, admission_id=admission_id, event_type="intervention", detail_id=out["detail_id"])',
                'dispatch_event_chain(conn, admission_id=admission_id, event_type="intervention", detail_id=out["detail_id"], defer_ward_coordinator=defer_ward_coordinator)',
            ),
        ]:
            t = t.replace(call, call.replace("defer_ward_coordinator=defer_ward_coordinator", "defer_ward_coordinator=defer_ward_coordinator"), 1)
            if call not in t:
                old = call.split(", defer_ward")[0] + ")"
                t = t.replace(old, call, 1)

    if "_run_ward_coordinator_batch_isolated" not in t:
        ward_fn = '''

def _run_ward_coordinator_batch_isolated() -> dict[str, Any]:
    """Run ward_coordinator once for the whole ICU after all per-patient work in this step."""
    progress_emit({"type": "ward_batch_start", "message": "全病房统一运行 ward_coordinator…"})
    settings = get_settings()
    started = datetime.now(timezone.utc)
    with psycopg.connect(settings.pg_dsn) as conn:
        emit_agent_lifecycle_event(
            conn,
            admission_id="global",
            patient_id="global",
            bed_id="global",
            producer_agent="ward_coordinator",
            lifecycle="started",
            payload={"trigger": "demo_batch_tick"},
        )
        try:
            ward_out = evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10))
            fin = datetime.now(timezone.utc)
            emit_agent_lifecycle_event(
                conn,
                admission_id=str(ward_out.priority_queue[0].admission_id if ward_out.priority_queue else "global"),
                patient_id="global",
                bed_id="global",
                producer_agent="ward_coordinator",
                lifecycle="completed",
                payload={
                    "trigger": "demo_batch_tick",
                    "ward_load_indicator": ward_out.ward_load_indicator,
                    "queue_size": len(ward_out.priority_queue),
                },
            )
            progress_emit(
                {
                    "type": "ward_batch_done",
                    "status": "ok",
                    "duration_ms": int((fin - started).total_seconds() * 1000),
                    "queue_size": len(ward_out.priority_queue),
                }
            )
            return {
                "type": "ward_coordinator_batch",
                "status": "ok",
                "ward_load_indicator": ward_out.ward_load_indicator,
                "queue_size": len(ward_out.priority_queue),
                "anchor_admission_id": ward_out.priority_queue[0].admission_id if ward_out.priority_queue else None,
                "duration_ms": int((fin - started).total_seconds() * 1000),
            }
        except Exception as exc:
            fin = datetime.now(timezone.utc)
            emit_agent_lifecycle_event(
                conn,
                admission_id="global",
                patient_id="global",
                bed_id="global",
                producer_agent="ward_coordinator",
                lifecycle="failed",
                payload={"trigger": "demo_batch_tick", "error": str(exc)},
            )
            progress_emit(
                {
                    "type": "ward_batch_done",
                    "status": "error",
                    "duration_ms": int((fin - started).total_seconds() * 1000),
                    "error": str(exc),
                }
            )
            return {"type": "ward_coordinator_batch", "status": "error", "error": str(exc)}

'''
        t = t.replace("\ndef reset_demo_auto(conn: Connection)", ward_fn + "\ndef reset_demo_auto(conn: Connection)", 1)

    if "defer_ward_coordinator=True" not in t:
        t = t.replace(
            "            req, wr = _write_random_event(conn, admission, sim_time, event_type)",
            "            req, wr = _write_random_event(conn, admission, sim_time, event_type, defer_ward_coordinator=True)",
            1,
        )

    if "fulfill_pending_requests_for_admission(conn, admission, sim_time=sim_time)" in t:
        t = t.replace(
            "            results = fulfill_pending_requests_for_admission(conn, admission, sim_time=sim_time)",
            "            results = fulfill_pending_requests_for_admission(\n                conn, admission, sim_time=sim_time, defer_ward_coordinator=True\n            )",
            1,
        )

    # admissions batch marker
    if '"admissions_batch_complete"' not in t:
        t = t.replace(
            "        _set_state(conn, sim_after, step_index)\n\n    progress_emit(",
            '        if sub_events or na or discharged_ids:\n'
            '            sub_events.append({\n'
            '                "type": "admissions_batch_complete",\n'
            '                "admissions_created": na,\n'
            '                "discharges": len(discharged_ids),\n'
            '                "active_count": len(_active_admissions(conn)),\n'
            '            })\n\n'
            "        _set_state(conn, sim_after, step_index)\n\n    progress_emit(",
            1,
        )

    # parallel request fulfillment + ward at end
    old_block = """    request_fulfillment: list[dict[str, Any]] = []
    for adm in active_clinical:
        request_fulfillment.extend(_fulfill_pending_agent_requests_isolated(adm, sim_after))
    if request_fulfillment:
        sub_events.extend(request_fulfillment)

    random.shuffle(active_clinical)
    clinical_jobs = [
        (adm, sim_after, random.choice(["vital_sign", "lab", "intervention"])) for adm in active_clinical
    ]

    progress_emit(
        {
            "type": "phase",
            "message": f"为 {len(active_clinical)} 位在院患者并行生成临床事件并运行 Agent 链…",
        }
    )

    captured_emit = get_progress_emit()

    def _clinical_job(job: tuple[dict[str, Any], datetime, str]) -> dict[str, Any]:
        adm, sim_t, et = job
        if captured_emit:
            with progress_scope(captured_emit):
                return _run_clinical_event_isolated(adm, sim_t, et)
        return _run_clinical_event_isolated(adm, sim_t, et)

    sub_events.extend(parallel_map(clinical_jobs, _clinical_job))"""

    new_block = """    progress_emit(
        {
            "type": "phase",
            "message": f"阶段 2/3：并行履约 {len(active_clinical)} 位患者的 Agent 待办（检查/会诊）…",
        }
    )
    request_jobs = [(adm, sim_after) for adm in active_clinical]
    captured_emit_req = get_progress_emit()

    def _request_job(job: tuple[dict[str, Any], datetime]) -> list[dict[str, Any]]:
        adm, sim_t = job
        if captured_emit_req:
            with progress_scope(captured_emit_req):
                return _fulfill_pending_agent_requests_isolated(adm, sim_t)
        return _fulfill_pending_agent_requests_isolated(adm, sim_t)

    request_fulfillment: list[dict[str, Any]] = []
    for chunk in parallel_map(request_jobs, _request_job):
        if isinstance(chunk, list):
            request_fulfillment.extend(chunk)
    if request_fulfillment:
        sub_events.extend(request_fulfillment)

    random.shuffle(active_clinical)
    clinical_jobs = [
        (adm, sim_after, random.choice(["vital_sign", "lab", "intervention"])) for adm in active_clinical
    ]

    progress_emit(
        {
            "type": "phase",
            "message": f"阶段 3/3：为 {len(active_clinical)} 位在院患者并行写入临床事件并运行患者级 Agent 链…",
        }
    )

    captured_emit = get_progress_emit()

    def _clinical_job(job: tuple[dict[str, Any], datetime, str]) -> dict[str, Any]:
        adm, sim_t, et = job
        if captured_emit:
            with progress_scope(captured_emit):
                return _run_clinical_event_isolated(adm, sim_t, et)
        return _run_clinical_event_isolated(adm, sim_t, et)

    sub_events.extend(parallel_map(clinical_jobs, _clinical_job))

    progress_emit({"type": "phase", "message": "阶段 4/4：全病房统一运行 ward_coordinator…"})
    ward_sub = _run_ward_coordinator_batch_isolated()
    sub_events.append(ward_sub)"""

    if old_block in t:
        t = t.replace(old_block, new_block, 1)
    elif "阶段 4/4" in t:
        print("demo service: workflow block already patched")
    else:
        raise SystemExit("demo service: could not find workflow block")

    # docstring
    t = t.replace(
        """    - 0–2 discharges among active demo patients
    - 0–2 admissions into empty demo beds
    - For **every** active demo patient after those mutations: one random clinical event
      (vital_sign / lab / intervention), each running the normal dispatch_event_chain.
    Ward capacity is capped at **DEMO_MAX_BEDS** (5) demo beds (`demo_b_01` … `demo_b_05`).""",
        """    1. Batch discharge/admit (all admissions for this tick finish before any agents run).
    2. Parallel fulfill pending lab/MDT requests per patient (patient-level agents only).
    3. Parallel clinical event + per-patient agent chain (ward_coordinator deferred).
    4. Single ward_coordinator evaluation for the whole ICU.
    Ward capacity is capped at **DEMO_MAX_BEDS** (5) demo beds (`demo_b_01` … `demo_b_05`).""",
        1,
    )

    p.write_text(t, encoding="utf-8")
    print("demo service: patched")


def patch_frontend() -> None:
    for rel, patches in [
        (
            "frontend/src/showcase/autoDemoProgress.ts",
            [
                (
                    '    case "phase":\n      return `${prefix}${String(ev.message ?? "处理中…")}`;',
                    '    case "ward_batch_start":\n      return `${prefix}${String(ev.message ?? "全病房 Agent 批次开始…")}`;\n'
                    '    case "ward_batch_done": {\n'
                    '      const st = ev.status === "error" ? "失败" : "完成";\n'
                    '      return `${prefix}ward_coordinator 全病房批次${st}，队列 ${ev.queue_size ?? "—"} 人，${ev.duration_ms ?? "?"}ms`;\n'
                    "    }\n"
                    '    case "phase":\n      return `${prefix}${String(ev.message ?? "处理中…")}`;',
                ),
                (
                    '  if (ev.type?.startsWith("agent_") || ev.type === "patient_clinical_start") return "agent";',
                    '  if (ev.type === "ward_batch_start" || ev.type === "ward_batch_done") return "agent";',
                    '  if (ev.type?.startsWith("agent_") || ev.type === "patient_clinical_start") return "agent";',
                ),
            ],
        ),
        (
            "frontend/src/showcase/autoDemoNarrative.ts",
            [
                (
                    '    lines.push(`Ward batch tick: ${n} sub-event(s). Anchor admission for risk snapshot: ${aid || "N/A"}.`);',
                    '    lines.push(`Ward batch tick (出入院 → 并行患者 → 全病房 Agent): ${n} sub-event(s). Anchor: ${aid || "N/A"}.`);',
                ),
                (
                    '      lines.push(`Mix: ${Object.entries(types)',
                    '      if (types["ward_coordinator_batch"]) {\n'
                    '        lines.push("Ward coordinator ran once for the whole ICU after all patients were processed.");\n'
                    "      }\n"
                    '      if (types["admissions_batch_complete"]) {\n'
                    '        lines.push("All admissions/discharges for this step completed before patient agents.");\n'
                    "      }\n"
                    '      lines.push(`Mix: ${Object.entries(types)',
                ),
            ],
        ),
        (
            "frontend/src/showcase/autoDemoStepEvents.ts",
            [
                (
                    '    if (type === "admission_discharge") {',
                    '    if (type === "admissions_batch_complete") {\n'
                    '      const created = Number((sub.write_result as JsonObj)?.admissions_created ?? (sub as JsonObj).admissions_created ?? 0);\n'
                    '      const dis = Number((sub as JsonObj).discharges ?? 0);\n'
                    '      items.push({\n'
                    '        index: items.length,\n'
                    '        type,\n'
                    '        admission_id: "",\n'
                    '        bed_id: "",\n'
                    '        title: "出入院批次完成",\n'
                    '        details: [`新收治 ${created} 人`, `出院 ${dis} 人`, "随后才启动患者级 Agent"],\n'
                    '      });\n'
                    '      continue;\n'
                    '    }\n'
                    '    if (type === "ward_coordinator_batch") {\n'
                    '      items.push({\n'
                    '        index: items.length,\n'
                    '        type,\n'
                    '        admission_id: String((sub as JsonObj).anchor_admission_id ?? ""),\n'
                    '        bed_id: "",\n'
                    '        title: "全病房 ward_coordinator",\n'
                    '        details: [\n'
                    '          `状态: ${String((sub as JsonObj).status ?? "—")}`,\n'
                    '          `队列: ${String((sub as JsonObj).queue_size ?? "—")} 人`,\n'
                    '          `负荷: ${String((sub as JsonObj).ward_load_indicator ?? "—")}`,\n'
                    '        ],\n'
                    '      });\n'
                    '      continue;\n'
                    '    }\n'
                    '    if (type === "admission_discharge") {',
                ),
            ],
        ),
    ]:
        p = ROOT / "system" / rel.replace("/", "\\") if False else ROOT / "system" / rel
        p = ROOT / "system" / rel
        if not p.exists():
            print(f"skip missing {p}")
            continue
        t = p.read_text(encoding="utf-8")
        for old, new in patches:
            if old in t:
                t = t.replace(old, new, 1)
            elif new.split("\n")[0] in t or "ward_coordinator_batch" in t:
                print(f"{rel}: already has patch fragment")
            else:
                raise SystemExit(f"{rel}: missing:\n{old[:80]}")
        p.write_text(t, encoding="utf-8")
        print(f"{rel}: patched")


if __name__ == "__main__":
    patch_dispatcher()
    patch_action_requests()
    patch_demo_service()
    patch_frontend()
    print("done")
