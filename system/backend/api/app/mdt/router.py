from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.rows import dict_row

from app.db import get_db
from app.schemas import MdtConsultationResultOut, MdtConsultationTriggerIn, MdtLatestOut
from app.services.mdt_bundle import AdmissionNotFoundError, build_icu_native_bundle
from app.services.mdt_client import SimiMdtError, check_simi_health, post_icu_workflow
from app.services.mdt_persist import save_mdt_agent_output

router = APIRouter(tags=["mdt-consultation"])


def _bridge_to_result(bridge: dict[str, Any], output_id: str, *, simi_health_ok: bool) -> MdtConsultationResultOut:
    return MdtConsultationResultOut(
        admission_id=str(bridge.get("admission_id") or ""),
        patient_id=str(bridge.get("patient_id") or ""),
        consultation_id=str(bridge.get("consultation_id") or ""),
        finalized=bool(bridge.get("finalized")),
        mdt_output_type=str(bridge.get("mdt_output_type") or "mdt_required_updates"),
        mdt_judgment=bridge.get("mdt_judgment") if isinstance(bridge.get("mdt_judgment"), dict) else {},
        treatment_and_surgical_plan=bridge.get("treatment_and_surgical_plan") or [],
        recommendations=bridge.get("recommendations") or [],
        required_updates=bridge.get("required_updates") or [],
        next_steps=bridge.get("next_steps") or [],
        case_summary=str(bridge.get("case_summary") or ""),
        safety_boundary=str(bridge.get("safety_boundary") or ""),
        output_id=output_id,
        simi_health_ok=simi_health_ok,
    )


def _simi_http_exception(exc: SimiMdtError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@router.get("/admissions/{admission_id}/consultations/mdt/export")
def export_mdt_bundle(
    admission_id: str,
    conn: Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        return build_icu_native_bundle(conn, admission_id)
    except AdmissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/admissions/{admission_id}/consultations/mdt", response_model=MdtConsultationResultOut)
def trigger_mdt_consultation(
    admission_id: str,
    body: MdtConsultationTriggerIn,
    conn: Connection = Depends(get_db),
) -> MdtConsultationResultOut:
    simi_ok = check_simi_health()
    try:
        bundle = build_icu_native_bundle(
            conn,
            admission_id,
            reason=body.reason,
            use_api=body.use_api,
            questions_for_mdt=body.questions_for_mdt or None,
            labs_limit=body.limits.labs,
            interventions_limit=body.limits.interventions,
            risks_limit=body.limits.risks,
        )
    except AdmissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        bridge = post_icu_workflow(bundle)
    except SimiMdtError as exc:
        raise _simi_http_exception(exc) from exc

    admission = bundle["admission"]
    output_id = save_mdt_agent_output(
        conn,
        admission_id=admission_id,
        patient_id=str(admission["patient_id"]),
        bed_id=str(admission.get("bed_id") or bundle.get("patient_state_current", {}).get("bed_id") or ""),
        bridge_response=bridge,
    )
    return _bridge_to_result(bridge, output_id, simi_health_ok=simi_ok)


@router.get("/admissions/{admission_id}/consultations/mdt/latest", response_model=MdtLatestOut)
def get_latest_mdt_consultation(
    admission_id: str,
    conn: Connection = Depends(get_db),
) -> MdtLatestOut:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT output_id, admission_id, patient_id, bed_id, agent_name, schema_version,
                   output_type, generated_at, payload
            FROM agent_outputs
            WHERE admission_id = %s AND agent_name = 'mdt_consultation'
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (admission_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="no MDT consultation output found for admission")
    data = dict(row)
    data["payload"] = data.get("payload") or {}
    return MdtLatestOut(**data)
