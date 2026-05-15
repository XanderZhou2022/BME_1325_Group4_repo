from __future__ import annotations

import json
import re
from typing import Any


_DIAGNOSIS_PATTERNS = [
    r"\bthe patient has sepsis\b",
    r"\bdiagnosed with\b",
    r"\bthis confirms\b",
    r"\bconfirmed shock\b",
    r"\bdiagnosis is\b",
]

_TREATMENT_PATTERNS = [
    r"\bstart norepinephrine\b",
    r"\bstart\b",
    r"\bstop\b",
    r"\bgive antibiotics\b",
    r"\bgive vasopressor\b",
    r"\bstart antibiotics\b",
    r"\bintubate\b",
    r"\bextubate\b",
    r"\bincrease (the )?dose\b",
    r"\bdecrease (the )?dose\b",
    r"\badminister\b",
    r"\btreatment plan\b",
    r"\bprescribe\b",
]

_AUTOMATION_PATTERNS = [
    r"\bautomatically (admit|discharge|transfer)\b",
    r"\bdecide ICU admission\b",
    r"\bdecide ICU discharge\b",
    r"\badmit to ICU\b",
    r"\bdischarge from ICU\b",
    r"\btransfer out\b",
    r"\bdeny ICU\b",
    r"\ballocate bed automatically\b",
]

_FAMILY_PATTERNS = [
    r"\btell the family\b",
    r"\binform the family directly\b",
    r"\binform the family .* death\b",
    r"\bfamily-facing prognosis\b",
    r"\bdeath is likely\b",
    r"\bwill die\b",
    r"\bwill not survive\b",
    r"\bdefinitely recover\b",
    r"\bguaranteed improvement\b",
    r"\bguaranteed\b",
    r"\bno hope\b",
    r"\bwe recommend stopping treatment\b",
    r"\bthe family should decide\b",
]


def _contains_human_review_true(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("human_review_required") is not True:
            return False
        return all(_contains_human_review_true(v) for v in value.values() if isinstance(v, (dict, list)))
    if isinstance(value, list):
        return all(_contains_human_review_true(v) for v in value if isinstance(v, (dict, list)))
    return True


def validate_llm_medical_safety(
    task_name: str,
    output: dict[str, Any],
    forbidden_use: list[str],
) -> tuple[bool, list[str]]:
    violations: list[str] = []
    if not _contains_human_review_true(output):
        violations.append("human_review_required must be true on output and nested items")

    text = json.dumps(output, ensure_ascii=False).lower()
    checks = [
        ("diagnosis", _DIAGNOSIS_PATTERNS),
        ("treatment_recommendation", _TREATMENT_PATTERNS),
        ("automatic_medical_decision", _AUTOMATION_PATTERNS),
        ("family_direct_communication_without_review", _FAMILY_PATTERNS),
    ]
    for label, patterns in checks:
        for pattern in patterns:
            if re.search(pattern, text):
                violations.append(f"{task_name} output matched unsafe {label} pattern: {pattern}")
                break

    for forbidden in forbidden_use:
        if forbidden.lower().replace("_", " ") in text and forbidden in {"diagnosis", "treatment_recommendation"}:
            violations.append(f"Output contains forbidden use phrase: {forbidden}")
    return len(violations) == 0, violations
