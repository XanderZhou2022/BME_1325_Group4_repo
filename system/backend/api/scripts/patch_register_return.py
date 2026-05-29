from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "services" / "agent_action_requests.py"
t = p.read_text(encoding="utf-8")
t = t.replace(
    ") -> list[str]:\n    created: list[str] = []\n    for spec in specs:\n        rid = enqueue_action_request(",
    ") -> list[dict[str, Any]]:\n    created: list[dict[str, Any]] = []\n    for spec in specs:\n        rid = enqueue_action_request(",
)
t = t.replace(
    "        if rid:\n            created.append(rid)\n    return created",
    "        created.append(\n            {\n                \"request_id\": rid,\n                \"request_type\": spec[\"request_type\"],\n                \"queued\": bool(rid),\n                \"payload\": spec.get(\"payload\") or {},\n            }\n        )\n    return created",
)
p.write_text(t, encoding="utf-8")

for rel in (
    "agents/clinical_summary/service.py",
    "agents/risk_sentinel/service.py",
):
    fp = Path(__file__).resolve().parents[3] / rel
    txt = fp.read_text(encoding="utf-8")
    txt = txt.replace(
        '_action_ids = register_agent_action_requests(',
        '_action_rows = register_agent_action_requests(',
    )
    txt = txt.replace(
        'payload["action_requests"] = [\n                {"request_id": rid, **spec}\n                for rid, spec in zip(_action_ids, _action_specs[: len(_action_ids)])\n            ]',
        'payload["action_requests"] = _action_rows',
    )
    txt = txt.replace(
        'payload["action_requests"] = [\n        {"request_id": rid, **spec} for rid, spec in zip(action_request_ids, action_specs[: len(action_request_ids)])\n    ]',
        'payload["action_requests"] = register_agent_action_requests(\n        conn,\n        admission_id=admission_id,\n        patient_id=summary.patient_id,\n        bed_id=summary.bed_id,\n        requested_by_agent="clinical_summary",\n        specs=action_specs,\n        source_output_id=output_id,\n    )',
    )
    # clinical may have duplicate register - read and fix manually
    fp.write_text(txt, encoding="utf-8")
    print("patched", rel)

demo = Path(__file__).resolve().parents[1] / "app" / "demo" / "service.py"
d = demo.read_text(encoding="utf-8")
if "agent_action_requests," not in d:
    d = d.replace(
        "                  agent_consumption_cursor,\n                  agent_events,",
        "                  agent_consumption_cursor,\n                  agent_action_requests,\n                  agent_events,",
        1,
    )
    demo.write_text(d, encoding="utf-8")
    print("demo truncate")
