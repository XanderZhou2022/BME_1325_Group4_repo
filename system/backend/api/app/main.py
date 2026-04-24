from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from app.config import get_settings

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False if allowed_origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


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
