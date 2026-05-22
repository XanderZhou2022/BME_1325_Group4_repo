"""Cap in-flight LLM HTTP requests (DashScope) across threads."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from functools import lru_cache

from app.config import get_settings


@lru_cache
def _semaphore() -> threading.Semaphore:
    n = max(1, min(100, int(get_settings().llm_max_concurrency)))
    return threading.Semaphore(n)


@contextmanager
def llm_request_slot():
    sem = _semaphore()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()
