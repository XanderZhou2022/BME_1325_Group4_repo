#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


KB_ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = KB_ROOT / "cards"
SCHEMA_DIR = KB_ROOT / "schemas"
REGISTRY_DIR = KB_ROOT / "registry"
INDEX_DIR = KB_ROOT / "indexes"


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def load_cards() -> list[tuple[Path, dict[str, Any]]]:
    cards = []
    for path in sorted(CARDS_DIR.glob("**/*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cards.extend((path, item) for item in data)
        else:
            cards.append((path, data))
    return cards


def main() -> None:
    guideline_schema = load_schema("guideline_card.schema.json")
    concept_schema = load_schema("computational_concept.schema.json")
    guideline_validator = Draft202012Validator(guideline_schema)
    concept_validator = Draft202012Validator(concept_schema)
    sources = json.loads((REGISTRY_DIR / "sources.json").read_text(encoding="utf-8"))["sources"]
    source_ids = {source["source_id"]: source for source in sources}
    profiles = json.loads((INDEX_DIR / "agent_retrieval_profiles.json").read_text(encoding="utf-8"))

    errors = []
    card_ids = set()
    for path, card in load_cards():
        card_id = card.get("card_id") or card.get("concept_id")
        if card_id in card_ids:
            errors.append(f"Duplicate card/concept id: {card_id}")
        card_ids.add(card_id)
        schema_errors = (
            concept_validator.iter_errors(card)
            if card.get("domain") == "computational_concepts" or "concept_id" in card
            else guideline_validator.iter_errors(card)
        )
        for err in schema_errors:
            errors.append(f"{path}: {list(err.path)} {err.message}")

        source_id = card.get("source_id")
        if source_id not in source_ids:
            errors.append(f"{path}: source_id not found in sources.json: {source_id}")
        if "evidence_location" not in card:
            errors.append(f"{path}: missing evidence_location")
        if "allowed_use" not in card or "forbidden_use" not in card:
            errors.append(f"{path}: missing allowed_use or forbidden_use")
        if card.get("human_review_required") is not True:
            errors.append(f"{path}: human_review_required must be true")
        if card.get("population") == "pediatric":
            for agent, profile in profiles.items():
                if agent != "ClinicalSummaryAgent" and "pediatric" in profile.get("allowed_populations", []):
                    errors.append(f"{agent}: pediatric source should not be default adult retrieval")
        if card.get("domain") == "icu_design_context" and "icu_design_context" in profiles["RiskSentinelAgent"].get("allowed_domains", []):
            errors.append("RiskSentinelAgent must not default-retrieve ICU design domain")
        if "CompassionAgent" in card.get("used_by_agents", []) and card.get("requires_clinician_approval") is not True:
            errors.append(f"{path}: CompassionAgent card requires requires_clinician_approval=true")
        evidence = card.get("evidence_location", {})
        if not evidence.get("page_start") or not evidence.get("page_end"):
            if card.get("confidence") != "low" or not card.get("notes"):
                errors.append(f"{path}: missing precise page requires confidence=low and notes")

    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "ok", "validated_cards": len(card_ids)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
