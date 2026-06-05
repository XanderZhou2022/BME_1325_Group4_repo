from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.config import get_settings


class InpatientBridgeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def check_inpatient_health() -> bool:
    settings = get_settings()
    url = f"{settings.inpatient_bridge_base_url.rstrip('/')}/api/v1/health"
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return False
            body = resp.json()
            return bool(body.get("ok"))
    except Exception:
        return False


def post_icu_transfer_intake(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.inpatient_bridge_base_url.rstrip('/')}/api/v1/icu-transfer-intake"
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": uuid.uuid4().hex,
    }
    try:
        with httpx.Client(timeout=settings.inpatient_bridge_timeout_seconds) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        raise InpatientBridgeError(
            "INTERNAL_ERROR",
            f"无法连接住院部桥接服务 ({settings.inpatient_bridge_base_url})：{exc}",
            status_code=503,
        ) from exc

    try:
        envelope = resp.json()
    except ValueError as exc:
        raise InpatientBridgeError(
            "INTERNAL_ERROR",
            f"住院部返回非 JSON：HTTP {resp.status_code}",
            status_code=resp.status_code,
        ) from exc

    if not isinstance(envelope, dict):
        raise InpatientBridgeError(
            "INTERNAL_ERROR",
            f"住院部返回格式异常：HTTP {resp.status_code}",
            status_code=resp.status_code,
        )

    envelope_ok = bool(envelope.get("ok"))
    if resp.status_code < 200 or resp.status_code >= 300 or not envelope_ok:
        err = envelope.get("error") if isinstance(envelope.get("error"), dict) else {}
        raise InpatientBridgeError(
            str(err.get("code") or "INTERNAL_ERROR"),
            str(err.get("message") or f"住院部拒绝接收：HTTP {resp.status_code}"),
            status_code=resp.status_code,
            details=err if isinstance(err, dict) else {},
        )
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise InpatientBridgeError("INTERNAL_ERROR", "住院部响应缺少 data 字段", status_code=502)
    return data
