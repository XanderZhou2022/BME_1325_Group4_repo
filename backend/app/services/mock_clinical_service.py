from app.models.clinical_state import ClinicalState


class MockClinicalService:
    def build_mock_exam_results(self) -> list[str]:
        # Fixed, deterministic results for demo purposes.
        return [
            "CBC: mild leukocytosis",
            "CRP: elevated",
            "Rapid antigen: negative",
        ]

    def build_diagnosis_and_prescription(
        self, lab_results: list[str]
    ) -> tuple[str, str]:
        # Keep it stable and simple; not medical advice.
        diagnosis = "可能的上呼吸道感染（mock）"
        prescription = (
            "处方（mock）：\n"
            "- 对症退热镇痛药（按说明）\n"
            "- 口服补液与休息建议\n"
            "- 如症状加重请及时就医"
        )
        return diagnosis, prescription

    def create_clinical_state_after_order_test(self) -> ClinicalState:
        lab_results = self.build_mock_exam_results()
        diagnosis, prescription = self.build_diagnosis_and_prescription(lab_results)
        return ClinicalState(
            chief_complaint="Headache and mild fever",
            lab_results=lab_results,
            initial_diagnosis=diagnosis,
            prescription=prescription,
        )


mock_clinical_service = MockClinicalService()

