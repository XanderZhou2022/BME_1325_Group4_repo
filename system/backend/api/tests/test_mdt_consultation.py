from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.mdt_bundle import AdmissionNotFoundError, build_icu_native_bundle
from app.services.mdt_client import SimiMdtError, post_icu_workflow


class _DictRowCursor:
    def __init__(self, handlers: dict[str, object]) -> None:
        self._handlers = handlers
        self._last_sql = ""

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._last_sql = " ".join(sql.split())
        self._params = params

    def fetchone(self):
        if "FROM admissions" in self._last_sql:
            return self._handlers.get("admission")
        if "FROM patients" in self._last_sql:
            return self._handlers.get("patient")
        if "FROM patient_state_current" in self._last_sql:
            return self._handlers.get("state")
        return None

    def fetchall(self):
        if "FROM lab_events" in self._last_sql:
            return self._handlers.get("labs", [])
        if "FROM intervention_events" in self._last_sql:
            return self._handlers.get("interventions", [])
        if "FROM alerts" in self._last_sql:
            return self._handlers.get("alerts", [])
        if "FROM risk_assessments" in self._last_sql:
            return self._handlers.get("risks", [])
        if "FROM agent_outputs" in self._last_sql:
            agent = self._params[1] if len(self._params) > 1 else ""
            outputs = self._handlers.get("agent_outputs", {})
            return outputs.get(agent, [])
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


class MdtBundleTest(unittest.TestCase):
    def _conn_with_sample(self):
        admission = {
            "admission_id": "ICU-ADM-TEST",
            "encounter_id": "E-20260101000000-abcd",
            "patient_id": "P-12345678",
            "bed_id": "B-ICU01-01",
            "admission_code": "ADM-TEST",
            "primary_diagnosis": "septic shock",
            "admission_reason": "hypotension",
            "severity_on_admission": "critical",
        }
        patient = {
            "patient_id": "P-12345678",
            "name": "Test Patient",
            "gender": "male",
            "age": 65,
            "chronic_conditions": [],
            "allergies": [],
            "baseline_profile": {},
        }
        state = {
            "admission_id": "ICU-ADM-TEST",
            "patient_id": "P-12345678",
            "bed_id": "B-ICU01-01",
            "current_vitals": {"heart_rate": 120, "mean_arterial_pressure": 55, "spo2": 90},
            "active_problems": ["shock"],
            "active_risks": [{"risk_type": "deterioration", "severity": "critical"}],
            "latest_interventions": [],
            "care_phase": "critical",
        }
        handlers = {
            "admission": admission,
            "patient": patient,
            "state": state,
            "labs": [{"lab_type": "lactate", "value": 4.2, "unit": "mmol/L", "abnormal_flag": "high"}],
            "interventions": [],
            "alerts": [],
            "risks": [],
            "agent_outputs": {
                "clinical_summary": [
                    {
                        "agent_name": "clinical_summary",
                        "payload": {"one_line_status": "Unstable shock physiology."},
                    }
                ],
            },
        }
        conn = MagicMock()
        conn.cursor.return_value = _DictRowCursor(handlers)
        return conn

    def test_build_bundle_contains_required_ids(self) -> None:
        bundle = build_icu_native_bundle(self._conn_with_sample(), "ICU-ADM-TEST", use_api=False)
        self.assertEqual(bundle["admission"]["admission_id"], "ICU-ADM-TEST")
        self.assertEqual(bundle["patient"]["patient_id"], "P-12345678")
        self.assertEqual(bundle["patient_state_current"]["bed_id"], "B-ICU01-01")
        self.assertIn("lab_events", bundle)
        self.assertFalse(bundle["use_api"])

    def test_missing_admission_raises(self) -> None:
        conn = MagicMock()
        conn.cursor.return_value = _DictRowCursor({"admission": None})
        with self.assertRaises(AdmissionNotFoundError):
            build_icu_native_bundle(conn, "ICU-ADM-MISSING")


class MdtClientTest(unittest.TestCase):
    @patch("app.services.mdt_client.httpx.Client")
    def test_post_icu_workflow_success(self, client_cls: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "consultation_id": "con-1",
            "admission_id": "ICU-ADM-TEST",
            "patient_id": "P-12345678",
            "finalized": False,
            "mdt_output_type": "mdt_required_updates",
            "mdt_judgment": {"status_level": "OPTIMIZE"},
        }
        client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        out = post_icu_workflow({"admission": {"admission_id": "ICU-ADM-TEST", "patient_id": "P-12345678"}})
        self.assertEqual(out["consultation_id"], "con-1")

    @patch("app.services.mdt_client.httpx.Client")
    def test_post_icu_workflow_connect_error(self, client_cls: MagicMock) -> None:
        import httpx

        client_cls.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError("refused")
        with self.assertRaises(SimiMdtError) as ctx:
            post_icu_workflow({})
        self.assertEqual(ctx.exception.code, "SIMI_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
