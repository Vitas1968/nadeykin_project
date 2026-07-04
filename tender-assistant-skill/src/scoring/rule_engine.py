from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_ALLOWED_PRIORITIES = {"high", "medium", "low"}
_ALLOWED_STATUSES = {"pass", "fail", "unknown", "conflict"}
_ALLOWED_RISKS = {"low", "medium", "high"}
_NEGATIVE_FIELD_KEYS = (
    "negative_keywords",
    "risk_keywords",
    "non_relevance_keywords",
    "negative_terms",
    "risk_terms",
    "non_relevance_terms",
    "negative_sign",
    "risk_sign",
    "non_relevance_sign",
    "Признак нерелевантности / риск ошибки",
)
_TERM_SPLIT_RE = re.compile(r"[;,]")
_MSP_RULE_ID = "msp_restriction"
_SECURITY_REQUIREMENT_RULE_ID = "security_requirement"
_EXPLICIT_MSP_OR_DEALER_TERMS = (
    "субъекты мсп",
    "субъектов мсп",
    "субъектами мсп",
    "субъекты малого и среднего предпринимательства",
    "субъектов малого и среднего предпринимательства",
    "субъектами малого и среднего предпринимательства",
    "малого и среднего предпринимательства",
    "только мсп",
    "для мсп",
    "для смп",
    "субъекты смп",
    "субъектов смп",
    "дилер",
    "дилера",
    "дилеру",
    "партнер",
    "партнера",
    "партнеру",
    "партнёр",
    "партнёра",
    "партнёру",
)
_SECURITY_NEGATIVE_TERMS = (
    "обеспечение заявки на участие в закупке | не требуется",
    "обеспечение заявки не требуется",
    "обеспечение участия не требуется",
    "обеспечение исполнения договора | не требуется",
    "обеспечение исполнения контракта | не требуется",
    "обеспечение исполнения обязательств по договору | не требуется",
    "обеспечение исполнения не требуется",
    "обеспечение договора не требуется",
    "не требуется обеспечение",
    "не установлено обеспечение",
    "обеспечение не установлено",
    "не предусмотрено обеспечение",
    "обеспечение не предусмотрено",
)


def _normalize_content_text(value: Any) -> str:
    return str(value).strip().lower().replace("ё", "е")


def _normalize_identifier(value: Any) -> str:
    return str(value).strip()


def _first_non_empty_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key not in item:
            continue
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _get_source_id(item: dict[str, Any]) -> str | None:
    for key in ("id", "criterion_id"):
        if key not in item:
            continue
        value = item.get(key)
        if value is None:
            continue
        text = _normalize_identifier(value)
        if text:
            return text
    return None


def _normalize_unique_terms(values: list[str]) -> list[str]:
    normalized_terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized_value = _normalize_content_text(value)
        if not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        normalized_terms.append(normalized_value)
    return normalized_terms


def _split_negative_field(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_parts = [str(item) for item in value]
    elif isinstance(value, str):
        raw_parts = _TERM_SPLIT_RE.split(value)
    else:
        raw_parts = [str(value)]

    cleaned_parts: list[str] = []
    for part in raw_parts:
        normalized_part = _normalize_content_text(part)
        if normalized_part:
            cleaned_parts.append(normalized_part)
    return cleaned_parts


def _coerce_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_evidence_text(evidence_item: dict[str, Any]) -> str:
    if not isinstance(evidence_item, dict):
        return ""

    collected: list[str] = []
    for key in ("snippet", "text"):
        value = evidence_item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            collected.append(text)

    block = evidence_item.get("block")
    if isinstance(block, dict):
        block_text = block.get("text")
        if block_text is not None:
            text = str(block_text).strip()
            if text:
                collected.append(text)

    return " ".join(collected)


def _extract_evidence_texts(evidence: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for evidence_item in evidence:
        text = _normalize_content_text(_extract_evidence_text(evidence_item))
        if text:
            texts.append(text)
    return texts


def _any_term_in_texts(texts: list[str], terms: tuple[str, ...]) -> bool:
    return any(term in text for text in texts for term in terms)


def _has_explicit_msp_or_dealer_indicator(evidence: list[dict[str, Any]], has_confirming: bool) -> bool:
    if not has_confirming:
        return False

    evidence_texts = _extract_evidence_texts(evidence)
    return _any_term_in_texts(evidence_texts, _EXPLICIT_MSP_OR_DEALER_TERMS)


def _evidence_concerns(
    rule_id: str,
    evidence: list[dict[str, Any]],
    has_confirming: bool,
    explicit_msp_or_dealer_indicator: bool,
) -> list[str]:
    if not has_confirming:
        return []

    evidence_texts = _extract_evidence_texts(evidence)
    concerns: list[str] = []

    if rule_id == _MSP_RULE_ID and not explicit_msp_or_dealer_indicator:
        concerns.append("msp_indicator_not_explicit")

    if rule_id == _SECURITY_REQUIREMENT_RULE_ID and _any_term_in_texts(evidence_texts, _SECURITY_NEGATIVE_TERMS):
        concerns.append("security_requirement_negative_evidence")

    return concerns


def _resolve_evidence_list(evidence: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if evidence is None:
        return []
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list or None")

    resolved: list[dict[str, Any]] = []
    for evidence_item in evidence:
        if isinstance(evidence_item, dict):
            resolved.append(dict(evidence_item))
    return resolved


def _validate_unique_ids(items: list[dict[str, Any]], label: str) -> None:
    seen: dict[str, int] = {}
    for index, item in enumerate(items):
        source_id = _get_source_id(item)
        if source_id is None:
            continue
        if source_id in seen:
            raise ValueError(f"Duplicate {label} id: {source_id}")
        seen[source_id] = index


def _resolve_matches_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    if "matches" not in item:
        return []
    matches = item.get("matches")
    if matches is None:
        return []
    if not isinstance(matches, list):
        raise ValueError("matches must be a list or null")
    resolved_matches: list[dict[str, Any]] = []
    for match in matches:
        if isinstance(match, dict):
            resolved_matches.append(dict(match))
    return resolved_matches


def _parse_yaml_scalar(text: str) -> Any:
    value = text.strip()
    if not value:
        return ""

    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value


def _collect_yaml_list(lines: list[str], start_index: int, parent_indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    index = start_index
    list_indent: int | None = None

    while index < len(lines):
        line = lines[index]
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent <= parent_indent:
            break
        if not stripped.startswith("- "):
            break
        if list_indent is None:
            list_indent = indent
        if indent != list_indent:
            break
        items.append(_parse_yaml_scalar(stripped[2:]))
        index += 1

    return items, index


def _parse_yaml_criteria_list(lines: list[str], start_index: int) -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = []
    index = start_index

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if not stripped:
            index += 1
            continue
        if not stripped.startswith("- "):
            index += 1
            continue

        item: dict[str, Any] = {}
        first_fragment = stripped[2:].strip()
        if first_fragment:
            if ":" in first_fragment:
                key, value = first_fragment.split(":", 1)
                key = key.strip()
                value = value.strip()
                item[key] = _parse_yaml_scalar(value) if value else None
            else:
                item["value"] = _parse_yaml_scalar(first_fragment)

        index += 1
        pending_list_key: str | None = None

        while index < len(lines):
            child_line = lines[index]
            child_stripped = child_line.strip()
            child_indent = len(child_line) - len(child_line.lstrip(" "))

            if not child_stripped:
                index += 1
                continue
            if child_indent <= indent:
                break
            if child_stripped.startswith("- "):
                if pending_list_key is None:
                    index += 1
                    continue
                list_items, index = _collect_yaml_list(lines, index, child_indent - 2)
                if pending_list_key in item and isinstance(item[pending_list_key], list):
                    item[pending_list_key].extend(list_items)
                else:
                    item[pending_list_key] = list_items
                pending_list_key = None
                continue

            if ":" not in child_stripped:
                index += 1
                continue

            key, value = child_stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                item[key] = _parse_yaml_scalar(value)
                pending_list_key = None
                index += 1
                continue

            list_items, new_index = _collect_yaml_list(lines, index + 1, child_indent)
            item[key] = list_items
            pending_list_key = key if not list_items else None
            index = new_index

        criteria.append(item)

    return criteria


def _load_criteria_without_yaml(path: str | Path) -> list[dict[str, Any]]:
    criteria_path = Path(path)
    if not criteria_path.exists():
        raise FileNotFoundError(f"Criteria file does not exist: {criteria_path}")

    suffix = criteria_path.suffix.lower()
    content = criteria_path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return []

    if suffix == ".json":
        data = json.loads(content)
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "criteria" in data:
                criteria = data.get("criteria")
                if criteria is None:
                    return []
                if not isinstance(criteria, list):
                    raise ValueError("criteria must be a list or null")
                return criteria
            return [data]
        raise ValueError("Unsupported criteria file format")

    normalized_lines = []
    criteria_list_start: int | None = None
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "criteria:":
            criteria_list_start = len(normalized_lines) + 1
            normalized_lines.append(raw_line.rstrip())
            continue
        normalized_lines.append(raw_line.rstrip())

    if criteria_list_start is None:
        return []

    return _parse_yaml_criteria_list(normalized_lines, criteria_list_start)


def normalize_priority(priority: str | None) -> str:
    normalized = _normalize_content_text(priority)
    if not normalized:
        return "medium"

    if normalized in {"high", "critical", "critically", "критично", "критичный", "критичная", "критическое", "высокий", "высокая", "высокое"}:
        return "high"
    if normalized in {"medium", "average", "средний", "средняя", "среднее"}:
        return "medium"
    if normalized in {"low", "низкий", "низкая", "низкое"}:
        return "low"
    return "medium"


def normalize_status(status: str | None) -> str:
    normalized = _normalize_content_text(status)
    if normalized in _ALLOWED_STATUSES:
        return normalized
    return "unknown"


def normalize_risk(risk: str | None) -> str:
    normalized = _normalize_content_text(risk)
    if normalized in _ALLOWED_RISKS:
        return normalized
    return "medium"


def is_confirming_evidence(evidence_item: dict[str, Any]) -> bool:
    if not isinstance(evidence_item, dict):
        return False

    score = _coerce_score(evidence_item.get("score")) if "score" in evidence_item else None
    if score is not None:
        return score > 0

    return bool(_extract_evidence_text(evidence_item).strip())


def find_negative_evidence(evidence: list[dict[str, Any]], negative_terms: list[str]) -> list[dict[str, Any]]:
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    if not negative_terms:
        return []

    normalized_terms = _normalize_unique_terms([str(term) for term in negative_terms])
    if not normalized_terms:
        return []

    negative_evidence: list[dict[str, Any]] = []
    for evidence_item in evidence:
        if not isinstance(evidence_item, dict):
            continue
        evidence_text = _normalize_content_text(_extract_evidence_text(evidence_item))
        if not evidence_text:
            continue
        if any(term in evidence_text for term in normalized_terms):
            negative_evidence.append(dict(evidence_item))
    return negative_evidence


def extract_negative_terms(criterion: dict[str, Any]) -> list[str]:
    if not isinstance(criterion, dict):
        raise ValueError("criterion must be a dict")

    collected_terms: list[str] = []
    for key in _NEGATIVE_FIELD_KEYS:
        if key not in criterion:
            continue
        collected_terms.extend(_split_negative_field(criterion.get(key)))
    return _normalize_unique_terms(collected_terms)


def _resolve_rule_identity(criterion: dict[str, Any]) -> str:
    source_id = _get_source_id(criterion)
    if source_id is not None:
        return source_id
    return "criterion_unknown"


def _resolve_rule_metadata(criterion: dict[str, Any]) -> tuple[str, str | None, str, str]:
    rule_id = _resolve_rule_identity(criterion)
    block = _first_non_empty_text(criterion, ("block",)) or None
    criterion_text = _first_non_empty_text(criterion, ("criterion",))
    priority = normalize_priority(criterion.get("priority"))
    return rule_id, block, criterion_text, priority


def _resolve_criterion_matches(criterion: dict[str, Any]) -> list[dict[str, Any]]:
    return _resolve_matches_from_item(criterion)


def _build_rule_comment(status: str, confirming_count: int, concerns: list[str] | None = None) -> str:
    concerns = concerns or []
    if "msp_indicator_not_explicit" in concerns:
        return "Найденные фрагменты не содержат явного признака МСП/СМП, дилера или партнера; требуется проверка."
    if "security_requirement_negative_evidence" in concerns:
        return "Найдено evidence с отрицанием требования обеспечения; требуется ручная проверка."
    if status == "pass":
        return f"Критерий подтвержден найденными фрагментами: {confirming_count}."
    if status == "fail":
        return "Найден негативный признак по критерию."
    if status == "conflict":
        return "Найдены одновременно подтверждающие и рискованные признаки; требуется ручная проверка."
    return "Подтверждающие фрагменты не найдены."


def evaluate_criterion(criterion: dict[str, Any], evidence: list[dict[str, Any]] | None = None) -> dict:
    if not isinstance(criterion, dict):
        raise ValueError("criterion must be a dict")

    resolved_evidence = _resolve_evidence_list(evidence) if evidence is not None else _resolve_criterion_matches(criterion)
    rule_id, block, criterion_text, priority = _resolve_rule_metadata(criterion)

    confirming_evidence = [item for item in resolved_evidence if is_confirming_evidence(item)]
    negative_terms = extract_negative_terms(criterion)
    negative_evidence = find_negative_evidence(resolved_evidence, negative_terms) if negative_terms else []

    has_confirming = bool(confirming_evidence)
    has_negative = bool(negative_evidence)
    explicit_msp_or_dealer_indicator = (
        rule_id == _MSP_RULE_ID
        and _has_explicit_msp_or_dealer_indicator(resolved_evidence, has_confirming)
    )
    concerns = _evidence_concerns(
        rule_id,
        resolved_evidence,
        has_confirming,
        explicit_msp_or_dealer_indicator,
    )

    if has_confirming and has_negative:
        status = "conflict"
    elif has_negative:
        status = "fail"
    elif has_confirming:
        status = "pass"
    else:
        status = "unknown"

    has_concerns = bool(concerns)

    if status in {"fail", "conflict"}:
        risk = "high"
    elif status == "unknown":
        risk = "low" if priority == "low" else "medium"
    elif has_concerns and priority == "high":
        risk = "medium"
    else:
        risk = "low"

    human_review_required = (
        status in {"fail", "conflict"}
        or (status == "unknown" and priority != "low")
        or (status == "pass" and priority == "high" and has_concerns)
    )
    comment = _build_rule_comment(status, len(confirming_evidence), concerns)

    return {
        "id": rule_id,
        "block": block,
        "criterion": criterion_text,
        "priority": priority,
        "evidence": resolved_evidence,
        "status": status,
        "risk": risk,
        "human_review_required": human_review_required,
        "comment": comment,
        "evidence_concerns": concerns,
        "explicit_dealer_indicator": explicit_msp_or_dealer_indicator,
    }


def _build_search_result_map(search_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    _validate_unique_ids(search_results, "search result")
    result_map: dict[str, dict[str, Any]] = {}
    for result_item in search_results:
        source_id = _get_source_id(result_item)
        if source_id is None:
            continue
        result_map[source_id] = result_item
    return result_map


def _resolve_evidence_for_criterion(
    criterion: dict[str, Any],
    search_result_map: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    source_id = _get_source_id(criterion)
    if search_result_map is not None and source_id is not None and source_id in search_result_map:
        return _resolve_matches_from_item(search_result_map[source_id])
    return _resolve_criterion_matches(criterion)


def evaluate_criteria(
    criteria: list[dict[str, Any]],
    search_results: dict | list[dict[str, Any]] | None = None,
) -> dict:
    if not isinstance(criteria, list):
        raise ValueError("criteria must be a list")

    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise ValueError("criteria items must be dicts")

    _validate_unique_ids(criteria, "criterion")

    search_result_map: dict[str, dict[str, Any]] | None = None
    if search_results is not None:
        if isinstance(search_results, dict):
            if "results" not in search_results:
                raise ValueError('search_results dict must contain "results"')
            results_value = search_results.get("results")
            if not isinstance(results_value, list):
                raise ValueError('search_results["results"] must be a list')
            search_result_map = _build_search_result_map(results_value)
        elif isinstance(search_results, list):
            search_result_map = _build_search_result_map(search_results)
        else:
            raise ValueError("search_results must be a dict, list, or None")

    rules: list[dict[str, Any]] = []
    stats = {
        "pass": 0,
        "fail": 0,
        "unknown": 0,
        "conflict": 0,
        "risk_low": 0,
        "risk_medium": 0,
        "risk_high": 0,
        "human_review_required": 0,
    }

    for criterion in criteria:
        evidence = _resolve_evidence_for_criterion(criterion, search_result_map)
        rule = evaluate_criterion(criterion, evidence=evidence)
        rules.append(rule)
        stats[rule["status"]] += 1
        stats[f"risk_{rule['risk']}"] += 1
        if rule["human_review_required"]:
            stats["human_review_required"] += 1

    return {
        "criteria_count": len(criteria),
        "rules_count": len(rules),
        "rules": rules,
        "stats": stats,
    }


def evaluate_search_result(search_result: dict[str, Any]) -> dict:
    if not isinstance(search_result, dict):
        raise ValueError("search_result must be a dict")
    if "results" not in search_result:
        raise ValueError('search_result must contain "results"')
    results = search_result.get("results")
    if not isinstance(results, list):
        raise ValueError('search_result["results"] must be a list')

    evaluated = evaluate_criteria(results, None)
    evaluated["input_path"] = search_result.get("input_path")
    evaluated["document_count"] = search_result.get("document_count")
    source_stats = search_result.get("stats")
    evaluated["source_stats"] = dict(source_stats) if isinstance(source_stats, dict) else {}
    return evaluated


def evaluate_tender_path(
    input_path: str,
    criteria_path: str,
    top_k: int = 5,
    min_score: float = 0.0,
) -> dict:
    try:
        import retrieval.keyword_search as keyword_search_module
    except ModuleNotFoundError:
        SRC_ROOT = Path(__file__).resolve().parents[1]
        if str(SRC_ROOT) not in sys.path:
            sys.path.insert(0, str(SRC_ROOT))
        import retrieval.keyword_search as keyword_search_module

    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_file}")

    criteria_file = Path(criteria_path)
    if not criteria_file.exists():
        raise FileNotFoundError(f"Criteria file does not exist: {criteria_file}")

    if getattr(keyword_search_module, "yaml", None) is None:
        criteria = _load_criteria_without_yaml(criteria_path)
        tender_result = keyword_search_module.read_tender_path(input_path)
        search_result = keyword_search_module.search_by_criteria(
            tender_result,
            criteria,
            top_k_per_criterion=top_k,
            min_score=min_score,
        )
        search_result["input_path"] = tender_result.get("input_path")
        stats = tender_result.get("stats")
        search_result["document_count"] = stats.get("documents") if isinstance(stats, dict) else None
    else:
        search_result = keyword_search_module.search_tender_path(
            input_path,
            criteria_path=criteria_path,
            top_k=top_k,
            min_score=min_score,
        )
    return evaluate_search_result(search_result)


def _print_summary(result: dict[str, Any]) -> None:
    print(f"criteria_count: {result['criteria_count']}")
    print(f"rules_count: {result['rules_count']}")
    print(f"stats: {json.dumps(result['stats'], ensure_ascii=False)}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("--criteria", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = evaluate_tender_path(
        args.input_path,
        args.criteria,
        top_k=args.top_k,
        min_score=args.min_score,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
