"""Thread-pool helpers for parallel admission / clinical work (each worker uses its own DB connection)."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

from app.config import get_settings

T = TypeVar("T")
R = TypeVar("R")


def effective_parallelism(item_count: int, *, max_workers: int | None = None) -> int:
    if item_count <= 0:
        return 1
    cap = max_workers if max_workers is not None else get_settings().demo_parallel_workers
    cap = max(1, min(32, int(cap)))
    return min(cap, item_count)


def parallel_map(items: list[T], worker: Callable[[T], R], *, max_workers: int | None = None) -> list[R]:
    if not items:
        return []
    workers = effective_parallelism(len(items), max_workers=max_workers)
    if workers <= 1:
        return [worker(item) for item in items]
    ordered: list[R | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="icu-par") as pool:
        future_to_idx = {pool.submit(worker, item): idx for idx, item in enumerate(items)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            ordered[idx] = future.result()
    return [r for r in ordered if r is not None]
