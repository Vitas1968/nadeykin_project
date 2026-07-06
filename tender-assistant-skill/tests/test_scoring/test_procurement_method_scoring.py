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
        "id": "procurement_method",
        "criterion": "Способ закупки — электронный аукцион",
        "priority": "medium",
    }


def _evidence(*texts):
    return [{"score": 1, "text": text} for text in texts]


class ProcurementMethodScoringTests(unittest.TestCase):
    def assertProcurementPassLowNoReview(self, result):
        self.assertEqual("pass", result["status"])
        self.assertEqual("low", result["risk"])
        self.assertFalse(result["human_review_required"])

    def assertProcurementFailHighReview(self, result):
        self.assertEqual("fail", result["status"])
        self.assertEqual("high", result["risk"])
        self.assertTrue(result["human_review_required"])

    def assertProcurementUnknownMediumReview(self, result):
        self.assertEqual("unknown", result["status"])
        self.assertEqual("medium", result["risk"])
        self.assertTrue(result["human_review_required"])

    def test_electronic_auction_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(_criterion(), evidence=_evidence("электронный аукцион"))

        self.assertProcurementPassLowNoReview(result)

    def test_request_for_proposals_is_fail_high_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("способ осуществления закупки: запрос предложений в электронной форме"),
        )

        self.assertProcurementFailHighReview(result)

    def test_open_request_for_proposals_is_fail_high_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "способ и предмет закупки: открытый запрос предложений на право заключения договора"
            ),
        )

        self.assertProcurementFailHighReview(result)

    def test_request_for_quotations_is_fail_high_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("запрос котировок в электронной форме"),
        )

        self.assertProcurementFailHighReview(result)

    def test_competition_in_electronic_form_is_fail_high_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("конкурс в электронной форме"),
        )

        self.assertProcurementFailHighReview(result)

    def test_weak_electronic_platform_evidence_is_unknown_medium_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("оператор электронной площадки"),
        )

        self.assertProcurementUnknownMediumReview(result)

    def test_no_evidence_is_unknown_medium_review(self):
        for evidence in ([], _evidence("срок поставки товара составляет 30 дней")):
            with self.subTest(evidence=evidence):
                result = rule_engine.evaluate_criterion(_criterion(), evidence=evidence)

                self.assertProcurementUnknownMediumReview(result)

    def test_competition_false_positive_phrases_do_not_fail_or_conflict(self):
        phrases = [
            "конкурсная документация",
            "конкурсной комиссии",
            "конкурсного производства",
        ]

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                result = rule_engine.evaluate_criterion(_criterion(), evidence=_evidence(phrase))

                self.assertNotIn(result["status"], {"fail", "conflict"})

    def test_auction_with_template_list_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "способ закупки | аукцион в электронной форме участниками которого могут быть только субъекты мсп.",
                (
                    "указать один из следующих вариантов первой части заявки / второй части заявки - "
                    "для конкурса аукциона запроса предложений предложение о цене договора - "
                    "для конкурса запроса предложений заявки - для запроса котировок"
                ),
            ),
        )

        self.assertProcurementPassLowNoReview(result)

    def test_auction_with_template_deletion_instruction_is_pass_low_no_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "способ закупки | аукцион в электронной форме участниками которого могут быть только субъекты мсп.",
                (
                    "дополнение в случае конкурса запроса предложений иначе при аукционе "
                    "запросе котировок вся строка 3 таблицы удаляется"
                ),
            ),
        )

        self.assertProcurementPassLowNoReview(result)

    def test_template_instruction_patterns_do_not_fail_or_conflict_individually(self):
        phrases = [
            "указать один из следующих вариантов заявки - для запроса котировок",
            "для конкурса аукциона запроса предложений",
            "дополнение в случае конкурса запроса предложений",
            "иначе при аукционе запросе котировок",
            "запрос котировок вся строка 12 таблицы удаляется",
        ]

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                result = rule_engine.evaluate_criterion(_criterion(), evidence=_evidence(phrase))

                self.assertProcurementUnknownMediumReview(result)

    def test_request_for_proposals_with_method_wording_is_fail_high_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("Способ закупки указан как запрос предложений."),
        )

        self.assertProcurementFailHighReview(result)

    def test_legacy_auction_wordings_are_pass_low_no_review(self):
        phrases = [
            "Закупка проводится как электронный аукцион.",
            "Процедура является аукционом в электронной форме.",
            "Документация размещена для проведения электронного аукциона.",
        ]

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                result = rule_engine.evaluate_criterion(_criterion(), evidence=_evidence(phrase))

                self.assertProcurementPassLowNoReview(result)

    def test_auction_and_request_for_proposals_is_conflict_high_review(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("электронный аукцион", "запрос предложений в электронной форме"),
        )

        self.assertEqual("conflict", result["status"])
        self.assertEqual("high", result["risk"])
        self.assertTrue(result["human_review_required"])

    def test_open_request_for_proposals_has_single_non_auction_concern(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("открытый запрос предложений"),
        )

        self.assertEqual(1, result["evidence_concerns"].count("procurement_method_non_auction_evidence"))


if __name__ == "__main__":
    unittest.main()
