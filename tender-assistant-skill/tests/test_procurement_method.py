import unittest

from scoring import rule_engine


def _criterion(rule_id="procurement_method"):
    return {
        "id": rule_id,
        "criterion": "Способ закупки — электронный аукцион",
        "priority": "medium",
    }


def _evidence(text, score=2.4):
    return [{"score": score, "text": text}]


class ProcurementMethodTests(unittest.TestCase):
    def test_procurement_method_passes_on_explicit_electronic_auction(self):
        confirming_texts = [
            "Закупка проводится как электронный аукцион.",
            "Процедура является аукционом в электронной форме.",
        ]

        for text in confirming_texts:
            with self.subTest(text=text):
                result = rule_engine.evaluate_criterion(_criterion(), evidence=_evidence(text))

                self.assertEqual("pass", result["status"])

    def test_procurement_method_passes_on_case_variant(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("Документация размещена для проведения электронного аукциона."),
        )

        self.assertEqual("pass", result["status"])

    def test_procurement_method_unknown_for_generic_electronic_document_evidence(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=[
                {
                    "score": 2.4,
                    "text": (
                        "Заявка оформляется в виде электронного документа, подписанного КЭП. "
                        "Контракт ведется через электронный документооборот, электронную почту "
                        "и ПИК ЕАСУЗ."
                    ),
                }
            ],
        )

        self.assertNotEqual("pass", result["status"])
        self.assertEqual("unknown", result["status"])
        self.assertTrue(result["human_review_required"])
        self.assertTrue(result["comment"])
        self.assertIn("электронный аукцион", result["comment"])

    def test_procurement_method_fail_keeps_unconfirmed_evidence_comment(self):
        criterion = _criterion()
        criterion["negative_keywords"] = ["запрос предложений"]

        result = rule_engine.evaluate_criterion(
            criterion,
            evidence=[
                {
                    "score": 2.4,
                    "text": (
                        "Заявка оформляется в виде электронного документа, подписанного КЭП. "
                        "Способ закупки указан как запрос предложений."
                    ),
                }
            ],
        )

        self.assertEqual("fail", result["status"])
        self.assertTrue(result["human_review_required"])
        self.assertIn("электронный аукцион", result["comment"])

    def test_other_criteria_keep_score_based_confirmation(self):
        result = rule_engine.evaluate_criterion(
            _criterion(rule_id="delivery_terms"),
            evidence=_evidence("Поставка товара выполняется в течение 30 дней."),
        )

        self.assertEqual("pass", result["status"])


if __name__ == "__main__":
    unittest.main()
