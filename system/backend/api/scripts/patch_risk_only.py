from pathlib import Path

p = Path(__file__).resolve().parents[3] / "agents" / "risk_sentinel" / "service.py"
text = p.read_text(encoding="utf-8")
if "derive_requests_from_risk_sentinel" in text:
    print("already done")
    raise SystemExit(0)

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

needle = '            output_id = new_id("out")\n            event_id = new_id("aevt")'
if needle not in text:
    raise RuntimeError(f"needle missing in {p}")

replacement = (
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
    '            event_id = new_id("aevt")'
)

text = text.replace(needle, replacement, 1)
p.write_text(text, encoding="utf-8")
print("risk_sentinel ok")
