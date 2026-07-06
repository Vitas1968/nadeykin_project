import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run as pipeline_run


def _config(enabled):
    return SimpleNamespace(enabled=enabled, provider="fake-provider", model="fake-model")


def _rule(rule_id, status="pass", risk="low", human_review_required=False, comment="deterministic"):
    return {
        "id": rule_id,
        "criterion": f"{rule_id} criterion",
        "priority": "medium",
        "evidence": [{"text": f"{rule_id} evidence"}],
        "status": status,
        "risk": risk,
        "human_review_required": human_review_required,
        "comment": comment,
        "evidence_concerns": [],
        "explicit_dealer_indicator": False,
    }


def _result(*rules):
    return {"rules": list(rules)}


def _deterministic_rules(result):
    return [
        {key: copy.deepcopy(value) for key, value in rule.items() if key != "llm_verdict"}
        for rule in result["rules"]
    ]


def _scenario(result):
    return pipeline_run.classify_scenario({"rules": copy.deepcopy(result["rules"])})


class ShadowIntegrationTests(unittest.TestCase):
    def _assert_security_evidence_allows_classifier(self, evidence):
        security_rule = _rule("security_requirement")
        security_rule["evidence"] = evidence if isinstance(evidence, list) else [{"text": evidence}]
        result = _result(security_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(security_rule)
        self.assertEqual(llm_verdict, security_rule["llm_verdict"])

    def _assert_security_evidence_skips_classifier(self, text):
        security_rule = _rule("security_requirement")
        security_rule["evidence"] = [{"text": text}]
        result = _result(security_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        llm_verdict = security_rule["llm_verdict"]
        self.assertEqual("skipped", llm_verdict["invocation_status"])
        self.assertEqual("unknown", llm_verdict["verdict"])
        self.assertEqual("low", llm_verdict["confidence"])
        self.assertTrue(llm_verdict["human_review_required"])
        self.assertEqual(pipeline_run.SECURITY_REQUIREMENT_SKIP_REASON, llm_verdict["reason"])

    def _assert_purchase_type_goods_evidence_skips_as_redundant(self, evidence):
        purchase_rule = _rule("purchase_type_goods")
        purchase_rule["evidence"] = evidence if isinstance(evidence, list) else [{"text": evidence}]
        result = _result(purchase_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        llm_verdict = purchase_rule["llm_verdict"]
        self.assertEqual("skipped", llm_verdict["invocation_status"])
        self.assertEqual("pass", llm_verdict["verdict"])
        self.assertEqual("high", llm_verdict["confidence"])
        self.assertFalse(llm_verdict["human_review_required"])
        self.assertFalse(llm_verdict["conflicts_with_rule"])
        self.assertEqual(pipeline_run.PURCHASE_TYPE_GOODS_REDUNDANT_SKIP_REASON, llm_verdict["reason"])
        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))

    def _assert_purchase_type_evidence_allows_classifier(self, evidence, llm_verdict=None):
        purchase_rule = _rule("purchase_type_goods")
        purchase_rule["evidence"] = evidence if isinstance(evidence, list) else [{"text": evidence}]
        result = _result(purchase_rule)
        llm_verdict = llm_verdict or {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(purchase_rule)
        self.assertEqual(llm_verdict, purchase_rule["llm_verdict"])

    def test_disabled_mode_skips_without_llm_verdict_or_classifier_call(self):
        core_rule = _rule("subject_okpd2_oil")
        procurement_rule = _rule("procurement_method")
        result = _result(core_rule, procurement_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(False)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertNotIn("llm_verdict", procurement_rule)
        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))

    def test_enabled_mode_calls_llm_only_for_procurement_method(self):
        core_rule = _rule("subject_okpd2_oil")
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [{"text": "Способ определения поставщика: электронный аукцион."}]
        other_rule = _rule("delivery_terms")
        result = _result(core_rule, procurement_rule, other_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(procurement_rule)
        self.assertEqual(llm_verdict, procurement_rule["llm_verdict"])
        self.assertNotIn("llm_verdict", core_rule)
        self.assertNotIn("llm_verdict", other_rule)

    def test_weak_procurement_evidence_skips_classifier_with_skipped_verdict(self):
        core_rule = _rule("subject_okpd2_oil")
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [
            {"text": "Заявка оформляется в виде электронного документа, подписанного КЭП."}
        ]
        result = _result(core_rule, procurement_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        llm_verdict = procurement_rule["llm_verdict"]
        self.assertEqual("skipped", llm_verdict["invocation_status"])
        self.assertEqual("unknown", llm_verdict["verdict"])
        self.assertEqual("low", llm_verdict["confidence"])
        self.assertTrue(llm_verdict["human_review_required"])
        self.assertEqual([], llm_verdict["supporting_evidence_ids"])
        self.assertFalse(llm_verdict["conflicts_with_rule"])
        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))

    def test_electronic_platform_weak_evidence_skips_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [
            {"text": "Заявка подается через оператора электронной площадки в форме электронного документа."}
        ]
        result = _result(procurement_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertEqual("skipped", procurement_rule["llm_verdict"]["invocation_status"])

    def test_explicit_electronic_auction_evidence_allows_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [{"text": "Способ определения поставщика: электронный аукцион."}]
        result = _result(procurement_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(procurement_rule)

    def test_explicit_request_for_proposals_evidence_allows_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [{"text": "Способ определения поставщика: запрос предложений в электронной форме."}]
        result = _result(procurement_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "fail", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(procurement_rule)

    def test_explicit_quotation_genitive_plural_evidence_allows_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [{"text": "Проведение котировок осуществляется в электронной форме."}]
        result = _result(procurement_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "fail", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(procurement_rule)

    def test_snippet_only_explicit_evidence_allows_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [{"snippet": "Способ определения поставщика: электронный аукцион."}]
        result = _result(procurement_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(procurement_rule)

    def test_block_text_only_explicit_evidence_allows_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [{"block": {"text": "Способ определения поставщика: электронный аукцион."}}]
        result = _result(procurement_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(procurement_rule)

    def test_empty_procurement_evidence_skips_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = []
        result = _result(procurement_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertEqual("skipped", procurement_rule["llm_verdict"]["invocation_status"])

    def test_auction_word_form_in_electronic_form_allows_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [{"text": "Закупка проводится путём аукциона в электронной форме."}]
        result = _result(procurement_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(procurement_rule)

    def test_ambiguous_electronic_platform_without_auction_skips_classifier(self):
        procurement_rule = _rule("procurement_method")
        procurement_rule["evidence"] = [
            {"text": "Подача заявок осуществляется через электронную площадку в форме, установленной для конкурентных процедур."}
        ]
        result = _result(procurement_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertEqual("skipped", procurement_rule["llm_verdict"]["invocation_status"])

    def test_shadow_verdict_cannot_change_deterministic_fields_or_scenario(self):
        core_rule = _rule("subject_okpd2_oil")
        procurement_rule = _rule("procurement_method", status="pass", risk="low")
        procurement_rule["evidence"] = [{"text": "Способ определения поставщика: электронный аукцион."}]
        result = _result(core_rule, procurement_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        def fake_classify(rule):
            rule["status"] = "fail"
            rule["risk"] = "high"
            rule["human_review_required"] = True
            rule["comment"] = "changed by fake llm"
            rule["evidence"] = [{"text": "changed by fake llm"}]
            return {
                "invocation_status": "ok",
                "verdict": "fail",
                "conflicts_with_rule": True,
                "warnings": [],
            }

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            side_effect=fake_classify,
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))
        self.assertEqual("fail", procurement_rule["llm_verdict"]["verdict"])
        self.assertTrue(procurement_rule["llm_verdict"]["conflicts_with_rule"])
        self.assertTrue(procurement_rule["llm_verdict"]["warnings"])

    def test_llm_exception_becomes_error_verdict_without_changing_deterministic_fields(self):
        core_rule = _rule("subject_okpd2_oil")
        procurement_rule = _rule("procurement_method", status="unknown", risk="medium")
        procurement_rule["evidence"] = [{"text": "Способ определения поставщика: электронный аукцион."}]
        result = _result(core_rule, procurement_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            side_effect=RuntimeError("fake failure"),
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))
        self.assertEqual("error", procurement_rule["llm_verdict"]["invocation_status"])
        self.assertEqual("RuntimeError", procurement_rule["llm_verdict"]["error_type"])

    def test_missing_procurement_method_skips_without_adding_llm_verdict(self):
        core_rule = _rule("subject_okpd2_oil")
        other_rule = _rule("delivery_terms")
        result = _result(core_rule, other_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertFalse(any("llm_verdict" in rule for rule in result["rules"]))
        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))

    def test_disabled_mode_skips_purchase_type_goods_without_llm_verdict(self):
        purchase_rule = _rule("purchase_type_goods")
        purchase_rule["evidence"] = [{"text": "Поставка товара осуществляется по заявкам заказчика."}]
        result = _result(purchase_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(False)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertNotIn("llm_verdict", purchase_rule)
        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))

    def test_missing_purchase_type_goods_skips_without_adding_llm_verdict(self):
        core_rule = _rule("subject_okpd2_oil")
        other_rule = _rule("delivery_terms")
        result = _result(core_rule, other_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertFalse(any("llm_verdict" in rule for rule in result["rules"]))

    def test_weak_purchase_type_quantity_evidence_skips_classifier(self):
        purchase_rule = _rule("purchase_type_goods")
        # This remains weak evidence: current goods patterns require explicit supply/transfer phrasing,
        # not a quantity phrase with "товара" alone.
        purchase_rule["evidence"] = [{"text": "Количество поставляемого товара: 100 литров."}]
        result = _result(purchase_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        llm_verdict = purchase_rule["llm_verdict"]
        self.assertEqual("skipped", llm_verdict["invocation_status"])
        self.assertEqual("unknown", llm_verdict["verdict"])
        self.assertEqual("low", llm_verdict["confidence"])
        self.assertTrue(llm_verdict["human_review_required"])
        self.assertEqual(pipeline_run.PURCHASE_TYPE_GOODS_WEAK_SKIP_REASON, llm_verdict["reason"])
        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))

    def test_empty_purchase_type_goods_evidence_skips_classifier(self):
        purchase_rule = _rule("purchase_type_goods")
        purchase_rule["evidence"] = []
        result = _result(purchase_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertEqual("skipped", purchase_rule["llm_verdict"]["invocation_status"])

    def test_purchase_type_goods_only_explicit_supply_skips_classifier_as_intentional_tradeoff(self):
        """Intentional coverage/cost trade-off: clear goods-only evidence skips redundant LLM shadow."""
        phrases = (
            "Поставка товара осуществляется по заявкам заказчика.",
            "Поставка товара должна осуществляться в сроки.",
            "Передача товара.",
        )

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self._assert_purchase_type_goods_evidence_skips_as_redundant(phrase)

    def test_purchase_type_goods_only_supplier_phrase_skips_classifier(self):
        self._assert_purchase_type_goods_evidence_skips_as_redundant("Поставщик поставляет товар.")

    def test_purchase_type_goods_only_buyer_accepts_goods_skips_classifier(self):
        self._assert_purchase_type_goods_evidence_skips_as_redundant("Покупатель принимает товар.")

    def test_strong_purchase_type_service_work_evidence_allows_classifier(self):
        phrases = (
            "Оказание услуг по замене масла в оборудовании.",
            "Выполнение работ.",
            "Техническое обслуживание.",
            "Ремонт оборудования.",
            "Монтаж оборудования.",
        )

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self._assert_purchase_type_evidence_allows_classifier(
                    phrase,
                    {"invocation_status": "ok", "verdict": "fail", "warnings": []},
                )

    def test_purchase_type_service_work_provision_evidence_allows_classifier(self):
        self._assert_purchase_type_evidence_allows_classifier(
            "Предоставление услуг по техническому обслуживанию оборудования.",
            {"invocation_status": "ok", "verdict": "fail", "warnings": []},
        )

    def test_conflict_purchase_type_goods_and_service_evidence_allows_classifier(self):
        purchase_rule = _rule("purchase_type_goods")
        purchase_rule["evidence"] = [
            {"text": "Поставка товара осуществляется партиями."},
            {"text": "Также предусмотрен монтаж оборудования."},
        ]
        result = _result(purchase_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "unknown", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(purchase_rule)

    def test_conflict_purchase_type_goods_and_service_in_one_item_allows_classifier(self):
        self._assert_purchase_type_evidence_allows_classifier(
            "Поставка товара и оказание услуг по монтажу.",
            {"invocation_status": "ok", "verdict": "unknown", "warnings": []},
        )

    def test_purchase_type_goods_only_tender_2_evidence_set_skips_classifier_as_redundant(self):
        self._assert_purchase_type_goods_evidence_skips_as_redundant(
            [
                {"text": "Поставка товара осуществляется по заявкам заказчика."},
                {"text": "Поставка товара должна осуществляться в сроки."},
                {"text": "Поставщик поставляет товар."},
            ]
        )

    def test_purchase_type_goods_snippet_fallback_skips_classifier(self):
        self._assert_purchase_type_goods_evidence_skips_as_redundant(
            [{"snippet": "Покупатель принимает товар после поставки."}]
        )

    def test_purchase_type_goods_block_text_fallback_skips_classifier(self):
        self._assert_purchase_type_goods_evidence_skips_as_redundant(
            [{"block": {"text": "Передача товара подтверждается накладной."}}]
        )

    def test_purchase_type_goods_llm_exception_becomes_error_verdict(self):
        purchase_rule = _rule("purchase_type_goods", status="unknown", risk="medium")
        purchase_rule["evidence"] = [{"text": "Оказание услуг по замене масла в оборудовании."}]
        result = _result(purchase_rule)
        deterministic_before = _deterministic_rules(result)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            side_effect=RuntimeError("fake failure"),
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual("error", purchase_rule["llm_verdict"]["invocation_status"])
        self.assertEqual("RuntimeError", purchase_rule["llm_verdict"]["error_type"])

    def test_purchase_type_goods_shadow_verdict_cannot_change_deterministic_fields(self):
        purchase_rule = _rule("purchase_type_goods", status="pass", risk="low")
        purchase_rule["evidence"] = [{"text": "Оказание услуг по замене масла в оборудовании."}]
        result = _result(purchase_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        def fake_classify(rule):
            rule["status"] = "fail"
            rule["risk"] = "high"
            rule["human_review_required"] = True
            rule["comment"] = "changed by fake llm"
            rule["evidence"] = [{"text": "changed by fake llm"}]
            return {
                "invocation_status": "ok",
                "verdict": "fail",
                "conflicts_with_rule": True,
                "warnings": [],
            }

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            side_effect=fake_classify,
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))
        self.assertEqual("fail", purchase_rule["llm_verdict"]["verdict"])
        self.assertTrue(purchase_rule["llm_verdict"]["warnings"])

    def test_purchase_type_goods_shadow_verdict_keeps_existing_scenario_result(self):
        purchase_rule = _rule("purchase_type_goods")
        purchase_rule["evidence"] = [{"text": "Поставка товара осуществляется по заявкам заказчика."}]
        result = _result(purchase_rule)
        result["scenario_result"] = {"scenario": "unchanged"}
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual({"scenario": "unchanged"}, result["scenario_result"])

    def test_strong_msp_only_restriction_allows_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Закупка только для субъектов малого и среднего предпринимательства."}]
        result = _result(msp_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(msp_rule)
        self.assertEqual(llm_verdict, msp_rule["llm_verdict"])

    def test_strong_msp_only_smp_participants_allows_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Участниками закупки могут быть только СМП."}]
        result = _result(msp_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(msp_rule)

    def test_strong_msp_among_small_business_allows_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Закупка проводится среди субъектов малого предпринимательства."}]
        result = _result(msp_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(msp_rule)

    def test_negative_msp_not_provided_allows_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Ограничение участия субъектов МСП не предусмотрено."}]
        result = _result(msp_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "fail", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(msp_rule)

    def test_negative_not_smp_purchase_allows_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Закупка не является закупкой у СМП."}]
        result = _result(msp_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "fail", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(msp_rule)

    def test_negative_any_participants_allowed_allows_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Участниками могут быть любые лица."}]
        result = _result(msp_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "fail", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(msp_rule)

    def test_weak_msp_preference_skips_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Преимущество субъектам МСП предоставляется в установленном порядке."}]
        result = _result(msp_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertEqual("skipped", msp_rule["llm_verdict"]["invocation_status"])
        self.assertEqual("unknown", msp_rule["llm_verdict"]["verdict"])
        self.assertTrue(msp_rule["llm_verdict"]["human_review_required"])
        self.assertEqual(pipeline_run.MSP_RESTRICTION_SKIP_REASON, msp_rule["llm_verdict"]["reason"])

    def test_weak_msp_marker_skips_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Субъекты МСП указывают сведения в составе заявки."}]
        result = _result(msp_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertEqual("skipped", msp_rule["llm_verdict"]["invocation_status"])

    def test_weak_msp_declaration_skips_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Декларация о принадлежности к субъектам МСП подается участником."}]
        result = _result(msp_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertEqual("skipped", msp_rule["llm_verdict"]["invocation_status"])

    def test_dealer_partner_without_sme_context_skips_classifier(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Официальный дилер и партнер производителя предоставляет документы."}]
        result = _result(msp_rule)

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=SimpleNamespace(invocation_status="unexpected"),
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_not_called()
        self.assertEqual("skipped", msp_rule["llm_verdict"]["invocation_status"])

    def test_mixed_msp_positive_and_negative_in_one_item_allows_conflict_classifier_verdict(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [
            {"text": "Участниками закупки могут быть только СМП; ограничение участия не предусмотрено."}
        ]
        result = _result(msp_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "conflict", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(msp_rule)
        self.assertEqual("conflict", msp_rule["llm_verdict"]["verdict"])

    def test_msp_positive_and_negative_in_different_items_allows_conflict_classifier_verdict(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [
            {"text": "Участниками закупки могут быть только СМП."},
            {"text": "Ограничение участия не установлено."},
        ]
        result = _result(msp_rule)
        llm_verdict = {"invocation_status": "ok", "verdict": "conflict", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ) as classify_mock:
            pipeline_run._apply_llm_shadow_verdict(result)

        classify_mock.assert_called_once_with(msp_rule)
        self.assertEqual("conflict", msp_rule["llm_verdict"]["verdict"])

    def test_msp_shadow_verdict_cannot_change_deterministic_fields(self):
        msp_rule = _rule("msp_restriction", status="pass", risk="low")
        msp_rule["evidence"] = [{"text": "Участниками закупки могут быть только СМП."}]
        result = _result(msp_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        def fake_classify(rule):
            rule["status"] = "fail"
            rule["risk"] = "high"
            rule["human_review_required"] = True
            rule["comment"] = "changed by fake llm"
            rule["evidence"] = [{"text": "changed by fake llm"}]
            return {
                "invocation_status": "ok",
                "verdict": "fail",
                "conflicts_with_rule": True,
                "warnings": [],
            }

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            side_effect=fake_classify,
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))
        self.assertEqual("fail", msp_rule["llm_verdict"]["verdict"])
        self.assertTrue(msp_rule["llm_verdict"]["warnings"])

    def test_msp_shadow_verdict_keeps_existing_scenario_result(self):
        msp_rule = _rule("msp_restriction")
        msp_rule["evidence"] = [{"text": "Участниками закупки могут быть только СМП."}]
        result = _result(msp_rule)
        result["scenario_result"] = {"scenario": "unchanged"}
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual({"scenario": "unchanged"}, result["scenario_result"])

    def test_strong_security_requirement_positive_evidence_allows_classifier(self):
        phrases = (
            "обеспечение заявки требуется",
            "размер обеспечения заявки составляет 1%",
            "размер обеспечения исполнения контракта составляет 5%",
            "обеспечение исполнения контракта предоставляется в форме независимой гарантии",
            "обеспечение исполнения контракта вносится денежными средствами",
            "обеспечение исполнения контракта предоставить независимой гарантией",
            "обеспечение исполнения договора составляет 5%",
        )

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self._assert_security_evidence_allows_classifier(phrase)

    def test_security_requirement_negative_evidence_allows_classifier(self):
        phrases = (
            "обеспечение заявки не требуется",
            "обеспечение исполнения контракта не требуется",
            "обеспечение исполнения обязательств по договору не предусмотрено",
        )

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self._assert_security_evidence_allows_classifier(phrase)

    def test_weak_security_requirement_evidence_skips_classifier(self):
        phrases = (
            "банковская гарантия",
            "денежные средства",
            "размер обеспечения",
            "антидемпинговые меры",
            "обеспечение гарантийных обязательств",
            "обеспечение исполнения контракта",
            "обеспечение заявки, независимая гарантия",
            "обеспечения заявки на участие в которой выдана независимая гарантия",
            "предоставить новое обеспечение исполнения контракта",
            "предоставить новое обеспечение исполнения контракта не позднее 1 месяца со дня уведомления",
            "в случае изменения независимой гарантии предоставить новое обеспечение исполнения контракта",
            "банковская гарантия предоставляется в размере 500000 руб.",
        )

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self._assert_security_evidence_skips_classifier(phrase)

    def test_mixed_security_requirement_positive_and_negative_in_one_item_allows_classifier(self):
        self._assert_security_evidence_allows_classifier(
            "обеспечение заявки требуется; обеспечение исполнения контракта не требуется"
        )

    def test_security_requirement_positive_and_negative_in_different_items_allows_classifier(self):
        self._assert_security_evidence_allows_classifier(
            [
                {"text": "обеспечение заявки требуется"},
                {"text": "обеспечение исполнения контракта не требуется"},
            ]
        )

    def test_security_requirement_shadow_verdict_cannot_change_deterministic_fields(self):
        security_rule = _rule("security_requirement", status="pass", risk="low")
        security_rule["evidence"] = [{"text": "обеспечение заявки требуется"}]
        result = _result(security_rule)
        deterministic_before = _deterministic_rules(result)
        scenario_before = _scenario(result)

        def fake_classify(rule):
            rule["status"] = "fail"
            rule["risk"] = "high"
            rule["human_review_required"] = True
            rule["comment"] = "changed by fake llm"
            rule["evidence"] = [{"text": "changed by fake llm"}]
            return {
                "invocation_status": "ok",
                "verdict": "fail",
                "conflicts_with_rule": True,
                "warnings": [],
            }

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            side_effect=fake_classify,
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual(deterministic_before, _deterministic_rules(result))
        self.assertEqual(scenario_before, _scenario(result))
        self.assertEqual("fail", security_rule["llm_verdict"]["verdict"])
        self.assertTrue(security_rule["llm_verdict"]["warnings"])

    def test_security_requirement_shadow_verdict_keeps_existing_scenario_result(self):
        security_rule = _rule("security_requirement")
        security_rule["evidence"] = [{"text": "обеспечение заявки требуется"}]
        result = _result(security_rule)
        result["scenario_result"] = {"scenario": "unchanged"}
        llm_verdict = {"invocation_status": "ok", "verdict": "pass", "warnings": []}

        with patch.object(pipeline_run, "load_config_from_env", return_value=_config(True)), patch.object(
            pipeline_run,
            "classify_criterion",
            return_value=llm_verdict,
        ):
            pipeline_run._apply_llm_shadow_verdict(result)

        self.assertEqual({"scenario": "unchanged"}, result["scenario_result"])


if __name__ == "__main__":
    unittest.main()
