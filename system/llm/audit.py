from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.ids import new_id

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "logs" / "llm_audit.jsonl"


def write_llm_audit(record: dict[str, Any]) -> str:
    audit_id = str(record.get("audit_log_id") or new_id("llmaudit"))
    payload = {
        "audit_log_id": audit_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **record,
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return audit_id
