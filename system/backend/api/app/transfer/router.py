from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db
from app.schemas import TransferOutEvaluationOut, TransferOutExecuteIn, TransferOutResultOut
from app.services.inpatient_client import check_inpatient_health
from app.services.inpatient_transfer import execute_transfer_out
from app.services.transfer_evaluator import evaluate_transfer_out

router = APIRouter(prefix="/api/v1", tags=["inpatient-transfer"])


@router.get("/admissions/{admission_id}/transfer-out/evaluation", response_model=TransferOutEvaluationOut)
def get_transfer_out_evaluation(admission_id: str, conn: Connection = Depends(get_db)) -> TransferOutEvaluationOut:
    data = evaluate_transfer_out(conn, admission_id)
    data["inpatient_bridge_ok"] = check_inpatient_health()
    return TransferOutEvaluationOut(**data)


@router.post("/admissions/{admission_id}/transfer-out", response_model=TransferOutResultOut)
def post_transfer_out(
    admission_id: str,
    body: TransferOutExecuteIn,
    conn: Connection = Depends(get_db),
) -> TransferOutResultOut:
    result = execute_transfer_out(conn, admission_id, force=body.force)
    evaluation = result.get("evaluation") or {}
    if isinstance(evaluation, dict) and "inpatient_bridge_ok" not in evaluation:
        evaluation = {**evaluation, "inpatient_bridge_ok": check_inpatient_health()}
    return TransferOutResultOut(
        status=result.get("status", "rejected"),
        transfer_id=result.get("transfer_id"),
        message=str(result.get("message") or ""),
        evaluation=evaluation,
        bridge_response=result.get("bridge_response") or {},
        output_id=result.get("output_id"),
        error_code=result.get("error_code"),
    )


@router.get("/transfer-out/bridge-health")
def transfer_bridge_health() -> dict[str, Any]:
    return {"ok": check_inpatient_health(), "service": "groupD.inpatient.intake"}
