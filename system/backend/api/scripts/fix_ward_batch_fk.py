from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "demo" / "service.py"
t = p.read_text(encoding="utf-8")
old = '''    with psycopg.connect(settings.pg_dsn) as conn:
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
            progress_emit('''
new = '''    with psycopg.connect(settings.pg_dsn) as conn:
        try:
            ward_out = evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10))
            fin = datetime.now(timezone.utc)
            progress_emit('''
if old not in t:
    raise SystemExit("ward batch block not found")
t = t.replace(old, new, 1)
t = t.replace(
    '''        except Exception as exc:
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
            progress_emit(''',
    '''        except Exception as exc:
            fin = datetime.now(timezone.utc)
            progress_emit(''',
    1,
)
if "emit_agent_lifecycle_event" not in t.replace("from app.services.agent_observability import emit_agent_lifecycle_event\n", ""):
    pass
else:
    t = t.replace("from app.services.agent_observability import emit_agent_lifecycle_event\n", "")
p.write_text(t, encoding="utf-8")
print("fixed")
