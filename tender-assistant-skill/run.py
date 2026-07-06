from __future__ import annotations

import argparse
import copy
import json
import re
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
from llm import classify_criterion, load_config_from_env
from llm.schema import build_error_verdict, build_skipped_verdict, normalize_rule_id, normalize_status


REPO_ROOT = PROJECT_ROOT.parent
DEFAULT_DOCX_TEMPLATE_RELATIVE = "sources_info/Шаблон сводки по тендеру v2.docx"
LLM_SHADOW_RULE_ID = "procurement_method"
PURCHASE_TYPE_GOODS_LLM_SHADOW_RULE_ID = "purchase_type_goods"
MSP_RESTRICTION_LLM_SHADOW_RULE_ID = "msp_restriction"
LLM_SHADOW_RULE_IDS = (
    LLM_SHADOW_RULE_ID,
    PURCHASE_TYPE_GOODS_LLM_SHADOW_RULE_ID,
    MSP_RESTRICTION_LLM_SHADOW_RULE_ID,
)
LLM_SHADOW_DETERMINISTIC_KEYS = (
    "id",
    "criterion",
    "status",
    "risk",
    "priority",
    "human_review_required",
    "comment",
    "evidence",
    "evidence_concerns",
    "explicit_dealer_indicator",
)
PROCUREMENT_METHOD_LLM_ALLOWED_PATTERNS = (
    re.compile(r"\bэлектрон\w*\s+аукцион\w*\b"),
    re.compile(r"\bаукцион\w*\s+в\s+электрон\w*\s+форм\w*\b"),
    re.compile(r"\bпроведени\w*\s+электрон\w*\s+аукцион\w*\b"),
    re.compile(r"\bэлектрон\w*\s+аукцион\w*\s+на\s+право\s+заключени\w*\s+договор\w*\b"),
    re.compile(r"\bзапрос\s+предложени\w*\b"),
    re.compile(r"\bзапрос\s+котировок\b"),
    re.compile(r"\bкотировок\b"),
    re.compile(r"\bкотировк\w*\b"),
    re.compile(r"\bконкурс\w*\s+в\s+электрон\w*\s+форм\w*\b"),
    re.compile(r"\bоткрыт\w*\s+конкурс\w*\b"),
    re.compile(r"\bспособ\s+закупки\s*:\s*конкурс\w*\b"),
    re.compile(r"\bспособ\s+определени\w*\s+поставщик\w*\s*:\s*конкурс\w*\b"),
)
PROCUREMENT_METHOD_AUCTION_ELECTRONIC_PROXIMITY_PATTERN = re.compile(
    r"\bаукцион\w*\b[\s\S]{0,80}\bэлектрон\w*\b|\bэлектрон\w*\b[\s\S]{0,80}\bаукцион\w*\b"
)
PURCHASE_TYPE_GOODS_LLM_ALLOWED_PATTERNS = (
    re.compile(r"\bпоставк\w*\s+товар\w*\b"),
    re.compile(r"\bпоставщик\w*\s+поставля\w*\s+товар\w*\b"),
    re.compile(r"\bпокупател\w*\s+принима\w*\s+товар\w*\b"),
    re.compile(r"\bпередач\w*\s+товар\w*\b"),
    re.compile(r"\bтовар\w*\s+поставля\w*\b"),
    re.compile(r"\bтовар\w*(?:\s+\w+){0,3}\s+поставлен\w*\b"),
)
PURCHASE_TYPE_SERVICE_WORK_LLM_ALLOWED_PATTERNS = (
    re.compile(r"\bоказани\w*\s+услуг\w*\b"),
    re.compile(r"\bпредоставлени\w*\s+услуг\w*\b"),
    re.compile(r"\bуслуг\w*\s+по\s+замен\w*\s+масл\w*\b"),
    re.compile(r"\bвыполнени\w*\s+работ\w*\b"),
    re.compile(r"\bтехническ\w*\s+обслуживани\w*\b"),
    re.compile(r"\bмонтаж\w*\b"),
    re.compile(r"\bустановк\w*\s+оборудовани\w*\b"),
    re.compile(r"\bремонт\w*\s+оборудовани\w*\b"),
    re.compile(r"\bдиагностик\w*\s+оборудовани\w*\b"),
    re.compile(r"\bпроведени\w*\s+диагностик\w*\b"),
)
MSP_RESTRICTION_SKIP_REASON = (
    "Evidence does not contain explicit SME-only restriction or explicit absence of SME restriction."
)
MSP_RESTRICTION_MARKERS = (
    "мсп",
    "смп",
    "малого и среднего предпринимательства",
    "малого предпринимательства",
    "сонко",
    "соно",
)
MSP_RESTRICTION_POSITIVE_CONTEXT_MARKERS = (
    "только",
    "среди",
    "ограничение участия установлено",
    "ограничение установлено",
)
MSP_RESTRICTION_NEGATIVE_CONTEXT_MARKERS = (
    "не установлено",
    "не предусмотрено",
    "отсутствует",
)
MSP_RESTRICTION_ABSENCE_MARKERS = (
    "не является закупкой у смп",
    "не является закупкой у мсп",
    "участниками могут быть любые лица",
)
MSP_RESTRICTION_PROXIMITY_WINDOW_CHARS = 50


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


def _evidence_item_text(item: dict) -> str:
    text = item.get("text")
    if text is None or not str(text).strip():
        text = item.get("snippet")
    if text is None or not str(text).strip():
        block = item.get("block")
        text = block.get("text", "") if isinstance(block, dict) else ""
    return str(text)


def _normalize_guardrail_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _marker_positions(text: str, marker: str) -> list[int]:
    positions: list[int] = []
    start = 0
    while True:
        position = text.find(marker, start)
        if position < 0:
            return positions
        positions.append(position)
        start = position + 1


def _markers_are_near(text: str, marker_a: str, marker_b: str) -> bool:
    if marker_a not in text or marker_b not in text:
        return False

    has_sentence_separator = any(separator in text for separator in ".!?;")
    if has_sentence_separator:
        sentences = [sentence.strip() for sentence in re.split(r"[.!?;]+", text) if sentence.strip()]
        if any(marker_a in sentence and marker_b in sentence for sentence in sentences):
            return True
        return False

    positions_a = _marker_positions(text, marker_a)
    positions_b = _marker_positions(text, marker_b)
    return any(
        abs(position_a - position_b) <= MSP_RESTRICTION_PROXIMITY_WINDOW_CHARS
        for position_a in positions_a
        for position_b in positions_b
    )


def _any_markers_are_near(text: str, markers_a: tuple[str, ...], markers_b: tuple[str, ...]) -> bool:
    return any(
        _markers_are_near(text, marker_a, marker_b)
        for marker_a in markers_a
        for marker_b in markers_b
    )


def _msp_restriction_item_guardrail_verdict(item: dict) -> str | None:
    text = _normalize_guardrail_text(_evidence_item_text(item))
    if not text:
        return None

    has_positive_context = _any_markers_are_near(
        text,
        MSP_RESTRICTION_MARKERS,
        MSP_RESTRICTION_POSITIVE_CONTEXT_MARKERS,
    )
    has_absence_context = _contains_any_marker(text, MSP_RESTRICTION_ABSENCE_MARKERS) or _any_markers_are_near(
        text,
        ("ограничение участия",),
        MSP_RESTRICTION_NEGATIVE_CONTEXT_MARKERS,
    )

    if has_positive_context and has_absence_context:
        return "conflict"
    if has_positive_context:
        return "positive"
    if has_absence_context:
        return "negative"
    return None


def _aggregate_msp_restriction_guardrail_verdict(evidence: list) -> str | None:
    has_positive = False
    has_negative = False

    for item in evidence:
        if not isinstance(item, dict):
            continue

        item_verdict = _msp_restriction_item_guardrail_verdict(item)
        if item_verdict == "conflict":
            return "conflict"
        if item_verdict == "positive":
            has_positive = True
        elif item_verdict == "negative":
            has_negative = True

    if has_positive and has_negative:
        return "conflict"
    if has_positive:
        return "positive"
    if has_negative:
        return "negative"
    return None


# Non-target rules are allowed if guardrail helpers are reused directly.
def _procurement_method_evidence_allows_llm(rule: dict) -> bool:
    if normalize_rule_id(rule.get("id")) != LLM_SHADOW_RULE_ID:
        return True

    evidence = rule.get("evidence")
    if not isinstance(evidence, list):
        return False

    for item in evidence:
        if not isinstance(item, dict):
            continue

        text = _evidence_item_text(item).lower()
        if any(pattern.search(text) for pattern in PROCUREMENT_METHOD_LLM_ALLOWED_PATTERNS):
            return True
        if PROCUREMENT_METHOD_AUCTION_ELECTRONIC_PROXIMITY_PATTERN.search(text):
            return True

    return False


def _purchase_type_goods_evidence_allows_llm(rule: dict) -> bool:
    if normalize_rule_id(rule.get("id")) != PURCHASE_TYPE_GOODS_LLM_SHADOW_RULE_ID:
        return True

    evidence = rule.get("evidence")
    if not isinstance(evidence, list):
        return False

    for item in evidence:
        if not isinstance(item, dict):
            continue

        text = _evidence_item_text(item).lower()
        if any(pattern.search(text) for pattern in PURCHASE_TYPE_GOODS_LLM_ALLOWED_PATTERNS):
            return True
        if any(pattern.search(text) for pattern in PURCHASE_TYPE_SERVICE_WORK_LLM_ALLOWED_PATTERNS):
            return True

    return False


def _msp_restriction_evidence_allows_llm(rule: dict) -> bool:
    if normalize_rule_id(rule.get("id")) != MSP_RESTRICTION_LLM_SHADOW_RULE_ID:
        return True

    evidence = rule.get("evidence")
    if not isinstance(evidence, list):
        return False

    # Evidence items do not expose a reliable title/body discriminator, so title-only SME header heuristics are not implemented.
    return _aggregate_msp_restriction_guardrail_verdict(evidence) is not None


def _llm_shadow_skip_reason(rule: dict) -> str | None:
    rule_id = normalize_rule_id(rule.get("id"))
    if rule_id == LLM_SHADOW_RULE_ID and not _procurement_method_evidence_allows_llm(rule):
        return "Evidence does not contain explicit procurement method phrase."
    if rule_id == PURCHASE_TYPE_GOODS_LLM_SHADOW_RULE_ID and not _purchase_type_goods_evidence_allows_llm(rule):
        return "Evidence does not contain explicit goods supply or service/work phrase."
    if rule_id == MSP_RESTRICTION_LLM_SHADOW_RULE_ID and not _msp_restriction_evidence_allows_llm(rule):
        return MSP_RESTRICTION_SKIP_REASON
    return None


def _apply_llm_shadow_verdict(result: dict) -> None:
    config = load_config_from_env()
    if not config.enabled:
        return

    rules = result.get("rules")
    if not isinstance(rules, list):
        return

    target_rules = [
        rule
        for rule in rules
        if isinstance(rule, dict) and normalize_rule_id(rule.get("id")) in LLM_SHADOW_RULE_IDS
    ]
    if not target_rules:
        return

    for target_rule in target_rules:
        skip_reason = _llm_shadow_skip_reason(target_rule)
        if skip_reason is not None:
            target_rule["llm_verdict"] = build_skipped_verdict(
                rule_id=normalize_rule_id(target_rule.get("id")),
                deterministic_status=normalize_status(target_rule.get("status")),
                provider=config.provider,
                model=config.model,
                reason=skip_reason,
                human_review_required=True,
            )
            continue

        snapshot = {
            key: copy.deepcopy(target_rule.get(key))
            for key in LLM_SHADOW_DETERMINISTIC_KEYS
            if key in target_rule
        }
        try:
            llm_verdict = classify_criterion(target_rule)
        except Exception as exc:
            llm_verdict = build_error_verdict(
                rule_id=normalize_rule_id(target_rule.get("id")),
                deterministic_status=normalize_status(target_rule.get("status")),
                provider=config.provider,
                model=config.model,
                reason="LLM shadow classification failed.",
                warnings=[str(exc)],
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        mutated = any(target_rule.get(key) != value for key, value in snapshot.items())
        mutated = mutated or any(key not in snapshot and key in target_rule for key in LLM_SHADOW_DETERMINISTIC_KEYS)
        for key in LLM_SHADOW_DETERMINISTIC_KEYS:
            if key in snapshot:
                target_rule[key] = snapshot[key]
            else:
                target_rule.pop(key, None)
        if mutated and isinstance(llm_verdict, dict):
            warnings = list(llm_verdict.get("warnings") or [])
            warnings.append("Deterministic rule fields were restored after LLM shadow classification.")
            llm_verdict["warnings"] = warnings
        target_rule["llm_verdict"] = llm_verdict


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
    _apply_llm_shadow_verdict(result)
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
    written_docx_path = Path(written_docx_path)
    if not written_docx_path.exists() or written_docx_path.stat().st_size <= 0:
        raise RuntimeError(
            "DOCX export completed without error, but tender_summary.docx is missing or empty"
        )
    print(f"DOCX summary written to: {written_docx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
