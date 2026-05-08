"""§5.2 unified JSON envelope for /api/v1 routes."""

from __future__ import annotations

import json
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def new_trace_id() -> str:
    return f"trc_{uuid.uuid4().hex}"


class ContractEnvelopeMiddleware(BaseHTTPMiddleware):
    """Wrap successful JSON responses in {ok, data, error, trace_id}."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not path.startswith("/api/v1"):
            return await call_next(request)

        trace_id = new_trace_id()
        request.state.trace_id = trace_id

        response = await call_next(request)

        if response.status_code >= 400:
            return response

        ct = response.headers.get("content-type", "")
        if "application/json" not in ct:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Avoid double-wrapping
        if isinstance(payload, dict) and "ok" in payload and "trace_id" in payload:
            return JSONResponse(
                content=payload,
                status_code=response.status_code,
                headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
            )

        wrapped: dict[str, Any] = {
            "ok": True,
            "data": payload,
            "error": None,
            "trace_id": trace_id,
        }
        return JSONResponse(
            content=wrapped,
            status_code=response.status_code,
            headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
        )


def envelope_error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None,
    trace_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message, "details": details or {}},
            "trace_id": trace_id,
        },
    )
