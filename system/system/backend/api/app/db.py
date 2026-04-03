from __future__ import annotations

from collections.abc import Generator

import psycopg
from psycopg import Connection

from app.config import get_settings


def get_db() -> Generator[Connection, None, None]:
    settings = get_settings()
    conn = psycopg.connect(settings.pg_dsn)
    try:
        yield conn
    finally:
        conn.close()
