from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_ROOT = REPO_ROOT / "system" / "prompts"


def load_prompt_template(prompt_name: str) -> str:
    path = PROMPT_ROOT / prompt_name
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_name}")
    return path.read_text(encoding="utf-8")
