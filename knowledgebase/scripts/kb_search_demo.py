#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


KB_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = KB_ROOT / "indexes"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.lower())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def bm25_score(query_terms: list[str], card: dict[str, Any], index: dict[str, Any]) -> float:
    k1 = 1.5
    b = 0.75
    card_id = card["card_id"]
    dl = index["doc_lengths"].get(card_id, 0)
    avgdl = index.get("avgdl") or 1.0
    score = 0.0
    for term in query_terms:
        freq = index["postings"].get(term, {}).get(card_id, 0)
        if not freq:
            continue
        idf = index["idf"].get(term, 0.0)
        denom = freq + k1 * (1 - b + b * dl / avgdl)
        score += idf * (freq * (k1 + 1) / denom)
    return score


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--risk_type")
    parser.add_argument("--top_k", type=int)
    args = parser.parse_args()

    cards = load_jsonl(INDEX_DIR / "cards.jsonl")
    profile_map = json.loads((INDEX_DIR / "agent_retrieval_profiles.json").read_text(encoding="utf-8"))
    bm25 = json.loads((INDEX_DIR / "bm25_index" / "index.json").read_text(encoding="utf-8"))
    if args.agent not in profile_map:
        raise SystemExit(f"Unknown agent: {args.agent}")

    profile = profile_map[args.agent]
    allowed = set(profile.get("allowed_domains", []))
    forbidden = set(profile.get("forbidden_domains", []))
    top_k = args.top_k or int(profile.get("default_top_k", 5))
    query_terms = tokenize(args.query)
    if args.risk_type:
        query_terms.extend(tokenize(args.risk_type))

    candidates = []
    for card in cards:
        if card["domain"] not in allowed:
            continue
        if card["domain"] in forbidden:
            continue
        if args.agent == "CompassionAgent" and not card.get("requires_clinician_approval", False):
            continue
        score = bm25_score(query_terms, card, bm25)
        if args.risk_type and args.risk_type in card.get("related_risk_types", []):
            score += 3.0
        if card.get("card_type") in profile.get("preferred_card_types", []):
            score += 0.5
        if args.agent in card.get("used_by_agents", []):
            score += 0.75
        if score <= 0:
            continue
        candidates.append((score, card))

    candidates.sort(key=lambda item: item[0], reverse=True)
    results = [
        {
            "card_id": card["card_id"],
            "domain": card["domain"],
            "topic": card["topic"],
            "score": round(score, 4),
            "key_points": card.get("key_points", []),
            "allowed_use": card.get("allowed_use", []),
            "forbidden_use": card.get("forbidden_use", []),
            "evidence_location": card.get("evidence_location", {}),
            "human_review_required": card.get("human_review_required", True),
        }
        for score, card in candidates[:top_k]
    ]
    print(
        json.dumps(
            {
                "agent": args.agent,
                "query": args.query,
                "filters": {"risk_type": args.risk_type} if args.risk_type else {},
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
