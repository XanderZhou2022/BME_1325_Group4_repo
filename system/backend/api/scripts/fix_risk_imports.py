from pathlib import Path

p = Path(__file__).resolve().parents[3] / "agents" / "risk_sentinel" / "service.py"
text = p.read_text(encoding="utf-8")
dup = (
    "from app.services.agent_action_requests import (\n"
    "    derive_requests_from_risk_sentinel,\n"
    "    register_agent_action_requests,\n"
    ")\n"
    "from app.services.agent_action_requests import (\n"
    "    derive_requests_from_risk_sentinel,\n"
    "    register_agent_action_requests,\n"
    ")\n"
    "from app.services.ids import new_id\n"
    "from types import SimpleNamespace\n"
    "from types import SimpleNamespace\n"
)
fixed = (
    "from app.services.agent_action_requests import (\n"
    "    derive_requests_from_risk_sentinel,\n"
    "    register_agent_action_requests,\n"
    ")\n"
    "from app.services.ids import new_id\n"
    "from types import SimpleNamespace\n"
)
if dup in text:
    text = text.replace(dup, fixed, 1)
    p.write_text(text, encoding="utf-8")
    print("fixed duplicates")
else:
    print("no dup block")
