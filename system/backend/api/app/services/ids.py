from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

# Contract v1.0: East Asia / Shanghai for encounter timestamps
_CN_TZ = timezone(timedelta(hours=8))

_ALNUM26 = string.ascii_uppercase + string.digits


def new_patient_id() -> str:
    """§1.1 Patient ID: P-{8 hex lowercase}."""
    return f"P-{uuid.uuid4().hex[:8]}"


def new_encounter_id(now: datetime | None = None) -> str:
    """§1.2 Encounter ID: E-{YYYYMMDDHHmmss}-{4 hex lowercase}."""
    dt = now or datetime.now(_CN_TZ)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CN_TZ)
    else:
        dt = dt.astimezone(_CN_TZ)
    ts = dt.strftime("%Y%m%d%H%M%S")
    suf = uuid.uuid4().hex[:4]
    return f"E-{ts}-{suf}"


def format_bed_id(ward_code: str, bed_number: int) -> str:
    """§1.3 Bed ID: B-{ward}-{two-digit bed}. ward e.g. ICU01."""
    return f"B-{ward_code}-{bed_number:02d}"


def new_contract_event_id() -> str:
    """§4.3 / Appendix A.3: evt_ + 26 uppercase alphanumeric."""
    body = "".join(secrets.choice(_ALNUM26) for _ in range(26))
    return f"evt_{body}"


def new_daily_document_id(prefix: str) -> str:
    """§1.4 LAB-/IMG-/ORD-/INT-/TRF- date + 5-digit sequence (randomized without DB seq)."""
    dt = datetime.now(_CN_TZ)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CN_TZ)
    else:
        dt = dt.astimezone(_CN_TZ)
    day = dt.strftime("%Y%m%d")
    seq = secrets.randbelow(100_000)
    return f"{prefix}-{day}-{seq:05d}"


def new_transfer_id() -> str:
    return new_daily_document_id("TRF")


def new_icu_admission_id() -> str:
    """Internal ICU admission primary key (not mandated by §1)."""
    return f"ICU-ADM-{uuid.uuid4().hex[:12].upper()}"


def new_lab_record_id() -> str:
    return new_daily_document_id("LAB")


def new_intervention_record_id() -> str:
    return new_daily_document_id("INT")


def new_id(prefix: str) -> str:
    """
    Legacy helper used across agents. Maps prefixes to contract IDs where applicable.
    """
    p = prefix.lower()
    if p in ("evt", "aevt"):
        return new_contract_event_id()
    if p == "vital":
        return new_daily_document_id("VS")  # vital sign row (contract defines INT- for interventions only)
    if p == "lab":
        return new_lab_record_id()
    if p == "intv":
        return new_intervention_record_id()
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

