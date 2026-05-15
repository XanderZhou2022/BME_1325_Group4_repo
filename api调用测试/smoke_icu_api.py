#!/usr/bin/env python3
"""
冒烟检查：本机 ICU Agent API 是否可用（不依赖 GenAI）。

默认假设后端已启动：http://127.0.0.1:8000
校验：
  GET  /health  （无 contract 信封）
  GET  /api/v1/demo/auto/state  （§5.2 信封，取 data）

用法（在仓库根目录或本目录均可）:
  pip install -r requirements.txt
  python smoke_icu_api.py
  python smoke_icu_api.py --base http://192.168.1.10:8000
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def _unwrap(body: object) -> object:
    if isinstance(body, dict) and "ok" in body:
        if not body.get("ok"):
            err = body.get("error") or {}
            print(json.dumps(body, ensure_ascii=False, indent=2), file=sys.stderr)
            raise SystemExit(f"API error: {err.get('code')} {err.get('message')}")
        return body.get("data")
    return body


def main() -> None:
    p = argparse.ArgumentParser(description="ICU Agent API smoke test")
    p.add_argument("--base", default="http://127.0.0.1:8000", help="API origin without trailing slash")
    args = p.parse_args()
    base = args.base.rstrip("/")

    with httpx.Client(timeout=15.0) as client:
        h = client.get(f"{base}/health")
        h.raise_for_status()
        print("[health]", h.json())

        r = client.get(f"{base}/api/v1/demo/auto/state")
        r.raise_for_status()
        data = _unwrap(r.json())
        print("[demo/auto/state]", json.dumps(data, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
