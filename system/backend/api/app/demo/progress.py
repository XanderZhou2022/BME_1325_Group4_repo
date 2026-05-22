"""Real-time progress events for Auto Demo (NDJSON stream)."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable

EmitFn = Callable[[dict[str, Any]], None]

_emit: ContextVar[EmitFn | None] = ContextVar("demo_progress_emit", default=None)


def emit(event: dict[str, Any]) -> None:
    fn = _emit.get()
    if fn is None:
        return
    payload = {**event, "ts": datetime.now(timezone.utc).isoformat()}
    fn(payload)


def get_emit() -> EmitFn | None:
    return _emit.get()


@contextmanager
def progress_scope(callback: EmitFn | None):
    if callback is None:
        yield
        return
    token = _emit.set(callback)
    try:
        yield
    finally:
        _emit.reset(token)
