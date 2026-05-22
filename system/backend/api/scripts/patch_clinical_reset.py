from pathlib import Path

# clinical_summary action_requests list fix
cs = Path(__file__).resolve().parents[3] / "agents" / "clinical_summary" / "service.py"
t = cs.read_text(encoding="utf-8")
old = """    payload["action_requests"] = [
        {"request_id": rid, **spec} for rid, spec in zip(action_request_ids, action_specs[: len(action_request_ids)])
    ]"""
new = """    payload["action_requests"] = []
    for spec in action_specs:
        rid = enqueue_action_request(
            conn,
            admission_id=admission_id,
            patient_id=summary.patient_id,
            bed_id=summary.bed_id,
            request_type=spec["request_type"],
            requested_by_agent="clinical_summary",
            payload=spec.get("payload") or {},
            source_output_id=output_id,
        )
        payload["action_requests"].append(
            {"request_id": rid, "queued": bool(rid), **spec}
        )"""
if old in t:
    t = t.replace(
        "    action_request_ids = register_agent_action_requests(\n        conn,\n        admission_id=admission_id,\n        patient_id=summary.patient_id,\n        bed_id=summary.bed_id,\n        requested_by_agent=\"clinical_summary\",\n        specs=action_specs,\n        source_output_id=output_id,\n    )\n" + old,
        "    from app.services.agent_action_requests import enqueue_action_request\n" + new,
        1,
    )
    # avoid double register - remove register block
    t = t.replace(
        "    from app.services.agent_action_requests import enqueue_action_request\n",
        "",
        1,
    )
    t = t.replace(
        "    action_specs = derive_requests_from_clinical_summary(summary, output_id=output_id)\n    action_request_ids = register_agent_action_requests(\n        conn,\n        admission_id=admission_id,\n        patient_id=summary.patient_id,\n        bed_id=summary.bed_id,\n        requested_by_agent=\"clinical_summary\",\n        specs=action_specs,\n        source_output_id=output_id,\n    )\n",
        "    action_specs = derive_requests_from_clinical_summary(summary, output_id=output_id)\n",
        1,
    )
    cs.write_text(t, encoding="utf-8")
    print("clinical_summary action_requests fixed")

demo = Path(__file__).resolve().parents[1] / "app" / "demo" / "service.py"
d = demo.read_text(encoding="utf-8")
if "agent_action_requests" not in d.split("TRUNCATE")[1][:800]:
    d = d.replace(
        "                  agent_events,\n                  agent_outputs,",
        "                  agent_action_requests,\n                  agent_events,\n                  agent_outputs,",
        1,
    )
    demo.write_text(d, encoding="utf-8")
    print("demo reset truncate ok")
