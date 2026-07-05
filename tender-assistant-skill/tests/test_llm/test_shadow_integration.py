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

    def test_shadow_verdict_cannot_change_deterministic_fields_or_scenario(self):
        core_rule = _rule("subject_okpd2_oil")
        procurement_rule = _rule("procurement_method", status="pass", risk="low")
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


if __name__ == "__main__":
    unittest.main()
