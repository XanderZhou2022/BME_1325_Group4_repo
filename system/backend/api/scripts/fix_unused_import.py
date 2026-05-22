from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "demo" / "service.py"
t = p.read_text(encoding="utf-8")
line = "from app.services.agent_observability import emit_agent_lifecycle_event\n"
if line in t and "emit_agent_lifecycle_event(" not in t.replace(line, ""):
    t = t.replace(line, "")
    p.write_text(t, encoding="utf-8")
    print("removed unused import")
else:
    print("skip", "still used" if "emit_agent_lifecycle_event(" in t else "not found")
