import json
import unittest

from llm import json_guard


def _valid_payload(**overrides):
    payload = {
        "invocation_status": "ok",
        "rule_id": "payload-rule",
        "verdict": "pass",
        "confidence": "medium",
        "human_review_required": False,
        "reason": "The evidence supports the criterion.",
        "supporting_evidence_ids": [0, 2],
        "warnings": [],
        "conflicts_with_rule": False,
        "deterministic_status": "pass",
        "provider": "payload-provider",
        "model": "payload-model",
    }
    payload.update(overrides)
    return payload


class JsonGuardTests(unittest.TestCase):
    def test_parse_llm_verdict_accepts_plain_json(self):
        result = json_guard.parse_llm_verdict(
            json.dumps(_valid_payload()),
            rule_id="criterion-1",
            deterministic_status="pass",
            provider="fake-provider",
            model="fake-model",
        )

        self.assertEqual("ok", result["invocation_status"])
        self.assertEqual("pass", result["verdict"])
        self.assertEqual([0, 2], result["supporting_evidence_ids"])

    def test_parse_llm_verdict_accepts_markdown_json_fence(self):
        raw_response = "```json\n" + json.dumps(_valid_payload(verdict="fail")) + "\n```"

        result = json_guard.parse_llm_verdict(
            raw_response,
            rule_id="criterion-1",
            deterministic_status="fail",
            provider="fake-provider",
            model="fake-model",
        )

        self.assertEqual("ok", result["invocation_status"])
        self.assertEqual("fail", result["verdict"])

    def test_invalid_json_returns_invalid_json_verdict(self):
        result = json_guard.parse_llm_verdict(
            "{not json",
            rule_id="criterion-1",
            deterministic_status="unknown",
            provider="fake-provider",
            model="fake-model",
        )

        self.assertEqual("invalid_json", result["invocation_status"])
        self.assertEqual("json_decode_error", result["error_type"])

    def test_missing_required_field_is_reported(self):
        payload = _valid_payload()
        del payload["reason"]

        result = json_guard.parse_llm_verdict(
            json.dumps(payload),
            rule_id="criterion-1",
            deterministic_status="unknown",
            provider="fake-provider",
            model="fake-model",
        )

        self.assertEqual("invalid_json", result["invocation_status"])
        self.assertEqual("contract_validation_error", result["error_type"])
        self.assertIn("Missing required fields: reason", result["error_message"])
        self.assertTrue(any("Missing required fields: reason" in item for item in result["warnings"]))

    def test_contract_type_violations_return_invalid_json(self):
        cases = [
            {"supporting_evidence_ids": ["0"]},
            {"warnings": [123]},
            {"human_review_required": "false"},
            {"conflicts_with_rule": "false"},
        ]

        for overrides in cases:
            with self.subTest(overrides=overrides):
                result = json_guard.parse_llm_verdict(
                    json.dumps(_valid_payload(**overrides)),
                    rule_id="criterion-1",
                    deterministic_status="unknown",
                    provider="fake-provider",
                    model="fake-model",
                )

                self.assertEqual("invalid_json", result["invocation_status"])
                self.assertEqual("contract_validation_error", result["error_type"])

    def test_valid_json_uses_parser_context_for_rule_metadata(self):
        result = json_guard.parse_llm_verdict(
            json.dumps(
                _valid_payload(
                    rule_id="payload-rule",
                    deterministic_status="fail",
                    provider="payload-provider",
                    model="payload-model",
                )
            ),
            rule_id="context-rule",
            deterministic_status="unknown",
            provider="context-provider",
            model="context-model",
        )

        self.assertEqual("context-rule", result["rule_id"])
        self.assertEqual("unknown", result["deterministic_status"])
        self.assertEqual("context-provider", result["provider"])
        self.assertEqual("context-model", result["model"])


if __name__ == "__main__":
    unittest.main()
