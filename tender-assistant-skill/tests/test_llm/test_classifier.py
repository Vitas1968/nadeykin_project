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
