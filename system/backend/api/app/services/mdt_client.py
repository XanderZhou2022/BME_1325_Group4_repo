from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


class SimiMdtError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def check_simi_health() -> bool:
    settings = get_settings()
    base = settings.simi_mdt_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base}/api/v1/health")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


def post_icu_workflow(bundle: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    url = settings.simi_mdt_workflow_url()
    timeout = settings.simi_mdt_timeout_seconds
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=bundle)
    except httpx.ConnectError as exc:
        raise SimiMdtError(
            "SIMI_UNAVAILABLE",
            "Cannot connect to simi MDT API. Ensure mdt_consultation_api is running on port 8001.",
            status_code=503,
            details={"url": url, "error": str(exc)},
        ) from exc
    except httpx.TimeoutException as exc:
        raise SimiMdtError(
            "SIMI_TIMEOUT",
            f"simi MDT request timed out after {timeout}s",
            status_code=504,
            details={"url": url},
        ) from exc
    except httpx.HTTPError as exc:
        raise SimiMdtError(
            "SIMI_HTTP_ERROR",
            str(exc),
            status_code=502,
            details={"url": url},
        ) from exc

    try:
        body = resp.json()
    except ValueError as exc:
        raise SimiMdtError(
            "SIMI_INVALID_RESPONSE",
            "simi MDT returned non-JSON response",
            status_code=502,
            details={"status_code": resp.status_code, "text": resp.text[:500]},
        ) from exc

    if resp.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else body
        if resp.status_code == 422:
            raise SimiMdtError(
                "SIMI_VALIDATION_ERROR",
                str(detail),
                status_code=422,
                details={"simi_response": body},
            )
        raise SimiMdtError(
            "SIMI_MDT_FAILED",
            str(detail),
            status_code=502 if resp.status_code >= 500 else resp.status_code,
            details={"simi_response": body, "status_code": resp.status_code},
        )

    if not isinstance(body, dict):
        raise SimiMdtError(
            "SIMI_INVALID_RESPONSE",
            "simi MDT response must be a JSON object",
            status_code=502,
        )
    return body
