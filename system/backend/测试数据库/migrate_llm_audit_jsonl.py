from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SYSTEM_ROOT = REPO_ROOT / "system"
API_ROOT = SYSTEM_ROOT / "backend" / "api"
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from llm.audit import import_llm_audit_jsonl  # noqa: E402


def main() -> None:
    default_path = REPO_ROOT / "logs" / "llm_audit.jsonl"
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path
    if not path.is_file():
        print(f"File not found: {path}")
        sys.exit(1)
    os.environ.setdefault("ICU_PG_DSN", "dbname=icu_agent user=postgres password=123456 host=localhost port=5432")
    count = import_llm_audit_jsonl(str(path))
    print(f"Imported {count} LLM audit records into llm_audit_logs.")


if __name__ == "__main__":
    main()
