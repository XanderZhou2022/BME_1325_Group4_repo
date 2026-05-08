from __future__ import annotations

import asyncio
import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.contract_envelope import ContractEnvelopeMiddleware, envelope_error, new_trace_id

# Allow importing core agent modules from `local/system/agents`.
# When running from `local/system/backend/api`, Python's module search path does not include `local/system`.
SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)

from app.routers import router  # noqa: E402
from app.orchestrator.scheduler import scheduler_loop  # noqa: E402

settings = get_settings()
allowed_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if not allowed_origins:
    allowed_origins = ["*"]

app = FastAPI(title=settings.api_title, version=settings.api_version)
scheduler_task: asyncio.Task | None = None

# Inner: wraps JSON responses for contract §5.2 (must register before CORS so CORS stays outermost).
app.add_middleware(ContractEnvelopeMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False if allowed_origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        return envelope_error(
            status_code=exc.status_code,
            code=str(detail["code"]),
            message=str(detail.get("message", "error")),
            details={k: v for k, v in detail.items() if k not in ("code", "message")},
            trace_id=trace_id,
        )
    status_map = {
        400: "EVENT_SCHEMA_INVALID",
        404: "ENCOUNTER_NOT_FOUND",
        409: "PATIENT_CONFLICT",
        422: "STATE_TRANSITION_INVALID",
        429: "LLM_RATE_LIMITED",
        503: "LLM_GATEWAY_UNAVAILABLE",
    }
    code = status_map.get(exc.status_code, "INTERNAL_ERROR")
    message = str(detail) if not isinstance(detail, dict) else str(detail.get("message", detail))
    return envelope_error(
        status_code=exc.status_code,
        code=code,
        message=message,
        details=detail if isinstance(detail, dict) else {},
        trace_id=trace_id,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
    return envelope_error(
        status_code=400,
        code="EVENT_SCHEMA_INVALID",
        message="Request validation failed",
        details={"errors": exc.errors()},
        trace_id=trace_id,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
    return envelope_error(
        status_code=500,
        code="INTERNAL_ERROR",
        message=str(exc),
        details={"type": type(exc).__name__},
        trace_id=trace_id,
    )


@app.on_event("startup")
async def _startup_scheduler() -> None:
    global scheduler_task
    if settings.scheduler_enabled:
        scheduler_task = asyncio.create_task(scheduler_loop())


@app.on_event("shutdown")
async def _shutdown_scheduler() -> None:
    global scheduler_task
    if scheduler_task:
        scheduler_task.cancel()
        scheduler_task = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.api_title, "version": settings.api_version, "docs": "/docs"}
