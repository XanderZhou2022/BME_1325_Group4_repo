#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


KB_ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = KB_ROOT / "cards"
INDEX_DIR = KB_ROOT / "indexes"
REGISTRY_DIR = KB_ROOT / "registry"


def card_files() -> list[Path]:
    return sorted(CARDS_DIR.glob("**/*.json"))


def load_cards() -> list[dict[str, Any]]:
    cards = []
    for path in card_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cards.extend(data)
        else:
            cards.append(data)
    return cards


def text_for_card(card: dict[str, Any]) -> str:
    fields = [
        card.get("card_id", ""),
        card.get("domain", ""),
        card.get("subdomain", ""),
        card.get("card_type", ""),
        card.get("topic", ""),
        card.get("clinical_context", ""),
        " ".join(card.get("key_points", [])),
        " ".join(card.get("trigger_signals", [])),
        " ".join(card.get("related_risk_types", [])),
        " ".join(card.get("retrieval_keywords", [])),
    ]
    return " ".join(str(x) for x in fields)


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.lower())


def minimal_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "card_id": card["card_id"],
        "domain": card["domain"],
        "topic": card["topic"],
        "key_points": card.get("key_points", []),
        "trigger_signals": card.get("trigger_signals", []),
        "related_risk_types": card.get("related_risk_types", []),
        "used_by_agents": card.get("used_by_agents", []),
        "retrieval_keywords": card.get("retrieval_keywords", []),
        "human_review_required": card.get("human_review_required", True),
    }


def main() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    (INDEX_DIR / "bm25_index").mkdir(parents=True, exist_ok=True)
    cards = load_cards()

    with (INDEX_DIR / "cards.jsonl").open("w", encoding="utf-8") as f:
        for card in cards:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")

    with (INDEX_DIR / "cards_minimal.jsonl").open("w", encoding="utf-8") as f:
        for card in cards:
            f.write(json.dumps(minimal_card(card), ensure_ascii=False) + "\n")

    doc_terms = {}
    doc_lengths = {}
    postings: dict[str, dict[str, int]] = defaultdict(dict)
    for card in cards:
        tokens = tokenize(text_for_card(card))
        counts = Counter(tokens)
        card_id = card["card_id"]
        doc_terms[card_id] = counts
        doc_lengths[card_id] = len(tokens)
        for term, freq in counts.items():
            postings[term][card_id] = freq

    doc_count = len(cards)
    avgdl = sum(doc_lengths.values()) / doc_count if doc_count else 0
    idf = {term: math.log(1 + (doc_count - len(docs) + 0.5) / (len(docs) + 0.5)) for term, docs in postings.items()}
    bm25 = {
        "schema_version": "icu_agent.bm25.v1",
        "generated_at": date.today().isoformat(),
        "doc_count": doc_count,
        "avgdl": avgdl,
        "doc_lengths": doc_lengths,
        "idf": idf,
        "postings": postings,
    }
    (INDEX_DIR / "bm25_index" / "index.json").write_text(json.dumps(bm25, ensure_ascii=False), encoding="utf-8")

    manifest = {
        "schema_version": "icu_agent.card_manifest.v1",
        "generated_at": date.today().isoformat(),
        "card_count": len(cards),
        "cards": [
            {
                "card_id": card["card_id"],
                "source_id": card["source_id"],
                "domain": card["domain"],
                "card_type": card["card_type"],
                "path": str(next((p for p in card_files() if p.read_text(encoding="utf-8").find(card["card_id"]) >= 0), "")),
                "human_review_required": card.get("human_review_required", True),
            }
            for card in cards
        ],
    }
    (REGISTRY_DIR / "card_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built indexes for {len(cards)} cards.")


if __name__ == "__main__":
    main()
