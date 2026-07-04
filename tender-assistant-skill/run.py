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
from scoring.scenario_classifier import classify_scenario
from output.docx_summary_writer import write_docx_summary
from output.questions_writer import write_questions
from output.summary_writer import write_summary


REPO_ROOT = PROJECT_ROOT.parent
DEFAULT_DOCX_TEMPLATE_RELATIVE = "sources_info/Шаблон сводки по тендеру v2.docx"


def _resolve_docx_template_path(template_arg: str | None) -> Path:
    if template_arg is None:
        template_path = REPO_ROOT / Path(DEFAULT_DOCX_TEMPLATE_RELATIVE)
        if not template_path.exists():
            raise FileNotFoundError(f"DOCX template not found: {template_path}")
        return template_path

    template_path = Path(template_arg)
    if template_path.is_absolute():
        if not template_path.exists():
            raise FileNotFoundError(f"DOCX template not found: {template_path}")
        return template_path

    cwd_path = Path.cwd() / template_path
    if cwd_path.exists():
        return cwd_path

    repo_root_path = REPO_ROOT / template_path
    if repo_root_path.exists():
        return repo_root_path

    raise FileNotFoundError(
        "DOCX template not found. "
        f"Requested template: {template_arg}. "
        f"Checked cwd path: {cwd_path}. "
        f"Checked repo root path: {repo_root_path}."
    )


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
    parser.add_argument(
        "--docx-template",
        default=None,
        type=str,
        help=f"DOCX template path (default: {DEFAULT_DOCX_TEMPLATE_RELATIVE})",
    )
    parser.add_argument("--no-docx", action="store_true")
    args = parser.parse_args()

    result = evaluate_tender_path(
        input_path=args.input,
        criteria_path=args.criteria,
        top_k=args.top_k,
        min_score=args.min_score,
    )
    result["scenario_result"] = classify_scenario(result)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tender_score.json"
    with out_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(f"Wrote: {out_path}")
    questions_path = write_questions(result, out_dir / "questions_for_customer.md")
    print(f"Wrote: {questions_path}")
    summary_path = write_summary(result, out_dir / "tender_summary.md")
    print(f"Wrote: {summary_path}")
    if args.no_docx:
        if args.docx_template is not None:
            print("DOCX export disabled by --no-docx; --docx-template ignored")
        else:
            print("DOCX export disabled by --no-docx")
        return 0

    docx_template_path = _resolve_docx_template_path(args.docx_template)
    docx_path = out_dir / "tender_summary.docx"
    written_docx_path = write_docx_summary(result, docx_template_path, docx_path)
    print(f"DOCX summary written to: {written_docx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
