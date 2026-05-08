"""Redis Pub/Sub + Stream journal — BME1325 contract §4."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

_CN = timezone(timedelta(hours=8))

_REDIS: redis.Redis | None = None


def _client() -> redis.Redis | None:
    global _REDIS
    s = get_settings()
    if not s.hospital_bus_enabled:
        return None
    if _REDIS is None:
        _REDIS = redis.Redis(
            host=s.hospital_redis_host,
            port=s.hospital_redis_port,
            db=s.hospital_redis_db,
            password=s.hospital_redis_password or None,
            decode_responses=True,
        )
    return _REDIS


def publish_contract_event(
    *,
    event_type: str,
    patient_id: str,
    data: dict[str, Any],
    encounter_id: str | None = None,
    correlation_id: str | None = None,
    producer: str | None = None,
    durable: bool = False,
    occurred_at: datetime | None = None,
) -> str | None:
    """
    §4.3 envelope + §4.2 channel hospital.<domain>.<event>.
    """
    r = _client()
    if r is None:
        return None

    from app.services.ids import new_contract_event_id

    s = get_settings()
    prod = producer or s.group_producer
    eid = new_contract_event_id()
    dt = occurred_at or datetime.now(_CN)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CN)
    else:
        dt = dt.astimezone(_CN)

    envelope = {
        "event_id": eid,
        "event_type": event_type,
        "schema_version": "1.0",
        "occurred_at": dt.isoformat(timespec="milliseconds"),
        "producer": prod,
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "correlation_id": correlation_id or eid,
        "data": data,
    }
    payload = json.dumps(envelope, ensure_ascii=False)
    channel = f"hospital.{event_type}"
    try:
        r.publish(channel, payload)
        if durable:
            r.xadd("hospital:journal", {"payload": payload}, maxlen=100_000, approximate=True)
    except redis.RedisError as exc:
        logger.warning("hospital bus publish failed: %s", exc)
        return None
    return eid


def mirror_agent_event_row(
    *,
    table_event_id: str,
    admission_id: str,
    patient_id: str,
    bed_id: str,
    producer_agent: str,
    internal_event_type: str,
    payload: dict[str, Any],
    encounter_id: str | None,
) -> None:
    """Map DB agent_events row to a cross-group friendly event (best-effort)."""
    data = {
        "source": "agent_events",
        "table_event_id": table_event_id,
        "admission_id": admission_id,
        "bed_id": bed_id,
        "producer_agent": producer_agent,
        "internal_event_type": internal_event_type,
        "payload": payload,
    }
    publish_contract_event(
        event_type="alert.raised",
        patient_id=patient_id,
        encounter_id=encounter_id,
        data=data,
        durable=True,
    )
