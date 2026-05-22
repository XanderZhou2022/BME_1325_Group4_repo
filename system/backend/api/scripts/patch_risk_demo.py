"""One-off patch script for risk_sentinel + demo service."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

risk_path = ROOT / "agents" / "risk_sentinel" / "service.py"
text = risk_path.read_text(encoding="utf-8")
if "derive_requests_from_risk_sentinel" not in text:
    text = text.replace(
        "from app.services.ids import new_id",
        "from app.services.agent_action_requests import (\n"
        "    derive_requests_from_risk_sentinel,\n"
        "    register_agent_action_requests,\n"
        ")\n"
        "from app.services.ids import new_id\n"
        "from types import SimpleNamespace",
        1,
    )
    old = (
        '            output_id = new_id("out")\n'
        '            event_id = new_id("aevt")\n'
        "            cur.execute(\n"
        '                """\n'
        "                INSERT INTO agent_outputs (\n"
        "                    output_id, admission_id, patient_id, bed_id, agent_name,\n"
        "                    schema_version, output_type, generated_at, payload\n"
        "                ) VALUES (%s, %s, %s, %s, 'risk_sentinel', 'v1', 'risk_assessment_ready', %s, %s::jsonb)\n"
        '                """\n'
        "                (output_id, req.admission_id, patient_id, bed_id, datetime.now(timezone.utc), Json(payload)),\n"
        "            )"
    )
    new = (
        "            if risks:\n"
        '                _highest = max(risks, key=lambda r: RISK_ORDER[str(r["risk_level"])])\n'
        '                _escalation = LEVEL_TO_ESCALATION[str(_highest["risk_level"])]\n'
        "            else:\n"
        '                _escalation = "info"\n'
        "            _risk_stub = SimpleNamespace(\n"
        "                escalation_level=_escalation,\n"
        "                overall_risk_level=overall_risk_level,\n"
        '                recommended_next_attention=payload["recommended_next_attention"],\n'
        '                new_or_worsening_flags=payload["new_or_worsening_flags"],\n'
        "            )\n"
        "            _action_specs = derive_requests_from_risk_sentinel(_risk_stub)\n"
        '            output_id = new_id("out")\n'
        "            _action_ids = register_agent_action_requests(\n"
        "                conn,\n"
        "                admission_id=req.admission_id,\n"
        "                patient_id=patient_id,\n"
        "                bed_id=bed_id,\n"
        '                requested_by_agent="risk_sentinel",\n'
        "                specs=_action_specs,\n"
        "                source_output_id=output_id,\n"
        "            )\n"
        '            payload["action_requests"] = [\n'
        '                {"request_id": rid, **spec}\n'
        "                for rid, spec in zip(_action_ids, _action_specs[: len(_action_ids)])\n"
        "            ]\n"
        '            event_id = new_id("aevt")\n'
        "            cur.execute(\n"
        '                """\n'
        "                INSERT INTO agent_outputs (\n"
        "                    output_id, admission_id, patient_id, bed_id, agent_name,\n"
        "                    schema_version, output_type, generated_at, payload\n"
        "                ) VALUES (%s, %s, %s, %s, 'risk_sentinel', 'v1', 'risk_assessment_ready', %s, %s::jsonb)\n"
        '                """\n'
        "                (output_id, req.admission_id, patient_id, bed_id, datetime.now(timezone.utc), Json(payload)),\n"
        "            )"
    )
    if old not in text:
        raise RuntimeError("risk_sentinel anchor not found")
    text = text.replace(old, new, 1)
    risk_path.write_text(text, encoding="utf-8")
    print("patched risk_sentinel")

demo_path = ROOT / "backend" / "api" / "app" / "demo" / "service.py"
demo = demo_path.read_text(encoding="utf-8")
if "fulfill_pending_requests_for_admission" not in demo:
    demo = demo.replace(
        "from app.orchestrator.event_dispatcher import dispatch_event_chain",
        "from app.orchestrator.event_dispatcher import dispatch_event_chain\n"
        "from app.services.agent_action_requests import fulfill_pending_requests_for_admission",
        1,
    )
    fulfill_fn = (
        "\n\n"
        "def _fulfill_pending_agent_requests_isolated(admission: dict[str, Any], sim_time: datetime) -> list[dict[str, Any]]:\n"
        '    """Execute pending lab / MDT requests queued by agents (next demo step)."""\n'
        "    progress_emit(\n"
        "        {\n"
        '            "type": "agent_requests_start",\n'
        '            "admission_id": str(admission["admission_id"]),\n'
        '            "bed_id": str(admission.get("bed_id") or ""),\n'
        "        }\n"
        "    )\n"
        "    settings = get_settings()\n"
        "    with psycopg.connect(settings.pg_dsn) as conn:\n"
        "        with conn.transaction():\n"
        "            results = fulfill_pending_requests_for_admission(conn, admission, sim_time=sim_time)\n"
        "    for item in results:\n"
        "        progress_emit(\n"
        "            {\n"
        '                "type": "agent_request_fulfilled",\n'
        '                "admission_id": item.get("admission_id"),\n'
        '                "request_type": item.get("type"),\n'
        '                "request_id": item.get("request_id"),\n'
        "            }\n"
        "        )\n"
        "    return results\n\n\n"
    )
    demo = demo.replace(
        "def _run_clinical_event_isolated(admission: dict[str, Any], sim_time: datetime, event_type: str) -> dict[str, Any]:",
        fulfill_fn + "def _run_clinical_event_isolated(admission: dict[str, Any], sim_time: datetime, event_type: str) -> dict[str, Any]:",
        1,
    )
    hook = "    active_clinical = _active_admissions(conn)\n    random.shuffle(active_clinical)\n    clinical_jobs = ["
    hook_new = (
        "    active_clinical = _active_admissions(conn)\n\n"
        "    progress_emit(\n"
        "        {\n"
        '            "type": "phase",\n'
        '            "message": f"处理 {len(active_clinical)} 位患者的 Agent 待办（检查/会诊）…",\n'
        "        }\n"
        "    )\n"
        "    request_fulfillment: list[dict[str, Any]] = []\n"
        "    for adm in active_clinical:\n"
        "        request_fulfillment.extend(_fulfill_pending_agent_requests_isolated(adm, sim_after))\n"
        "    if request_fulfillment:\n"
        "        sub_events.extend(request_fulfillment)\n\n"
        "    random.shuffle(active_clinical)\n"
        "    clinical_jobs = ["
    )
    if hook not in demo:
        raise RuntimeError("demo hook not found")
    demo = demo.replace(hook, hook_new, 1)
    if "agent_action_requests" not in demo:
        demo = demo.replace(
            "                  agent_events,\n                  agent_outputs,",
            "                  agent_action_requests,\n                  agent_events,\n                  agent_outputs,",
            1,
        )
    demo_path.write_text(demo, encoding="utf-8")
    print("patched demo service")
