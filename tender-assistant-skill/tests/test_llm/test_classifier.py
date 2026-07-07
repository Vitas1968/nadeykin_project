import copy
import io
import json
import os
import unittest
from unittest.mock import patch

from llm.classifier import (
    DEFAULT_MAX_EVIDENCE_CHARS,
    DEFAULT_MAX_EVIDENCE_ITEMS,
    HARD_MAX_EVIDENCE_CHARS,
    HARD_MAX_EVIDENCE_ITEMS,
    TRUNCATION_MARKER,
    _env_positive_int,
    _evidence_payload,
    classify_criterion,
)
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


def _rendered_prompt_for_rule(rule_id, criterion, evidence=None):
    rule = _rule(evidence=evidence)
    rule["id"] = rule_id
    rule["criterion"] = criterion
    client = FakeClient(
        _config(enabled=True),
        LLMClientResponse(
            ok=True,
            text=_valid_response_text(rule_id=rule_id),
        ),
    )

    classify_criterion(rule, client)

    return client.last_prompt


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

    def test_evidence_payload_limits_default_items_to_three(self):
        rule = _rule(evidence=[{"text": f"evidence {index}"} for index in range(4)])

        result = _evidence_payload(rule)

        self.assertEqual(DEFAULT_MAX_EVIDENCE_ITEMS, len(result))
        self.assertEqual(["evidence 0", "evidence 1", "evidence 2"], [item["text"] for item in result])

    def test_evidence_payload_max_items_keeps_current_order(self):
        rule = _rule(evidence=[{"text": "first"}, {"text": "second"}, {"text": "third"}])

        result = _evidence_payload(rule, max_items=2)

        self.assertEqual(["first", "second"], [item["text"] for item in result])

    def test_evidence_payload_truncates_long_text(self):
        result = _evidence_payload(_rule(evidence=[{"text": "x" * 50}]), max_chars=30)

        self.assertLessEqual(len(result[0]["text"]), 30)
        self.assertIn(TRUNCATION_MARKER, result[0]["text"])

    def test_evidence_payload_truncates_long_snippet(self):
        result = _evidence_payload(_rule(evidence=[{"snippet": "x" * 50}]), max_chars=30)

        self.assertLessEqual(len(result[0]["snippet"]), 30)
        self.assertIn(TRUNCATION_MARKER, result[0]["snippet"])

    def test_evidence_payload_truncates_long_block_text(self):
        result = _evidence_payload(_rule(evidence=[{"block": {"text": "x" * 50}}]), max_chars=30)

        self.assertLessEqual(len(result[0]["block"]["text"]), 30)
        self.assertIn(TRUNCATION_MARKER, result[0]["block"]["text"])

    def test_evidence_payload_does_not_mark_exact_length_text(self):
        result = _evidence_payload(_rule(evidence=[{"text": "x" * 20}]), max_chars=20)

        self.assertEqual("x" * 20, result[0]["text"])
        self.assertNotIn(TRUNCATION_MARKER, result[0]["text"])

    def test_evidence_payload_does_not_mark_short_text(self):
        result = _evidence_payload(_rule(evidence=[{"text": "short"}]), max_chars=20)

        self.assertEqual("short", result[0]["text"])
        self.assertNotIn(TRUNCATION_MARKER, result[0]["text"])

    def test_evidence_payload_keeps_all_items_below_max_items(self):
        rule = _rule(evidence=[{"text": "first"}, {"text": "second"}])

        result = _evidence_payload(rule, max_items=3)

        self.assertEqual(["first", "second"], [item["text"] for item in result])

    def test_evidence_payload_does_not_mutate_rule_or_nested_block(self):
        rule = _rule(evidence=[{"text": "x" * 50, "block": {"text": "y" * 50}}])
        original_rule = copy.deepcopy(rule)

        result = _evidence_payload(rule, max_chars=20)

        self.assertEqual(original_rule, rule)
        self.assertIsNot(result[0]["block"], rule["evidence"][0]["block"])

    def test_evidence_payload_ignores_missing_none_and_non_string_text_fields(self):
        rule = _rule(
            evidence=[
                {"text": None},
                {"snippet": 123},
                {"block": {"text": None}},
                {"text": 123, "snippet": "valid snippet", "block": {"text": 456}},
            ]
        )

        result = _evidence_payload(rule)

        self.assertEqual(1, len(result))
        self.assertEqual(123, result[0]["text"])
        self.assertEqual("valid snippet", result[0]["snippet"])
        self.assertEqual(456, result[0]["block"]["text"])

    def test_evidence_payload_skips_non_dict_items_without_raising(self):
        rule = _rule(evidence=["not a dict", {"text": "valid"}, 42])

        result = _evidence_payload(rule)

        self.assertEqual(1, len(result))
        self.assertEqual("valid", result[0]["text"])

    def test_evidence_payload_replaces_existing_llm_evidence_id_with_original_position(self):
        result = _evidence_payload(_rule(evidence=[{"text": "valid", "llm_evidence_id": "retrieval-id"}]))

        self.assertEqual(0, result[0]["llm_evidence_id"])

    def test_evidence_payload_adds_original_position_as_llm_evidence_id(self):
        rule = _rule(evidence=["not a dict", {"text": "valid"}])

        result = _evidence_payload(rule)

        self.assertEqual(1, result[0]["llm_evidence_id"])

    def test_classify_criterion_env_max_evidence_items_limits_prompt_payload(self):
        evidence = [{"text": "first"}, {"text": "second"}, {"text": "third"}]
        client = FakeClient(_config(enabled=True), LLMClientResponse(ok=True, text=_valid_response_text()))

        with patch.dict(os.environ, {"TENDER_LLM_MAX_EVIDENCE_ITEMS": "2"}, clear=False):
            classify_criterion(_rule(evidence=evidence), client)

        self.assertIn("first", client.last_prompt)
        self.assertIn("second", client.last_prompt)
        self.assertNotIn("third", client.last_prompt)

    def test_classify_criterion_env_max_evidence_chars_limits_prompt_payload(self):
        client = FakeClient(_config(enabled=True), LLMClientResponse(ok=True, text=_valid_response_text()))

        with patch.dict(os.environ, {"TENDER_LLM_MAX_EVIDENCE_CHARS": "100"}, clear=False):
            classify_criterion(_rule(evidence=[{"text": "x" * 150}]), client)

        self.assertIn(TRUNCATION_MARKER, client.last_prompt)
        self.assertNotIn("x" * 101, client.last_prompt)

    def test_env_positive_int_invalid_values_return_default(self):
        for value in ("", "abc", "0", "-1", "3.5"):
            with self.subTest(value=value):
                self.assertEqual(
                    DEFAULT_MAX_EVIDENCE_ITEMS,
                    _env_positive_int(value, DEFAULT_MAX_EVIDENCE_ITEMS, HARD_MAX_EVIDENCE_ITEMS),
                )

    def test_env_positive_int_accepts_spaces_and_plus_sign(self):
        self.assertEqual(2, _env_positive_int(" 2 ", DEFAULT_MAX_EVIDENCE_ITEMS, HARD_MAX_EVIDENCE_ITEMS))
        self.assertEqual(2, _env_positive_int("+2", DEFAULT_MAX_EVIDENCE_ITEMS, HARD_MAX_EVIDENCE_ITEMS))

    def test_env_positive_int_clamps_to_hard_max(self):
        self.assertEqual(
            HARD_MAX_EVIDENCE_ITEMS,
            _env_positive_int("999", DEFAULT_MAX_EVIDENCE_ITEMS, HARD_MAX_EVIDENCE_ITEMS),
        )
        self.assertEqual(
            HARD_MAX_EVIDENCE_CHARS,
            _env_positive_int("999999", DEFAULT_MAX_EVIDENCE_CHARS, HARD_MAX_EVIDENCE_CHARS),
        )

    def test_classify_criterion_logs_shadow_diagnostics_without_payloads(self):
        secret_evidence = "SECRET_EVIDENCE_TEXT"
        client = FakeClient(_config(enabled=True), LLMClientResponse(ok=True, text=_valid_response_text()))
        stderr = io.StringIO()

        with patch("sys.stderr", stderr):
            classify_criterion(_rule(evidence=[{"text": secret_evidence}]), client)

        log_output = stderr.getvalue()
        self.assertIn("LLM shadow classify", log_output)
        self.assertIn("rule_id=criterion-1", log_output)
        self.assertIn("evidence_items=1", log_output)
        self.assertIn("prompt_chars=", log_output)
        self.assertNotIn(secret_evidence, log_output)
        self.assertNotIn(client.last_prompt, log_output)

    def test_procurement_method_prompt_contains_electronic_auction_instruction(self):
        prompt = _rendered_prompt_for_rule(
            "procurement_method",
            "Способ закупки должен быть электронным аукционом.",
        )

        self.assertIn("электронный аукцион", prompt)

    def test_procurement_method_prompt_contains_electronic_document_flow_weak_evidence(self):
        prompt = _rendered_prompt_for_rule(
            "procurement_method",
            "Способ закупки должен быть электронным аукционом.",
        )

        self.assertIn("электронный документооборот", prompt)
        self.assertIn("электронный документ", prompt)

    def test_procurement_method_prompt_excludes_purchase_type_goods_terms(self):
        prompt = _rendered_prompt_for_rule(
            "procurement_method",
            "Способ закупки должен быть электронным аукционом.",
        )

        self.assertNotIn("поставка товара", prompt)
        self.assertNotIn("оказание услуг", prompt)
        self.assertNotIn("выполнение работ", prompt)

    def test_purchase_type_goods_prompt_excludes_electronic_auction_instruction(self):
        prompt = _rendered_prompt_for_rule(
            "purchase_type_goods",
            "Предмет закупки должен быть товаром.",
        )

        self.assertNotIn("электронный аукцион", prompt)
        self.assertNotIn("аукцион", prompt)

    def test_purchase_type_goods_prompt_excludes_procurement_only_rules(self):
        prompt = _rendered_prompt_for_rule(
            "purchase_type_goods",
            "Предмет закупки должен быть товаром.",
        )

        self.assertNotIn("электронный документооборот", prompt)
        self.assertNotIn("запрос предложений", prompt)
        self.assertNotIn("котировка", prompt)
        self.assertNotIn("способ закупки", prompt)

    def test_purchase_type_goods_prompt_contains_goods_delivery_instruction(self):
        prompt = _rendered_prompt_for_rule(
            "purchase_type_goods",
            "Предмет закупки должен быть товаром.",
        )

        self.assertIn("поставка товара", prompt)
        self.assertIn("кг", prompt)
        self.assertIn("штуки", prompt)

    def test_purchase_type_goods_prompt_contains_service_and_work_instructions(self):
        prompt = _rendered_prompt_for_rule(
            "purchase_type_goods",
            "Предмет закупки должен быть товаром.",
        )

        self.assertIn("оказание услуг", prompt)
        self.assertIn("выполнение работ", prompt)

    def test_rendered_prompt_replaces_rule_instructions_placeholder(self):
        prompt = _rendered_prompt_for_rule(
            "purchase_type_goods",
            "Предмет закупки должен быть товаром.",
        )

        self.assertNotIn("{{rule_instructions}}", prompt)

    def test_rendered_prompt_preserves_russian_utf8_text(self):
        prompt = _rendered_prompt_for_rule(
            "purchase_type_goods",
            "Предмет закупки должен быть товаром.",
            evidence=[{"text": "Поставка товара: масло моторное, 10 литров."}],
        )

        self.assertIn("Предмет закупки должен быть товаром.", prompt)
        self.assertIn("Поставка товара: масло моторное, 10 литров.", prompt)

    def test_purchase_type_goods_tender_2_regression_prompt_has_no_procurement_terms(self):
        prompt = _rendered_prompt_for_rule(
            "purchase_type_goods",
            "Предмет закупки должен быть товаром.",
            evidence=[{"text": "Масло моторное, 10 литров, позиция 1."}],
        )

        self.assertNotIn("аукцион", prompt)
        self.assertNotIn("электронный документооборот", prompt)
        self.assertNotIn("запрос предложений", prompt)
        self.assertNotIn("котировка", prompt)

    def test_msp_restriction_prompt_contains_sme_only_instruction(self):
        prompt = _rendered_prompt_for_rule(
            "msp_restriction",
            "Закупка только для субъектов МСП.",
        )

        self.assertIn("только для субъектов", prompt)

    def test_msp_restriction_prompt_distinguishes_preference_from_only(self):
        prompt = _rendered_prompt_for_rule(
            "msp_restriction",
            "Закупка только для субъектов МСП.",
        )

        self.assertIn("Преимущество", prompt)
        self.assertIn("не равно", prompt)
        self.assertIn("только для МСП", prompt)

    def test_msp_restriction_prompt_contains_negative_phrases(self):
        prompt = _rendered_prompt_for_rule(
            "msp_restriction",
            "Закупка только для субъектов МСП.",
        )

        self.assertIn("не предусмотрено", prompt)
        self.assertIn("не установлено", prompt)
        self.assertIn("любые лица", prompt)

    def test_msp_restriction_prompt_excludes_procurement_only_terms(self):
        prompt = _rendered_prompt_for_rule(
            "msp_restriction",
            "Закупка только для субъектов МСП.",
        )

        self.assertNotIn("электронный аукцион", prompt)

    def test_msp_restriction_prompt_excludes_purchase_type_goods_only_terms(self):
        prompt = _rendered_prompt_for_rule(
            "msp_restriction",
            "Закупка только для субъектов МСП.",
        )

        self.assertNotIn("поставка товара", prompt)
        self.assertNotIn("оказание услуг", prompt)
        self.assertNotIn("выполнение работ", prompt)

    def test_msp_restriction_prompt_preserves_russian_utf8_text(self):
        prompt = _rendered_prompt_for_rule(
            "msp_restriction",
            "Закупка только для субъектов МСП.",
            evidence=[{"text": "Участниками закупки могут быть только СМП."}],
        )

        self.assertIn("Закупка только для субъектов МСП.", prompt)
        self.assertIn("Участниками закупки могут быть только СМП.", prompt)

    def test_security_requirement_prompt_contains_bid_security_instruction(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению.",
        )

        self.assertIn("обеспечение заявки", prompt)

    def test_security_requirement_prompt_contains_contract_security_instruction(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению.",
        )

        self.assertIn("обеспечение исполнения контракта", prompt)

    def test_security_requirement_prompt_distinguishes_instruments_without_security_type(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению.",
        )

        self.assertIn("банковская гарантия", prompt)
        self.assertIn("без явного вида обеспечения не подтверждают критерий", prompt)

    def test_security_requirement_prompt_distinguishes_warranty_obligations(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению.",
        )

        self.assertIn("обеспечение гарантийных обязательств", prompt)
        self.assertIn("не равно обеспечению заявки", prompt)

    def test_security_requirement_prompt_contains_negative_phrases(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению.",
        )

        self.assertIn("не требуется", prompt)
        self.assertIn("не установлено", prompt)
        self.assertIn("не предусмотрено", prompt)

    def test_security_requirement_prompt_excludes_procurement_only_terms(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению.",
        )

        self.assertNotIn("электронный аукцион", prompt)

    def test_security_requirement_prompt_excludes_purchase_type_goods_only_terms(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению.",
        )

        self.assertNotIn("поставка товара", prompt)
        self.assertNotIn("оказание услуг", prompt)
        self.assertNotIn("выполнение работ", prompt)

    def test_security_requirement_prompt_excludes_msp_only_terms(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению.",
        )

        self.assertNotIn("только для субъектов МСП", prompt)

    def test_security_requirement_prompt_preserves_russian_utf8_text(self):
        prompt = _rendered_prompt_for_rule(
            "security_requirement",
            "Требования к обеспечению заявки.",
            evidence=[{"text": "Обеспечение заявки не требуется."}],
        )

        self.assertIn("Требования к обеспечению заявки.", prompt)
        self.assertIn("Обеспечение заявки не требуется.", prompt)

    def test_other_rule_id_gets_empty_rule_instructions(self):
        prompt = _rendered_prompt_for_rule(
            "delivery_deadline",
            "Срок поставки не более 30 дней.",
        )

        self.assertNotIn("{{rule_instructions}}", prompt)
        self.assertNotIn("электронный аукцион", prompt)
        self.assertNotIn("поставка товара", prompt)
        self.assertNotIn("оказание услуг", prompt)

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
