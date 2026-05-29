from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.agent_action_requests import (
    derive_requests_from_clinical_summary,
    derive_requests_from_risk_sentinel,
    _infer_lab_types_from_texts,
)


class AgentActionDeriveTest(unittest.TestCase):
    def test_infer_lactate_from_text(self) -> None:
        labs = _infer_lab_types_from_texts(["Please order lactate and creatinine"])
        self.assertIn("lactate", labs)
        self.assertIn("creatinine", labs)

    def test_clinical_critical_requests_mdt(self) -> None:
        summary = SimpleNamespace(
            urgency_level="critical",
            uncertainties_or_missing_data=["No latest risk_assessments available."],
            recommended_attention_targets=[],
            watch_items=[],
            one_line_status="Unstable",
        )
        specs = derive_requests_from_clinical_summary(summary)
        types = {s["request_type"] for s in specs}
        self.assertIn("mdt_consultation", types)
        self.assertIn("lab", types)
        for spec in specs:
            self.assertTrue(spec["payload"].get("request"))
            self.assertTrue(spec["payload"].get("reason"))

    def test_risk_escalation_requests_mdt(self) -> None:
        resp = SimpleNamespace(
            escalation_level="immediate_review",
            overall_risk_level="critical",
            recommended_next_attention=["Repeat lactate in 2h"],
            new_or_worsening_flags=["shock"],
        )
        specs = derive_requests_from_risk_sentinel(resp)
        types = {s["request_type"] for s in specs}
        self.assertIn("mdt_consultation", types)
        self.assertIn("lab", types)
        for spec in specs:
            self.assertTrue(spec["payload"].get("request"))
            self.assertTrue(spec["payload"].get("reason"))


if __name__ == "__main__":
    unittest.main()
