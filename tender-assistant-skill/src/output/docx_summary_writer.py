from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


PLACEHOLDER_RE = re.compile(r"\{\{[a-zA-Z0-9_.]+\}\}")
XML_INVALID_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
KNOWN_RULE_STATUSES = {"pass", "fail", "unknown", "conflict"}
RUN_SPLITTING_MESSAGE = "possible run-splitting in template XML or template/contract mismatch"

PLACEHOLDER_SPECS: dict[str, dict[str, Any]] = {
    "{{input.path}}": {
        "required": True,
        "fallback": "Путь к входным данным не указан.",
    },
    "{{stats.document_count}}": {"required": True, "fallback": "0"},
    "{{stats.criteria_count}}": {"required": True, "fallback": "0"},
    "{{stats.rules_count}}": {"required": True, "fallback": "0"},
    "{{stats.pass}}": {"required": True, "fallback": "0"},
    "{{stats.fail}}": {"required": True, "fallback": "0"},
    "{{stats.unknown}}": {"required": True, "fallback": "0"},
    "{{stats.conflict}}": {"required": True, "fallback": "0"},
    "{{stats.risk_low}}": {"required": True, "fallback": "0"},
    "{{stats.risk_medium}}": {"required": True, "fallback": "0"},
    "{{stats.risk_high}}": {"required": True, "fallback": "0"},
    "{{stats.human_review_required}}": {"required": True, "fallback": "0"},
    "{{scenario.scenario}}": {
        "required": True,
        "fallback": "Итоговый сценарий не рассчитан.",
    },
    "{{scenario.recommendation}}": {
        "required": True,
        "fallback": "Рекомендация не сформирована.",
    },
    "{{scenario.confidence}}": {"required": True, "fallback": "-"},
    "{{scenario.human_review_required}}": {
        "required": True,
        "fallback": "не указано",
    },
    "{{scenario.blocking_criteria}}": {
        "required": True,
        "fallback": "Блокирующие критерии не выявлены.",
    },
    "{{scenario.reasons}}": {
        "required": True,
        "fallback": "Причины не сформированы.",
    },
    "{{rules.subject_okpd2_oil.status}}": {
        "required": True,
        "fallback": "unknown",
    },
    "{{rules.subject_okpd2_oil.comment}}": {
        "required": True,
        "fallback": "Комментарий по ОКПД2 не сформирован.",
    },
    "{{rules.subject_okpd2_oil.evidence}}": {
        "required": True,
        "fallback": "Evidence по ОКПД2 не найдено.",
    },
    "{{rules.procurement_method.status}}": {
        "required": True,
        "fallback": "unknown",
    },
    "{{rules.procurement_method.comment}}": {
        "required": True,
        "fallback": "Комментарий по способу закупки не сформирован.",
    },
    "{{rules.procurement_method.evidence}}": {
        "required": True,
        "fallback": "Evidence по способу закупки не найдено.",
    },
    "{{rules.price_nmc.status}}": {"required": True, "fallback": "unknown"},
    "{{rules.price_nmc.comment}}": {
        "required": True,
        "fallback": "Комментарий по НМЦК не сформирован.",
    },
    "{{rules.price_nmc.evidence}}": {
        "required": True,
        "fallback": "Evidence по НМЦК не найдено.",
    },
    "{{rules.delivery_location.status}}": {
        "required": True,
        "fallback": "unknown",
    },
    "{{rules.delivery_location.comment}}": {
        "required": True,
        "fallback": "Комментарий по месту поставки не сформирован.",
    },
    "{{rules.delivery_location.evidence}}": {
        "required": True,
        "fallback": "Evidence по месту поставки не найдено.",
    },
    "{{rules.delivery_period.status}}": {
        "required": True,
        "fallback": "unknown",
    },
    "{{rules.delivery_period.comment}}": {
        "required": True,
        "fallback": "Комментарий по сроку поставки не сформирован.",
    },
    "{{rules.delivery_period.evidence}}": {
        "required": True,
        "fallback": "Evidence по сроку поставки не найдено.",
    },
    "{{rules.msp_restriction.status}}": {
        "required": True,
        "fallback": "unknown",
    },
    "{{rules.msp_restriction.comment}}": {
        "required": True,
        "fallback": "Комментарий по ограничению МСП не сформирован.",
    },
    "{{rules.msp_restriction.evidence}}": {
        "required": True,
        "fallback": "Evidence по ограничению МСП не найдено.",
    },
    "{{rules.national_regime.status}}": {
        "required": True,
        "fallback": "unknown",
    },
    "{{rules.national_regime.comment}}": {
        "required": True,
        "fallback": "Комментарий по национальному режиму не сформирован.",
    },
    "{{rules.national_regime.evidence}}": {
        "required": True,
        "fallback": "Evidence по национальному режиму не найдено.",
    },
    "{{rules.security_requirement.status}}": {
        "required": True,
        "fallback": "unknown",
    },
    "{{rules.security_requirement.comment}}": {
        "required": True,
        "fallback": "Комментарий по обеспечению не сформирован.",
    },
    "{{rules.security_requirement.evidence}}": {
        "required": True,
        "fallback": "Evidence по обеспечению не найдено.",
    },
    "{{rules.contract_terms.status}}": {
        "required": True,
        "fallback": "unknown",
    },
    "{{rules.contract_terms.comment}}": {
        "required": True,
        "fallback": "Комментарий по условиям контракта не сформирован.",
    },
    "{{rules.contract_terms.evidence}}": {
        "required": True,
        "fallback": "Evidence по условиям контракта не найдено.",
    },
    "{{summary.general_conclusion}}": {
        "required": False,
        "fallback": "Общий вывод не сформирован.",
    },
    "{{summary.attention_criteria}}": {
        "required": False,
        "fallback": "Критерии, требующие внимания, не выявлены.",
    },
    "{{summary.confirmed_criteria}}": {
        "required": False,
        "fallback": "Подтвержденные критерии не выявлены.",
    },
    "{{summary.low_priority_unknown_criteria}}": {
        "required": False,
        "fallback": "Низкоприоритетные неподтвержденные критерии не выявлены.",
    },
    "{{questions.count}}": {"required": False, "fallback": "0"},
    "{{questions.items}}": {
        "required": False,
        "fallback": "Вопросы не выявлены.",
    },
    "{{evidence.appendix}}": {
        "required": False,
        "fallback": "Evidence не найдено.",
    },
}

_LAST_WARNINGS: list[str] = []
_LAST_RENDER_REPORT: dict[str, Any] = {}


def _spec_fallback(placeholder: str) -> str:
    spec = PLACEHOLDER_SPECS[placeholder]
    return str(spec.get("fallback", ""))


def _required_placeholders() -> set[str]:
    return {
        placeholder
        for placeholder, spec in PLACEHOLDER_SPECS.items()
        if spec.get("required") is True
    }


def _direct_rule_ids() -> set[str]:
    rule_ids: set[str] = set()
    for placeholder in PLACEHOLDER_SPECS:
        match = re.match(r"\{\{rules\.([a-zA-Z0-9_]+)\.(status|comment|evidence)\}\}", placeholder)
        if match:
            rule_ids.add(match.group(1))
    return rule_ids


def _add_warning(message: str) -> None:
    if message not in _LAST_WARNINGS:
        _LAST_WARNINGS.append(message)


def _reset_warnings() -> None:
    _LAST_WARNINGS.clear()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _text_or_fallback(value: Any, fallback: str) -> str:
    text = _clean_text(value)
    return text if text else fallback


def _string_value(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "да" if value else "нет"
    text = _clean_text(value)
    return text if text else fallback


def _dict_value(data: dict[str, Any], key: str, fallback: str) -> str:
    if key not in data:
        return fallback
    return _string_value(data.get(key), fallback)


def _normalize_status_value(value: Any, rule_id: str) -> str:
    status = _clean_text(value).lower()
    if not status:
        return "unknown"
    if status not in KNOWN_RULE_STATUSES:
        _add_warning(f"unexpected rule status: {status} for {rule_id}")
    return status


def _normalize_choice_text(value: Any, fallback: str = "unknown") -> str:
    text = _clean_text(value).lower()
    return text if text else fallback


def _truncate_text(text: str, limit: int = 500) -> str:
    normalized = _clean_text(text)
    if len(normalized) <= limit:
        return normalized

    cut = normalized[: limit - 3].rstrip()
    boundary = cut.rfind(" ")
    if boundary > 0:
        cut = cut[:boundary].rstrip()
    if not cut:
        cut = normalized[: limit - 3].rstrip()
    return f"{cut}..."[:limit]


def _evidence_item_text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("snippet", "text"):
        text = _clean_text(item.get(key))
        if text:
            return text
    block = item.get("block")
    if isinstance(block, dict):
        text = _clean_text(block.get("text"))
        if text:
            return text
    return ""


def _evidence_fragments(rule: dict[str, Any], limit: int = 2) -> list[str]:
    evidence = rule.get("evidence")
    if isinstance(evidence, str):
        text = _truncate_text(evidence)
        return [text] if text else []
    if not isinstance(evidence, list):
        return []

    fragments: list[str] = []
    for item in evidence:
        text = _evidence_item_text(item)
        if not text:
            continue
        fragments.append(_truncate_text(text))
        if len(fragments) >= limit:
            break
    return [fragment for fragment in fragments if fragment]


def _render_evidence(rule: dict[str, Any], fallback: str) -> str:
    fragments = _evidence_fragments(rule, limit=2)
    if not fragments:
        return fallback
    return "\n".join(fragments)


def _rule_criterion(rule: dict[str, Any]) -> str:
    return _text_or_fallback(rule.get("criterion"), "Критерий не указан")


def _rule_risk(rule: dict[str, Any]) -> str:
    return _normalize_choice_text(rule.get("risk"), "unknown")


def _rule_priority(rule: dict[str, Any]) -> str:
    return _normalize_choice_text(rule.get("priority"), "unknown")


def _rule_comment(rule: dict[str, Any], fallback: str = "Комментарий не сформирован.") -> str:
    return _text_or_fallback(rule.get("comment"), fallback)


def _format_rule_header(rule_id: str, rule: dict[str, Any]) -> str:
    status = _normalize_status_value(rule.get("status"), rule_id)
    risk = _rule_risk(rule)
    return f"[{rule_id}] {_rule_criterion(rule)} — {status} / {risk}"


def _normalize_rules(score_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rules = score_result.get("rules")
    normalized: dict[str, dict[str, Any]] = {}

    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = _clean_text(rule.get("rule_id")) or _clean_text(rule.get("id"))
            if not rule_id:
                _add_warning("skipped rule without identifiable rule_id/id")
                continue
            normalized[rule_id] = rule
    elif isinstance(rules, dict):
        for key, rule in rules.items():
            rule_id = _clean_text(key)
            if not rule_id:
                _add_warning("skipped rule without identifiable rule_id/id")
                continue
            if not isinstance(rule, dict):
                _add_warning(f"skipped non-dict rule for {rule_id}")
                continue
            normalized[rule_id] = rule

    direct_rule_ids = _direct_rule_ids()
    for rule_id in normalized:
        if rule_id not in direct_rule_ids:
            _add_warning(f"extra rule without direct placeholder: {rule_id}")

    return normalized


def _render_scenario_confidence(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return _string_value(value, fallback)
    if isinstance(value, (int, float)):
        if 0 <= value <= 1:
            percent = float(value) * 100
            if percent.is_integer():
                return f"{int(percent)}%"
            return f"{percent:.1f}".rstrip("0").rstrip(".") + "%"
        return str(value)
    return _text_or_fallback(value, fallback)


def _render_scenario_human_review(value: Any) -> str:
    if value is True:
        return "да"
    if value is False:
        return "нет"
    return "не указано"


def _render_scenario_blocking_criteria(items: Any, fallback: str) -> str:
    if not isinstance(items, list) or not items:
        return fallback

    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rule_id = _text_or_fallback(item.get("rule_id"), "unknown")
        criterion = _text_or_fallback(item.get("criterion"), "Критерий не указан")
        status = _text_or_fallback(item.get("status"), "unknown")
        risk = _text_or_fallback(item.get("risk"), "unknown")
        lines.append(f"- [{rule_id}] {criterion} — {status} / {risk}")
        message = _clean_text(item.get("message"))
        if message:
            lines.append(f"  {message}")
    return "\n".join(lines) if lines else fallback


def _render_scenario_reasons(items: Any, fallback: str) -> str:
    if not isinstance(items, list) or not items:
        return fallback

    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        message = _text_or_fallback(item.get("message"), "Причина не указана")
        rule_id = _clean_text(item.get("rule_id"))
        if rule_id:
            lines.append(f"- {message} ({rule_id})")
        else:
            lines.append(f"- {message}")
    return "\n".join(lines) if lines else fallback


def _resolve_stat_value(score_result: dict[str, Any], key: str, fallback: str) -> str:
    stats = score_result.get("stats")
    if not isinstance(stats, dict) or key not in stats:
        return fallback
    return _string_value(stats.get(key), fallback)


def _human_review_count(score_result: dict[str, Any], rules_by_id: dict[str, dict[str, Any]]) -> str:
    stats = score_result.get("stats")
    if isinstance(stats, dict) and stats.get("human_review_required") is not None:
        value = stats.get("human_review_required")
        if isinstance(value, bool):
            return str(int(value))
        return _text_or_fallback(value, "0")
    return str(sum(1 for rule in rules_by_id.values() if rule.get("human_review_required") is True))


def _summary_general_conclusion(
    score_result: dict[str, Any],
    scenario_result: dict[str, Any],
    fallback: str,
) -> str:
    summary = score_result.get("summary")
    if isinstance(summary, dict):
        for key in ("general_conclusion", "conclusion"):
            text = _clean_text(summary.get(key))
            if text:
                return text

    for source in (score_result, scenario_result):
        for key in ("general_conclusion", "conclusion"):
            text = _clean_text(source.get(key))
            if text:
                return text

    return fallback


def _attention_rules(rules_by_id: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    selected: list[tuple[str, dict[str, Any]]] = []
    for rule_id, rule in rules_by_id.items():
        status = _normalize_status_value(rule.get("status"), rule_id)
        if status in {"fail", "unknown", "conflict"} or rule.get("human_review_required") is True:
            selected.append((rule_id, rule))
    return selected


def _render_attention_criteria(rules_by_id: dict[str, dict[str, Any]], fallback: str) -> str:
    lines: list[str] = []
    for rule_id, rule in _attention_rules(rules_by_id):
        lines.append(f"- {_format_rule_header(rule_id, rule)}")
        lines.append(f"  Комментарий: {_rule_comment(rule)}")
    return "\n".join(lines) if lines else fallback


def _render_confirmed_criteria(rules_by_id: dict[str, dict[str, Any]], fallback: str) -> str:
    lines: list[str] = []
    for rule_id, rule in rules_by_id.items():
        if _normalize_status_value(rule.get("status"), rule_id) == "pass":
            lines.append(f"- {_format_rule_header(rule_id, rule)}")
    return "\n".join(lines) if lines else fallback


def _render_low_priority_unknown_criteria(
    rules_by_id: dict[str, dict[str, Any]],
    fallback: str,
) -> str:
    lines: list[str] = []
    for rule_id, rule in rules_by_id.items():
        status = _normalize_status_value(rule.get("status"), rule_id)
        if status == "unknown" and _rule_priority(rule) == "low":
            lines.append(f"- {_format_rule_header(rule_id, rule)}")
    return "\n".join(lines) if lines else fallback


def _question_rules(rules_by_id: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    selected: list[tuple[str, dict[str, Any]]] = []
    for rule_id, rule in rules_by_id.items():
        status = _normalize_status_value(rule.get("status"), rule_id)
        if rule.get("human_review_required") is True or status in {"unknown", "conflict", "fail"}:
            selected.append((rule_id, rule))
    return selected


def _render_questions(rules_by_id: dict[str, dict[str, Any]], fallback: str) -> tuple[str, str]:
    questions = []
    for rule_id, rule in _question_rules(rules_by_id):
        status = _normalize_status_value(rule.get("status"), rule_id)
        risk = _rule_risk(rule)
        criterion = _rule_criterion(rule)
        questions.append(
            f"- Уточнить критерий: {criterion} ([{rule_id}], status={status}, risk={risk})"
        )

    if not questions:
        return "0", fallback
    return str(len(questions)), "\n".join(questions)


def _render_evidence_appendix(rules_by_id: dict[str, dict[str, Any]], fallback: str) -> str:
    lines: list[str] = []
    for rule_id, rule in list(rules_by_id.items())[:3]:
        evidence = _render_evidence(rule, fallback)
        if evidence == fallback:
            continue
        lines.append(f"- [{rule_id}] {_rule_criterion(rule)}")
        lines.append(f"  Основание: {evidence}")
    return "\n".join(lines) if lines else fallback


def _xml_text(value: str) -> str:
    text = XML_INVALID_RE.sub("", value)
    escaped_lines = [escape(line, {'"': "&quot;", "'": "&apos;"}) for line in text.split("\n")]
    return '</w:t><w:br/><w:t xml:space="preserve">'.join(escaped_lines)


def _read_document_xml(docx_path: Path) -> str:
    try:
        with zipfile.ZipFile(docx_path, "r") as archive:
            try:
                content = archive.read("word/document.xml")
            except KeyError as exc:
                raise ValueError("word/document.xml is missing in DOCX template") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid DOCX zip: {docx_path}") from exc
    return content.decode("utf-8")


def _extract_placeholders_from_document_xml(document_xml: str) -> set[str]:
    placeholders = set(PLACEHOLDER_RE.findall(document_xml))
    if not placeholders:
        raise ValueError(f"No placeholders found in DOCX template; {RUN_SPLITTING_MESSAGE}")
    return placeholders


def extract_docx_placeholders(template_path: str | Path) -> set[str]:
    path = Path(template_path)
    return _extract_placeholders_from_document_xml(_read_document_xml(path))


def build_placeholder_values(score_result: dict) -> dict[str, str]:
    if not isinstance(score_result, dict):
        raise ValueError("score_result must be a dict")

    _reset_warnings()
    values = {
        placeholder: _spec_fallback(placeholder)
        for placeholder in PLACEHOLDER_SPECS
    }
    rules_by_id = _normalize_rules(score_result)
    scenario_result = score_result.get("scenario_result")
    if not isinstance(scenario_result, dict):
        scenario_result = {}

    values["{{input.path}}"] = _dict_value(
        score_result,
        "input_path",
        _spec_fallback("{{input.path}}"),
    )
    values["{{stats.document_count}}"] = _dict_value(
        score_result,
        "document_count",
        _spec_fallback("{{stats.document_count}}"),
    )
    values["{{stats.criteria_count}}"] = _dict_value(
        score_result,
        "criteria_count",
        _spec_fallback("{{stats.criteria_count}}"),
    )
    values["{{stats.rules_count}}"] = _dict_value(
        score_result,
        "rules_count",
        _spec_fallback("{{stats.rules_count}}"),
    )
    for key in ("pass", "fail", "unknown", "conflict", "risk_low", "risk_medium", "risk_high"):
        values[f"{{{{stats.{key}}}}}"] = _resolve_stat_value(
            score_result,
            key,
            _spec_fallback(f"{{{{stats.{key}}}}}"),
        )
    values["{{stats.human_review_required}}"] = _human_review_count(score_result, rules_by_id)

    values["{{scenario.scenario}}"] = _dict_value(
        scenario_result,
        "scenario",
        _spec_fallback("{{scenario.scenario}}"),
    )
    values["{{scenario.recommendation}}"] = _dict_value(
        scenario_result,
        "recommendation",
        _spec_fallback("{{scenario.recommendation}}"),
    )
    values["{{scenario.confidence}}"] = _render_scenario_confidence(
        scenario_result.get("confidence"),
        _spec_fallback("{{scenario.confidence}}"),
    )
    values["{{scenario.human_review_required}}"] = _render_scenario_human_review(
        scenario_result.get("human_review_required")
    )
    values["{{scenario.blocking_criteria}}"] = _render_scenario_blocking_criteria(
        scenario_result.get("blocking_criteria"),
        _spec_fallback("{{scenario.blocking_criteria}}"),
    )
    values["{{scenario.reasons}}"] = _render_scenario_reasons(
        scenario_result.get("reasons"),
        _spec_fallback("{{scenario.reasons}}"),
    )

    for rule_id in _direct_rule_ids():
        rule = rules_by_id.get(rule_id, {})
        status_placeholder = f"{{{{rules.{rule_id}.status}}}}"
        comment_placeholder = f"{{{{rules.{rule_id}.comment}}}}"
        evidence_placeholder = f"{{{{rules.{rule_id}.evidence}}}}"
        values[status_placeholder] = _normalize_status_value(rule.get("status"), rule_id)
        values[comment_placeholder] = _rule_comment(rule, _spec_fallback(comment_placeholder))
        values[evidence_placeholder] = _render_evidence(rule, _spec_fallback(evidence_placeholder))

    values["{{summary.general_conclusion}}"] = _summary_general_conclusion(
        score_result,
        scenario_result,
        _spec_fallback("{{summary.general_conclusion}}"),
    )
    values["{{summary.attention_criteria}}"] = _render_attention_criteria(
        rules_by_id,
        _spec_fallback("{{summary.attention_criteria}}"),
    )
    values["{{summary.confirmed_criteria}}"] = _render_confirmed_criteria(
        rules_by_id,
        _spec_fallback("{{summary.confirmed_criteria}}"),
    )
    values["{{summary.low_priority_unknown_criteria}}"] = _render_low_priority_unknown_criteria(
        rules_by_id,
        _spec_fallback("{{summary.low_priority_unknown_criteria}}"),
    )

    questions_count, questions_items = _render_questions(
        rules_by_id,
        _spec_fallback("{{questions.items}}"),
    )
    values["{{questions.count}}"] = questions_count
    values["{{questions.items}}"] = questions_items
    values["{{evidence.appendix}}"] = _render_evidence_appendix(
        rules_by_id,
        _spec_fallback("{{evidence.appendix}}"),
    )
    return values


def validate_template_placeholders(
    found_placeholders: set[str],
    values: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    expected = len(PLACEHOLDER_SPECS)

    if not found_placeholders:
        errors.append(f"No placeholders found in DOCX template; {RUN_SPLITTING_MESSAGE}")

    unknown_placeholders = sorted(found_placeholders - set(PLACEHOLDER_SPECS))
    for placeholder in unknown_placeholders:
        errors.append(f"Unknown placeholder in DOCX template: {placeholder}")

    required_placeholders = _required_placeholders()
    missing_required = sorted(required_placeholders - found_placeholders)
    for placeholder in missing_required:
        errors.append(f"Required placeholder is missing in DOCX template: {placeholder}; {RUN_SPLITTING_MESSAGE}")

    if len(found_placeholders) < expected * 0.5:
        errors.append(
            "Found placeholders count is less than 50% of PLACEHOLDER_SPECS "
            f"({len(found_placeholders)} < {expected} * 0.5); {RUN_SPLITTING_MESSAGE}"
        )

    missing_values = sorted(found_placeholders - set(values))
    for placeholder in missing_values:
        errors.append(f"No rendered value for placeholder: {placeholder}")

    optional_missing = sorted(set(PLACEHOLDER_SPECS) - required_placeholders - found_placeholders)
    for placeholder in optional_missing:
        _add_warning(f"optional placeholder missing in DOCX template: {placeholder}")

    return errors


def _validate_output_docx(output_path: Path) -> None:
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise ValueError(f"Output DOCX was not created or is empty: {output_path}")
    try:
        with zipfile.ZipFile(output_path, "r") as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names:
                raise ValueError("Output DOCX is missing [Content_Types].xml")
            if "word/document.xml" not in names:
                raise ValueError("Output DOCX is missing word/document.xml")
            document_xml = archive.read("word/document.xml").decode("utf-8")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Output DOCX is not a valid zip: {output_path}") from exc

    remaining = sorted(set(PLACEHOLDER_RE.findall(document_xml)))
    if remaining:
        raise ValueError(f"Output DOCX contains unreplaced placeholders: {', '.join(remaining)}")


def _write_replaced_docx(
    template_path: Path,
    output_path: Path,
    document_xml: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document_bytes = document_xml.encode("utf-8")
    with zipfile.ZipFile(template_path, "r") as source:
        with zipfile.ZipFile(output_path, "w") as target:
            for item in source.infolist():
                data = document_bytes if item.filename == "word/document.xml" else source.read(item.filename)
                target.writestr(item, data)


def render_docx_summary(
    score_result: dict,
    template_path: str | Path,
    output_path: str | Path,
) -> Path:
    template = Path(template_path)
    output = Path(output_path)

    document_xml = _read_document_xml(template)
    found_placeholders = _extract_placeholders_from_document_xml(document_xml)
    values = build_placeholder_values(score_result)
    errors = validate_template_placeholders(found_placeholders, values)
    required_placeholders = _required_placeholders()
    required_missing = required_placeholders - found_placeholders
    replaced_placeholders = found_placeholders & set(values)

    _LAST_RENDER_REPORT.clear()
    _LAST_RENDER_REPORT.update(
        {
            "found_placeholders_count": len(found_placeholders),
            "expected_placeholders_count": len(PLACEHOLDER_SPECS),
            "required_placeholders_count": len(required_placeholders),
            "required_found_count": len(required_placeholders & found_placeholders),
            "required_missing_count": len(required_missing),
            "replaced_placeholders_count": len(replaced_placeholders),
            "warnings_count": len(_LAST_WARNINGS),
            "validation_errors": list(errors),
        }
    )

    if errors:
        raise ValueError("Validation failed:\n" + "\n".join(errors))

    for placeholder in sorted(found_placeholders, key=len, reverse=True):
        document_xml = document_xml.replace(placeholder, _xml_text(values[placeholder]))

    _write_replaced_docx(template, output, document_xml)
    _validate_output_docx(output)
    _LAST_RENDER_REPORT["warnings_count"] = len(_LAST_WARNINGS)
    return output


def write_docx_summary(
    score_result: dict,
    template_path: str | Path,
    output_path: str | Path,
) -> Path:
    return render_docx_summary(score_result, template_path, output_path)


def _load_score(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid score JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("score JSON must contain an object")
    return data


def _print_report(
    score_path: Path,
    template_path: Path,
    output_path: Path,
    final_result: str,
) -> None:
    report = dict(_LAST_RENDER_REPORT)
    print(f"score path: {score_path}")
    print(f"template path: {template_path}")
    print(f"output path: {output_path}")
    print(f"found placeholders count: {report.get('found_placeholders_count', 0)}")
    print(f"expected placeholders count: {len(PLACEHOLDER_SPECS)}")
    print(f"required placeholders count: {len(_required_placeholders())}")
    print(f"replaced placeholders count: {report.get('replaced_placeholders_count', 0)}")
    print(f"warnings count: {len(_LAST_WARNINGS)}")
    for warning in _LAST_WARNINGS:
        print(f"WARNING: {warning}")
    print(f"final result: {final_result}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Render tender summary DOCX from tender_score.json.")
    parser.add_argument("--score", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    score_path = Path(os.fspath(args.score))
    template_path = Path(os.fspath(args.template))
    output_path = Path(os.fspath(args.out))

    try:
        if not score_path.exists():
            raise FileNotFoundError(f"score JSON not found: {score_path}")
        if not template_path.exists():
            raise FileNotFoundError(f"DOCX template not found: {template_path}")
        score_result = _load_score(score_path)
        render_docx_summary(score_result, template_path, output_path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        _print_report(score_path, template_path, output_path, "failed")
        return 1

    _print_report(score_path, template_path, output_path, "success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
