from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scoring.rule_engine import evaluate_tender_path
from output.questions_writer import write_questions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=str)
    parser.add_argument(
        "--criteria",
        default=str(PROJECT_ROOT / "config" / "criteria.yaml"),
        type=str,
    )
    parser.add_argument("--out", required=True, type=str)
    parser.add_argument("--top-k", default=5, type=int)
    parser.add_argument("--min-score", default=0.0, type=float)
    args = parser.parse_args()

    result = evaluate_tender_path(
        input_path=args.input,
        criteria_path=args.criteria,
        top_k=args.top_k,
        min_score=args.min_score,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tender_score.json"
    with out_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(f"Wrote: {out_path}")
    questions_path = write_questions(result, out_dir / "questions_for_customer.md")
    print(f"Wrote: {questions_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
