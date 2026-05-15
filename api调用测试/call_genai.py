#!/usr/bin/env python3
"""
上海科技大学 GenAI 网关调用示例（与 curl 示例一致）。

用法（在脚本所在目录）:
  pip install -r requirements.txt
  # 配置 .env（从 .env.example 复制）

  python call_genai.py --profile gpt52 --text "用一句话介绍 ICU 多智能体系统"
  python call_genai.py --profile qwen_vl --text "描述图片" --image-url "https://..."

环境变量见同目录 .env / .env.example
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# 与 .env 同目录加载
_ENV_DIR = Path(__file__).resolve().parent
load_dotenv(_ENV_DIR / ".env")

PROFILES: dict[str, tuple[str, str]] = {
    "gpt52": ("KEY_GPT52", "MODEL_GPT52"),
    "deepseek_v32": ("KEY_DEEPSEEK_V32", "MODEL_DEEPSEEK_V32"),
    "deepseek_r1": ("KEY_DEEPSEEK_R1", "MODEL_DEEPSEEK_R1"),
    "qwen3": ("KEY_QWEN3", "MODEL_QWEN3"),
    "qwen_vl": ("KEY_QWEN_VL", "MODEL_QWEN_VL"),
}


def _build_user_message(text: str, image_url: str | None) -> dict:
    if image_url:
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    return {"role": "user", "content": text}


def _payload(model: str, messages: list[dict], *, stream: bool) -> dict:
    # 网关对部分模型不接受空数组字段 `stop`，故不传（与 curl 示例有差异时以网关报错为准）
    return {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "n": 1,
        "stream": stream,
        "presence_penalty": 0,
        "frequency_penalty": 0,
    }


def _print_sse_line(line: str) -> None:
    line = line.strip()
    if not line or line == "data: [DONE]":
        return
    if line.startswith("data:"):
        line = line[5:].strip()
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        print(line, flush=True)
        return
    # OpenAI 风格增量
    choices = obj.get("choices") or []
    for ch in choices:
        delta = ch.get("delta") or {}
        if "content" in delta and delta["content"]:
            print(delta["content"], end="", flush=True)
        # 部分网关把整段放在 message
        msg = ch.get("message") or {}
        if isinstance(msg.get("content"), str) and msg["content"]:
            print(msg["content"], end="", flush=True)
    if obj.get("error"):
        print(f"\n[error] {obj['error']}", file=sys.stderr, flush=True)


def stream_request(url: str, headers: dict, body: dict) -> None:
    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                err = resp.read().decode("utf-8", errors="replace")
                print(f"HTTP {resp.status_code}: {err}", file=sys.stderr)
                sys.exit(1)
            for line in resp.iter_lines():
                if line is None:
                    continue
                _print_sse_line(line)
    print()


def blocking_request(url: str, headers: dict, body: dict) -> None:
    body = {**body, "stream": False}
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            print(r.text, file=sys.stderr)
            sys.exit(1)
        try:
            data = r.json()
        except json.JSONDecodeError:
            print(r.text)
            return
        print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="GenAI API 调用（.env 存 key）")
    p.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        default="gpt52",
        help="选择模型配置（对应 .env 中 KEY_* / MODEL_*）",
    )
    p.add_argument("--text", default="你好，请用一句话自我介绍。", help="用户文本")
    p.add_argument("--image-url", default=None, help="可选图片 URL（多模态，建议 qwen_vl 等）")
    p.add_argument("--no-stream", action="store_true", help="关闭流式，打印完整 JSON")
    args = p.parse_args()

    url = os.getenv("GENAI_API_URL", "https://genaiapi.shanghaitech.edu.cn/api/v1/start").strip()
    key_env, model_env = PROFILES[args.profile]
    api_key = os.getenv(key_env, "").strip()
    model = os.getenv(model_env, "").strip()
    if not api_key or not model:
        print(f"缺少环境变量: {key_env} 或 {model_env}，请检查 {_ENV_DIR / '.env'}", file=sys.stderr)
        sys.exit(1)

    messages = [_build_user_message(args.text, args.image_url)]
    body = _payload(model, messages, stream=not args.no_stream)
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if args.no_stream:
        blocking_request(url, headers, body)
    else:
        stream_request(url, headers, body)


if __name__ == "__main__":
    main()
