from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from retrieval.keyword_search import build_search_terms
from scoring import rule_engine


class ProcurementMethodSearchTermsTests(unittest.TestCase):
    def test_procurement_method_contains_request_for_proposals_phrase(self):
        criteria_path = Path(__file__).resolve().parents[2] / "config" / "criteria.yaml"
        criteria = rule_engine._load_criteria_without_yaml(criteria_path)
        criterion = next(item for item in criteria if item.get("id") == "procurement_method")

        terms = build_search_terms(query=criterion.get("query"), keywords=criterion.get("keywords"))

        self.assertIn(
            {"raw": "запрос предложений", "normalized": "запрос предложений", "kind": "phrase"},
            terms,
        )


if __name__ == "__main__":
    unittest.main()
