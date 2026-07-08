import unittest

from llm import schema


class SchemaContractTests(unittest.TestCase):
    def test_build_skipped_verdict_returns_full_contract(self):
        verdict = schema.build_skipped_verdict(
            rule_id="criterion-1",
            deterministic_status="unexpected",
            provider="fake-provider",
            model="fake-model",
            reason="Skipped for test.",
        )

        self.assertEqual(schema.REQUIRED_LLM_VERDICT_FIELDS, set(verdict))
        self.assertEqual("skipped", verdict["invocation_status"])
        self.assertEqual("criterion-1", verdict["rule_id"])
        self.assertEqual("unknown", verdict["verdict"])
        self.assertEqual("low", verdict["confidence"])
        self.assertEqual("unknown", verdict["deterministic_status"])
        self.assertEqual("fake-provider", verdict["provider"])
        self.assertEqual("fake-model", verdict["model"])

    def test_build_invalid_json_verdict_marks_human_review_and_raw_saved(self):
        verdict = schema.build_invalid_json_verdict(
            rule_id="criterion-1",
            deterministic_status="fail",
            provider="fake-provider",
            model="fake-model",
            reason="Invalid JSON.",
            raw_response_saved=True,
        )

        self.assertEqual("invalid_json", verdict["invocation_status"])
        self.assertTrue(verdict["human_review_required"])
        self.assertTrue(verdict["raw_response_saved"])

    def test_mark_conflict_with_rule_sets_flag_and_warning(self):
        cases = [
            ("unknown", "fail", True),
            ("fail", "unknown", True),
            ("pass", "pass", False),
        ]

        for deterministic_status, verdict, expected_conflict in cases:
            with self.subTest(deterministic_status=deterministic_status, verdict=verdict):
                llm_verdict = schema.build_ok_verdict(
                    rule_id="criterion-1",
                    deterministic_status=deterministic_status,
                    provider="fake-provider",
                    model="fake-model",
                    verdict=verdict,
                    confidence="low",
                    human_review_required=False,
                    reason="Checked.",
                    supporting_evidence_ids=[],
                )

                result = schema.mark_conflict_with_rule(llm_verdict)

                self.assertEqual(expected_conflict, result["conflicts_with_rule"])
                if expected_conflict:
                    self.assertTrue(
                        any("conflicts with deterministic status" in item for item in result["warnings"])
                    )
                else:
                    self.assertEqual([], result["warnings"])

    def test_normalize_status_returns_unknown_for_unexpected_value(self):
        self.assertEqual("unknown", schema.normalize_status("not-a-status"))


if __name__ == "__main__":
    unittest.main()
