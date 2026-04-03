from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

# Allow importing core agent modules from `local/system/agents`.
# When running from `local/system/backend/api`, Python's module search path does not include `local/system`.
SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)

from app.routers import router  # noqa: E402

settings = get_settings()

app = FastAPI(title=settings.api_title, version=settings.api_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.api_title, "version": settings.api_version, "docs": "/docs"}
