from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id

from .schemas import SharedBoardEntry


def _get_latest_snapshot_state_snapshot(
    conn: Connection,
    *,
    admission_id: str,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.row_factory = dict_row
        cur.execute(
            """
            SELECT state_snapshot
            FROM patient_state_snapshots
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (admission_id,),
        )
        row = cur.fetchone()
    if not row:
        return {}
    raw = row.get("state_snapshot")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    # Fallback: if driver returns JSON string, best-effort parsing.
    # (Should be dict most of the time with psycopg JSONB.)
    return raw  # type: ignore[return-value]


def update_shared_board_snapshot(
    conn: Connection,
    *,
    admission_id: str,
    entry: SharedBoardEntry,
) -> datetime:
    """
    Append-only update:
    - Read latest patient_state_snapshots.state_snapshot
    - Update/overwrite `shared_patient_state_board[entry.source_agent]`
    - Insert a new snapshot row with updated state_snapshot JSON
    """
    latest_state = _get_latest_snapshot_state_snapshot(conn, admission_id=admission_id)
    latest_state.setdefault("shared_patient_state_board", {})
    board = latest_state.get("shared_patient_state_board")
    if not isinstance(board, dict):
        board = {}
        latest_state["shared_patient_state_board"] = board

    board[entry.source_agent] = entry.model_dump(mode="json")

    snapshot_ts = entry.timestamp
    if snapshot_ts.tzinfo is None:
        # Ensure TIMESTAMPTZ correctness.
        snapshot_ts = snapshot_ts.replace(tzinfo=timezone.utc)

    snapshot_id = new_id("snap")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patient_state_snapshots (
                id, admission_id, timestamp, state_snapshot
            ) VALUES (%s, %s, %s, %s::jsonb)
            """,
            (
                snapshot_id,
                admission_id,
                snapshot_ts,
                Json(latest_state),
            ),
        )
    return snapshot_ts


def get_shared_board_from_latest_snapshot(
    conn: Connection,
    *,
    admission_id: str,
) -> dict[str, Any]:
    latest_state = _get_latest_snapshot_state_snapshot(conn, admission_id=admission_id)
    board = latest_state.get("shared_patient_state_board", {})
    if not isinstance(board, dict):
        return {}
    return board

