import copy
import json
import unittest

from llm.classifier import classify_criterion
from llm.local_llm_client import LLMClientConfig, LLMClientResponse


def _config(enabled):
    return LLMClientConfig(
        enabled=enabled,
        provider="fake-provider",
        base_url="http://example.invalid",
        model="fake-model",
        api_key="fake-key",
        timeout_seconds=1,
    )


def _rule(status="pass", evidence=None):
    if evidence is None:
        evidence = [{"text": "Product delivery is required within 30 days."}]
    return {
        "id": "criterion-1",
        "status": status,
        "criterion": "Delivery deadline",
        "evidence": evidence,
    }


def _valid_response_text(**overrides):
    payload = {
        "invocation_status": "ok",
        "rule_id": "criterion-1",
        "verdict": "pass",
        "confidence": "medium",
        "human_review_required": False,
        "reason": "The evidence supports the criterion.",
        "supporting_evidence_ids": [0],
        "warnings": [],
        "conflicts_with_rule": False,
        "deterministic_status": "pass",
        "provider": "fake-provider",
        "model": "fake-model",
    }
    payload.update(overrides)
    return json.dumps(payload)


class FakeClient:
    def __init__(self, config, response):
        self.config = config
        self.response = response
        self.last_prompt = None
        self.chat_calls = 0

    def chat(self, prompt):
        self.chat_calls += 1
        self.last_prompt = prompt
        return self.response


class ClassifierTests(unittest.TestCase):
    def test_disabled_config_skips_without_calling_client_and_keeps_rule(self):
        rule = _rule()
        original_rule = copy.deepcopy(rule)
        client = FakeClient(
            _config(enabled=False),
            LLMClientResponse(ok=True, text=_valid_response_text()),
        )

        result = classify_criterion(rule, client)

        self.assertEqual("skipped", result["invocation_status"])
        self.assertEqual("unknown", result["verdict"])
        self.assertEqual(0, client.chat_calls)
        self.assertEqual(original_rule, rule)

    def test_enabled_config_with_empty_evidence_skips_for_human_review(self):
        client = FakeClient(
            _config(enabled=True),
            LLMClientResponse(ok=True, text=_valid_response_text()),
        )

        result = classify_criterion(_rule(status="unknown", evidence=[]), client)

        self.assertEqual("skipped", result["invocation_status"])
        self.assertEqual("unknown", result["verdict"])
        self.assertTrue(result["human_review_required"])
        self.assertEqual(0, client.chat_calls)

    def test_valid_fake_json_returns_ok_verdict_from_response(self):
        client = FakeClient(
            _config(enabled=True),
            LLMClientResponse(
                ok=True,
                text=_valid_response_text(verdict="fail", supporting_evidence_ids=[0]),
            ),
        )

        result = classify_criterion(_rule(status="fail"), client)

        self.assertEqual(1, client.chat_calls)
        self.assertIsNotNone(client.last_prompt)
        self.assertEqual("ok", result["invocation_status"])
        self.assertEqual("fail", result["verdict"])
        self.assertEqual([0], result["supporting_evidence_ids"])

    def test_conflicting_fake_verdict_marks_conflict(self):
        client = FakeClient(
            _config(enabled=True),
            LLMClientResponse(ok=True, text=_valid_response_text(verdict="fail")),
        )

        result = classify_criterion(_rule(status="unknown"), client)

        self.assertTrue(result["conflicts_with_rule"])
        self.assertTrue(any("conflicts with deterministic status" in item for item in result["warnings"]))

    def test_invalid_fake_json_is_returned_without_raising(self):
        client = FakeClient(
            _config(enabled=True),
            LLMClientResponse(ok=True, text="{not json"),
        )

        result = classify_criterion(_rule(), client)

        self.assertEqual("invalid_json", result["invocation_status"])

    def test_fake_client_url_error_returns_unavailable_without_raising(self):
        client = FakeClient(
            _config(enabled=True),
            LLMClientResponse(
                ok=False,
                error_type="url_error",
                error_message="Connection refused",
                provider="fake-provider",
                model="fake-model",
            ),
        )

        result = classify_criterion(_rule(), client)

        self.assertEqual("unavailable", result["invocation_status"])
        self.assertEqual("url_error", result["error_type"])


if __name__ == "__main__":
    unittest.main()
