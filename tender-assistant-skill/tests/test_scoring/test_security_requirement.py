from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scoring import rule_engine


def _criterion():
    return {
        "id": "security_requirement",
        "criterion": "Обязательство по обеспечению участия в тендере или обеспечения по договору",
        "priority": "high",
        "negative_terms": [
            "обеспечение заявки на участие в закупке не требуется",
            "обеспечение исполнения договора не требуется",
            "обеспечение исполнения контракта не требуется",
            "обеспечение исполнения обязательств по договору не требуется",
        ],
    }


def _evidence(*texts):
    return [{"score": 1, "text": text} for text in texts]


def _non_confirming_evidence(text):
    return [{"score": 0, "text": text}]


def _security_requirement_from_config():
    criteria_path = Path(__file__).resolve().parents[2] / "config" / "criteria.yaml"
    criteria = rule_engine._load_criteria_without_yaml(criteria_path)
    return next(item for item in criteria if item.get("id") == "security_requirement")


class SecurityRequirementTests(unittest.TestCase):
    def assertSecurityPassLowNoReview(self, result):
        self.assertEqual("pass", result["status"])
        self.assertEqual("low", result["risk"])
        self.assertFalse(result["human_review_required"])
        self.assertEqual([], result["evidence_concerns"])

    def test_security_requirement_negative_phrases_are_pass_low_no_review(self):
        phrases = [
            "обеспечение заявки на участие в закупке не требуется",
            "обеспечение исполнения договора не требуется",
            "обеспечение исполнения контракта не требуется",
            "обеспечение исполнения обязательств по договору не требуется",
        ]

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                result = rule_engine.evaluate_criterion(_criterion(), evidence=_evidence(phrase))

                self.assertSecurityPassLowNoReview(result)
                self.assertEqual([phrase], [item["text"] for item in result["evidence"]])

    def test_security_requirement_negative_phrase_is_pass_low_in_realistic_context(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "5.2 Обеспечение исполнения контракта не требуется "
                "в связи с наличием банковской гарантии"
            ),
        )

        self.assertSecurityPassLowNoReview(result)
        self.assertEqual(1, len(result["evidence"]))

    def test_security_requirement_negative_phrase_is_pass_low_across_whitespace(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("Обеспечение исполнения\n\nконтракта   не\tтребуется"),
        )

        self.assertSecurityPassLowNoReview(result)

    def test_security_requirement_bid_security_pipe_negative_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("обеспечение заявки на участие в закупке | не требуется"),
        )

        self.assertSecurityPassLowNoReview(result)

    def test_security_requirement_contract_security_pipe_negative_with_punctuation_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("обеспечение исполнения договора | не требуется."),
        )

        self.assertSecurityPassLowNoReview(result)

    def test_security_requirement_negative_evidence_with_generic_conditionals_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "обеспечение заявки на участие в закупке | не требуется",
                "обеспечение исполнения договора | не требуется.",
                "в случае выбора участником обеспечения заявки банковской гарантией",
                "если подразделом предусмотрена обязанность предоставить обеспечение",
            ),
        )

        self.assertSecurityPassLowNoReview(result)

    def test_security_requirement_contract_security_negative_without_pipe_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("обеспечение исполнения договора не требуется"),
        )

        self.assertSecurityPassLowNoReview(result)

    def test_security_requirement_contract_security_not_established_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("обеспечение исполнения контракта не установлено"),
        )

        self.assertSecurityPassLowNoReview(result)

    def test_security_requirement_short_and_reversed_negative_phrases_are_pass_low_no_review(self):
        phrases = [
            "обеспечение участия не требуется",
            "обеспечение исполнения не требуется",
            "обеспечение договора не требуется",
            "не требуется обеспечение",
            "не установлено обеспечение",
            "не предусмотрено обеспечение",
        ]

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                result = rule_engine.evaluate_criterion(_criterion(), evidence=_evidence(phrase))

                self.assertSecurityPassLowNoReview(result)

    def test_security_requirement_non_confirming_negative_evidence_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_non_confirming_evidence("не требуется обеспечение"),
        )

        self.assertSecurityPassLowNoReview(result)

    def test_security_requirement_numeric_conflict_is_high_risk_human_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "обеспечение исполнения договора не требуется",
                "размер обеспечения исполнения договора составляет 5%",
            ),
        )

        self.assertEqual("conflict", result["status"])
        self.assertEqual("high", result["risk"])
        self.assertTrue(result["human_review_required"])

    def test_security_requirement_non_numeric_conflict_is_high_risk_human_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "обеспечение исполнения договора не требуется",
                "обеспечение заявки установлено",
            ),
        )

        self.assertEqual("conflict", result["status"])
        self.assertEqual("high", result["risk"])
        self.assertTrue(result["human_review_required"])

    def test_security_requirement_conflict_uses_conflicting_concern_only(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "обеспечение исполнения договора не требуется",
                "обеспечение заявки установлено",
            ),
        )

        self.assertIn("security_requirement_conflicting_evidence", result["evidence_concerns"])
        self.assertNotIn("security_requirement_negative_evidence", result["evidence_concerns"])

    def test_security_requirement_negative_terms_do_not_use_pipe_separator(self):
        terms = rule_engine.extract_negative_terms(_security_requirement_from_config())

        self.assertTrue(terms)
        self.assertFalse(any("|" in term for term in terms))


if __name__ == "__main__":
    unittest.main()
