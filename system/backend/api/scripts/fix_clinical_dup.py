from pathlib import Path

p = Path(__file__).resolve().parents[3] / "agents" / "clinical_summary" / "service.py"
t = p.read_text(encoding="utf-8")
dup = """    action_request_ids = register_agent_action_requests(
        conn,
        admission_id=admission_id,
        patient_id=summary.patient_id,
        bed_id=summary.bed_id,
        requested_by_agent="clinical_summary",
        specs=action_specs,
        source_output_id=output_id,
    )
    payload["action_requests"] = register_agent_action_requests(
        conn,
        admission_id=admission_id,
        patient_id=summary.patient_id,
        bed_id=summary.bed_id,
        requested_by_agent="clinical_summary",
        specs=action_specs,
        source_output_id=output_id,
    )"""
fix = """    payload["action_requests"] = register_agent_action_requests(
        conn,
        admission_id=admission_id,
        patient_id=summary.patient_id,
        bed_id=summary.bed_id,
        requested_by_agent="clinical_summary",
        specs=action_specs,
        source_output_id=output_id,
    )"""
if dup in t:
    t = t.replace(dup, fix, 1)
    p.write_text(t, encoding="utf-8")
    print("fixed")
else:
    print("not found")
