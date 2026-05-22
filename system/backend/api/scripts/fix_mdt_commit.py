from pathlib import Path

persist = Path(__file__).resolve().parents[1] / "app" / "services" / "mdt_persist.py"
router = Path(__file__).resolve().parents[1] / "app" / "mdt" / "router.py"

t = persist.read_text(encoding="utf-8")
if "conn.commit()" in t:
    t = t.replace("    conn.commit()\n    return output_id", "    return output_id")
    persist.write_text(t, encoding="utf-8")
    print("mdt_persist: removed commit")
else:
    print("mdt_persist: already fixed")

t2 = router.read_text(encoding="utf-8")
if "with conn.transaction():" in t2 and "save_mdt_agent_output" in t2.split("trigger_mdt")[1][:800]:
    print("router: already wrapped")
else:
    old = """    admission = bundle["admission"]
    output_id = save_mdt_agent_output(
        conn,
        admission_id=admission_id,
        patient_id=str(admission["patient_id"]),
        bed_id=str(admission.get("bed_id") or bundle.get("patient_state_current", {}).get("bed_id") or ""),
        bridge_response=bridge,
    )
    return _bridge_to_result(bridge, output_id, simi_health_ok=simi_ok)"""
    new = """    admission = bundle["admission"]
    with conn.transaction():
        output_id = save_mdt_agent_output(
            conn,
            admission_id=admission_id,
            patient_id=str(admission["patient_id"]),
            bed_id=str(admission.get("bed_id") or bundle.get("patient_state_current", {}).get("bed_id") or ""),
            bridge_response=bridge,
        )
    return _bridge_to_result(bridge, output_id, simi_health_ok=simi_ok)"""
    if old in t2:
        router.write_text(t2.replace(old, new, 1), encoding="utf-8")
        print("router: wrapped transaction")
    else:
        print("router: pattern not found")
