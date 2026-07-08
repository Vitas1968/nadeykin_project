from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


KNOWN_STATUSES = {"pass", "fail", "conflict", "unknown"}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()
    return text or None


def _field_text(rule: dict[str, Any], field_name: str, fallback: str) -> str:
    return _clean_text(rule.get(field_name)) or fallback


def _normalized_status(rule: dict[str, Any]) -> str:
    return (_clean_text(rule.get("status")) or "").lower()


def _normalized_priority(rule: dict[str, Any]) -> str:
    return (_clean_text(rule.get("priority")) or "").lower()


def _has_evidence_concerns(rule: dict[str, Any]) -> bool:
    concerns = rule.get("evidence_concerns")
    return isinstance(concerns, list) and any(_clean_text(item) for item in concerns)


def _criterion_or_id(rule: dict[str, Any]) -> str:
    return (
        _clean_text(rule.get("criterion"))
        or _clean_text(rule.get("id"))
        or "неизвестный критерий"
    )


def _question_title(rule: dict[str, Any]) -> str:
    return (
        _clean_text(rule.get("block"))
        or _clean_text(rule.get("criterion"))
        or _clean_text(rule.get("id"))
        or "неизвестный критерий"
    )


def _needs_question(rule: dict[str, Any]) -> bool:
    if rule.get("human_review_required") is True:
        return True

    status = _normalized_status(rule)
    if status in {"fail", "conflict"}:
        return True
    if status == "unknown":
        return _normalized_priority(rule) != "low"
    if status == "pass":
        return _normalized_priority(rule) == "high" and _has_evidence_concerns(rule)
    return False


def _normalize_evidence_fragment(value: Any) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 320:
        text = f"{text[:317]}..."
    return text


def _evidence_value(item: dict[str, Any]) -> Any | None:
    snippet = _clean_text(item.get("snippet"))
    if snippet is not None:
        return snippet

    text = _clean_text(item.get("text"))
    if text is not None:
        return text

    block = item.get("block")
    if isinstance(block, dict):
        block_text = _clean_text(block.get("text"))
        if block_text is not None:
            return block_text

    return None


def _evidence_fragments(rule: dict[str, Any]) -> list[str]:
    evidence = rule.get("evidence")
    if not isinstance(evidence, list):
        return []

    fragments: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        value = _evidence_value(item)
        if value is None:
            continue
        fragment = _normalize_evidence_fragment(value)
        if fragment and len(fragments) < 3:
            fragments.append(fragment)
    return fragments


def _build_question_text(rule: dict[str, Any]) -> str:
    criterion_or_id = _criterion_or_id(rule)
    status = _normalized_status(rule)

    if status == "unknown":
        return f"Уточнить данные по критерию: {criterion_or_id}."
    if status == "fail":
        return f"Проверить негативный признак по критерию: {criterion_or_id}."
    if status == "conflict":
        return f"Разобрать противоречие по критерию: {criterion_or_id}."
    if status == "pass" and _has_evidence_concerns(rule):
        return f"Проверить подтверждение по критерию: {criterion_or_id}."
    return f"Проверить критерий вручную: {criterion_or_id}."


def render_questions(score_result: dict[str, Any]) -> str:
    if not isinstance(score_result, dict):
        raise ValueError("score_result must be a dict")

    rules = score_result.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError('score_result["rules"] must be a list')

    question_rules = [
        rule for rule in rules if isinstance(rule, dict) and _needs_question(rule)
    ]

    lines = ["# Вопросы заказчику / человеку", ""]
    if not question_rules:
        lines.extend(
            [
                "Вопросы не выявлены.",
                "",
                "Все критерии либо подтверждены, либо не требуют ручной проверки на текущем этапе.",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend([f"Всего вопросов: {len(question_rules)}", ""])

    for index, rule in enumerate(question_rules, start=1):
        lines.extend(
            [
                f"## {index}. {_question_title(rule)}",
                "",
                f"- ID критерия: `{_field_text(rule, 'id', 'unknown')}`",
                f"- Блок: {_field_text(rule, 'block', 'Не указан')}",
                f"- Критерий: {_field_text(rule, 'criterion', 'Не указан')}",
                f"- Приоритет: {_field_text(rule, 'priority', 'Не указан')}",
                f"- Статус: {_field_text(rule, 'status', 'Не указан')}",
                f"- Риск: {_field_text(rule, 'risk', 'Не указан')}",
                "",
                f"**Вопрос:** {_build_question_text(rule)}",
                "",
                f"**Причина:** {_field_text(rule, 'comment', 'Требуется ручная проверка.')}",
                "",
                "**Evidence:**",
                "",
            ]
        )

        fragments = _evidence_fragments(rule)
        if fragments:
            lines.extend(f"- {fragment}" for fragment in fragments)
        else:
            lines.append("Evidence не найдено.")

        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_questions(score_result: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    markdown = render_questions(score_result)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(markdown)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("score_json_path")
    parser.add_argument("output_md_path")
    args = parser.parse_args()

    score_path = Path(args.score_json_path)
    output_path = Path(args.output_md_path)
    with score_path.open("r", encoding="utf-8") as file:
        score_result = json.load(file)

    written_path = write_questions(score_result, output_path)
    print(f"Wrote: {written_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
