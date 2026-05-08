"""§5.4 Idempotency-Key persistence for POST writes."""

from __future__ import annotations

import json
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json


def get_cached_response(conn: Connection, *, key: str, route: str) -> dict[str, Any] | None:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT response_json FROM idempotency_keys
            WHERE key = %s AND route = %s
              AND created_at > NOW() - INTERVAL '24 hours'
            """,
            (key, route),
        )
        row = cur.fetchone()
    if not row:
        return None
    raw = row["response_json"]
    return raw if isinstance(raw, dict) else json.loads(raw)


def store_response(conn: Connection, *, key: str, route: str, inner_payload: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO idempotency_keys (key, route, response_json)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (key) DO UPDATE SET
                route = EXCLUDED.route,
                response_json = EXCLUDED.response_json,
                created_at = NOW()
            """,
            (key, route, Json(inner_payload)),
        )
