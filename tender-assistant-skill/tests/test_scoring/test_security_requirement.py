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


def _evidence(text):
    return [{"score": 0, "text": text}]


def _security_requirement_from_config():
    criteria_path = Path(__file__).resolve().parents[2] / "config" / "criteria.yaml"
    criteria = rule_engine._load_criteria_without_yaml(criteria_path)
    return next(item for item in criteria if item.get("id") == "security_requirement")


class SecurityRequirementTests(unittest.TestCase):
    def test_security_requirement_negative_phrases_are_detected(self):
        phrases = [
            "обеспечение заявки на участие в закупке не требуется",
            "обеспечение исполнения договора не требуется",
            "обеспечение исполнения контракта не требуется",
            "обеспечение исполнения обязательств по договору не требуется",
        ]

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                result = rule_engine.evaluate_criterion(_criterion(), evidence=_evidence(phrase))

                self.assertEqual("fail", result["status"])
                self.assertEqual([phrase], [item["text"] for item in result["evidence"]])

    def test_security_requirement_negative_phrase_is_detected_in_realistic_context(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence(
                "5.2 Обеспечение исполнения контракта не требуется "
                "в связи с наличием банковской гарантии"
            ),
        )

        self.assertEqual("fail", result["status"])
        self.assertEqual(1, len(result["evidence"]))

    def test_security_requirement_negative_phrase_is_detected_across_whitespace(self):
        result = rule_engine.evaluate_criterion(
            _criterion(),
            evidence=_evidence("Обеспечение исполнения\n\nконтракта   не\tтребуется"),
        )

        self.assertEqual("fail", result["status"])

    def test_security_requirement_negative_terms_do_not_use_pipe_separator(self):
        terms = rule_engine.extract_negative_terms(_security_requirement_from_config())

        self.assertTrue(terms)
        self.assertFalse(any("|" in term for term in terms))


if __name__ == "__main__":
    unittest.main()
