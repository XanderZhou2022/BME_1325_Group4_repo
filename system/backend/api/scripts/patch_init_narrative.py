from pathlib import Path

init_path = Path(__file__).resolve().parents[2] / "测试数据库" / "init_core_tables.py"
text = init_path.read_text(encoding="utf-8")
ddl = '''
    """
    CREATE TABLE IF NOT EXISTS agent_action_requests (
        request_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        patient_id TEXT NOT NULL,
        bed_id TEXT NOT NULL,
        request_type TEXT NOT NULL CHECK (request_type IN ('lab', 'mdt_consultation')),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'completed', 'failed')),
        requested_by_agent TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        source_output_id TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        fulfilled_at TIMESTAMPTZ,
        fulfillment_detail JSONB
    );
    """,
'''
if "agent_action_requests" not in text:
    anchor = '    CREATE TABLE IF NOT EXISTS ward_priority_snapshots ('
    if anchor not in text:
        raise RuntimeError("init anchor missing")
    text = text.replace(anchor, ddl + anchor, 1)
    init_path.write_text(text, encoding="utf-8")
    print("init_core_tables patched")

narr_path = Path(__file__).resolve().parents[3] / "frontend" / "src" / "showcase" / "autoDemoNarrative.ts"
nar = narr_path.read_text(encoding="utf-8")
if "agent_request" not in nar:
    old = "      lines.push(`Mix: ${Object.entries(types)"
    new = (
        "      const reqTypes = Object.entries(types).filter(([k]) => k.startsWith('agent_request'));\n"
        "      if (reqTypes.length) {\n"
        "        lines.push(`Agent requests fulfilled: ${reqTypes.map(([k, v]) => `${k}×${v}`).join(', ')}.`);\n"
        "      }\n"
        "      lines.push(`Mix: ${Object.entries(types)"
    )
    if old not in nar:
        raise RuntimeError("narrative anchor missing")
    nar = nar.replace(old, new, 1)
    narr_path.write_text(nar, encoding="utf-8")
    print("narrative patched")
