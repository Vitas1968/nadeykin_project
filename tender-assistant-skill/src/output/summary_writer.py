from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


KNOWN_STATUSES = {"pass", "fail", "conflict", "unknown"}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _field_text(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    text = _clean_text(value)
    return text or fallback


def _normalized_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = _clean_text(value).lower()
    return text or fallback


def _normalized_status(rule: dict[str, Any]) -> str:
    return _normalized_text(rule.get("status"), "unknown")


def _normalized_risk(rule: dict[str, Any]) -> str:
    return _normalized_text(rule.get("risk"), "")


def _normalized_priority(rule: dict[str, Any]) -> str:
    return _normalized_text(rule.get("priority"), "")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _valid_rules(score_result: dict[str, Any]) -> list[dict[str, Any]]:
    rules = score_result.get("rules")
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def _recount_stats(valid_rules: list[dict[str, Any]]) -> dict[str, int]:
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

    for rule in valid_rules:
        status = _normalized_status(rule)
        if status in KNOWN_STATUSES:
            stats[status] += 1

        risk = _normalized_risk(rule)
        if risk == "low":
            stats["risk_low"] += 1
        elif risk == "medium":
            stats["risk_medium"] += 1
        elif risk == "high":
            stats["risk_high"] += 1

        if rule.get("human_review_required") is True:
            stats["human_review_required"] += 1

    return stats


def _resolve_stats(score_result: dict[str, Any], valid_rules: list[dict[str, Any]]) -> dict[str, int]:
    recounted = _recount_stats(valid_rules)
    source_stats = score_result.get("stats")
    if not isinstance(source_stats, dict):
        return recounted

    resolved: dict[str, int] = {}
    for key, fallback_value in recounted.items():
        value = _optional_int(source_stats.get(key))
        resolved[key] = fallback_value if value is None else value
    return resolved


def _top_level_count(
    score_result: dict[str, Any],
    field_name: str,
    fallback: int | str,
) -> int | str:
    if field_name not in score_result:
        return fallback
    value = _optional_int(score_result.get(field_name))
    return fallback if value is None else value


def _evidence_value(item: dict[str, Any]) -> Any | None:
    snippet = item.get("snippet")
    if snippet is not None and _clean_text(snippet):
        return snippet

    text = item.get("text")
    if text is not None and _clean_text(text):
        return text

    block = item.get("block")
    if isinstance(block, dict):
        block_text = block.get("text")
        if block_text is not None and _clean_text(block_text):
            return block_text

    return None


def _truncate_evidence(text: str) -> str:
    if len(text) > 240:
        return f"{text[:237]}..."
    return text


def _evidence_fragments(rule: dict[str, Any], limit: int = 2) -> list[str]:
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
        fragment = _truncate_evidence(_clean_text(value))
        if fragment:
            fragments.append(fragment)
        if len(fragments) >= limit:
            break
    return fragments


def _evidence_summary(rule: dict[str, Any]) -> str:
    evidence = rule.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return "не найдено"
    fragments = _evidence_fragments(rule, limit=1)
    if not fragments:
        return "есть, фрагмент не извлечён"
    return fragments[0]


def _attention_title(rule: dict[str, Any]) -> str:
    return (
        _field_text(rule.get("block"), "")
        or _field_text(rule.get("criterion"), "")
        or _field_text(rule.get("id"), "")
        or "неизвестный критерий"
    )


def _compact_title(rule: dict[str, Any]) -> str:
    return (
        _field_text(rule.get("criterion"), "")
        or _field_text(rule.get("block"), "")
        or "Не указан"
    )


def _is_attention_rule(rule: dict[str, Any]) -> bool:
    if rule.get("human_review_required") is True:
        return True

    status = _normalized_status(rule)
    if status in {"fail", "conflict"}:
        return True
    if status == "unknown" and _normalized_priority(rule) != "low":
        return True
    return _normalized_risk(rule) == "high"


def _general_conclusion(
    valid_rules: list[dict[str, Any]],
    attention_rules: list[dict[str, Any]],
) -> str:
    if len(valid_rules) == 0:
        return "Данные для сводки отсутствуют или скоринг не содержит правил."
    if attention_rules:
        return "Требуется ручная проверка перед принятием решения по тендеру."
    if all(_normalized_status(rule) == "pass" for rule in valid_rules):
        return "По текущим критериям критичные риски не выявлены. Итог не является финальным решением без проверки человеком."
    return "Критичные риски не выявлены, но часть критериев не подтверждена. Требуется выборочная проверка."


def _manual_review_text(value: Any) -> str:
    if value is True:
        return "да"
    if value is False:
        return "нет"
    return "не указано"


def _append_scenario_section(lines: list[str], score_result: dict[str, Any]) -> None:
    lines.extend(["## 2. Итоговый сценарий", ""])

    scenario_result = score_result.get("scenario_result")
    if not isinstance(scenario_result, dict):
        lines.extend(["Итоговый сценарий не рассчитан.", ""])
        return

    lines.extend(
        [
            f"- Сценарий: {_field_text(scenario_result.get('scenario'), '—')}",
            f"- Рекомендация: {_field_text(scenario_result.get('recommendation'), '—')}",
            f"- Уверенность: {_field_text(scenario_result.get('confidence'), '—')}",
            f"- Требуется ручная проверка: {_manual_review_text(scenario_result.get('human_review_required'))}",
            "",
        ]
    )

    blocking_criteria = scenario_result.get("blocking_criteria")
    if isinstance(blocking_criteria, list):
        valid_blocking_criteria = [item for item in blocking_criteria if isinstance(item, dict)]
    else:
        valid_blocking_criteria = []

    if valid_blocking_criteria:
        lines.extend(["Блокирующие критерии:", ""])
        for item in valid_blocking_criteria:
            lines.append(
                f"- `{_field_text(item.get('rule_id'), '—')}` — "
                f"status: {_field_text(item.get('status'), '—')}, "
                f"risk: {_field_text(item.get('risk'), '—')}, "
                f"priority: {_field_text(item.get('priority'), '—')}"
            )
        lines.append("")
    else:
        lines.extend(["Блокирующие критерии не выявлены.", ""])

    reasons = scenario_result.get("reasons")
    if not isinstance(reasons, list):
        return

    valid_reasons = [item for item in reasons if isinstance(item, dict)]
    if not valid_reasons:
        return

    lines.extend(["Причины:", ""])
    for item in valid_reasons[:5]:
        message = _field_text(item.get("message"), "Причина не указана.")
        rule_id = _field_text(item.get("rule_id"), "")
        if rule_id:
            lines.append(f"- {message} (`{rule_id}`)")
        else:
            lines.append(f"- {message}")
    lines.append("")


def _append_attention_section(lines: list[str], attention_rules: list[dict[str, Any]]) -> None:
    lines.extend(["## 4. Критерии, требующие внимания", ""])
    if not attention_rules:
        lines.extend(["Критерии, требующие ручной проверки, не выявлены.", ""])
        return

    for index, rule in enumerate(attention_rules[:10], start=1):
        lines.extend(
            [
                f"### {index}. {_attention_title(rule)}",
                "",
                f"- ID критерия: `{_field_text(rule.get('id'), 'unknown')}`",
                f"- Блок: {_field_text(rule.get('block'), 'Не указан')}",
                f"- Критерий: {_field_text(rule.get('criterion'), 'Не указан')}",
                f"- Приоритет: {_field_text(rule.get('priority'), 'Не указан')}",
                f"- Статус: {_field_text(rule.get('status'), 'unknown')}",
                f"- Риск: {_field_text(rule.get('risk'), 'Не указан')}",
                f"- Комментарий: {_field_text(rule.get('comment'), 'Комментарий не указан.')}",
                "",
            ]
        )

        fragments = _evidence_fragments(rule)
        if fragments:
            lines.extend(["Evidence:", ""])
            lines.extend(f"- {fragment}" for fragment in fragments)
        else:
            lines.append("Evidence не найдено.")
        lines.append("")

    if len(attention_rules) > 10:
        lines.extend(
            [
                f"Показано 10 из {len(attention_rules)}. Остальные см. в tender_score.json.",
                "",
            ]
        )


def _append_pass_section(lines: list[str], pass_rules: list[dict[str, Any]]) -> None:
    lines.extend(["## 5. Подтверждённые критерии", ""])
    if not pass_rules:
        lines.extend(["Подтверждённые критерии не выявлены.", ""])
        return

    for rule in pass_rules[:12]:
        lines.append(
            f"- `{_field_text(rule.get('id'), 'unknown')}` — {_compact_title(rule)}. Evidence: {_evidence_summary(rule)}"
        )
    lines.append("")

    if len(pass_rules) > 12:
        lines.extend(
            [
                f"Показано 12 из {len(pass_rules)}. Остальные см. в tender_score.json.",
                "",
            ]
        )


def _append_low_unknown_section(lines: list[str], low_unknown_rules: list[dict[str, Any]]) -> None:
    lines.extend(["## 6. Неподтверждённые низкоприоритетные критерии", ""])
    if not low_unknown_rules:
        lines.extend(["Низкоприоритетные неподтверждённые критерии не выявлены.", ""])
        return

    for rule in low_unknown_rules[:8]:
        lines.append(f"- `{_field_text(rule.get('id'), 'unknown')}` — {_compact_title(rule)}")
    lines.append("")

    if len(low_unknown_rules) > 8:
        lines.extend(
            [
                f"Показано 8 из {len(low_unknown_rules)}. Остальные см. в tender_score.json.",
                "",
            ]
        )


def render_summary(score_result: dict[str, Any]) -> str:
    if not isinstance(score_result, dict):
        raise ValueError("score_result must be a dict")

    valid_rules = _valid_rules(score_result)
    stats = _resolve_stats(score_result, valid_rules)
    document_count = _top_level_count(score_result, "document_count", "Не указано")
    criteria_count = _top_level_count(score_result, "criteria_count", len(valid_rules))
    rules_count = _top_level_count(score_result, "rules_count", len(valid_rules))

    attention_rules = [rule for rule in valid_rules if _is_attention_rule(rule)]
    pass_rules = [rule for rule in valid_rules if _normalized_status(rule) == "pass"]
    low_unknown_rules = [
        rule
        for rule in valid_rules
        if _normalized_status(rule) == "unknown"
        and _normalized_priority(rule) == "low"
        and rule.get("human_review_required") is not True
        and not _is_attention_rule(rule)
    ]

    lines = [
        "# Сводка по тендеру",
        "",
        "## 1. Общий вывод",
        "",
        _general_conclusion(valid_rules, attention_rules),
        "",
    ]

    _append_scenario_section(lines, score_result)

    lines.extend(
        [
            "## 3. Краткая статистика",
            "",
            f"- Входной путь: `{_field_text(score_result.get('input_path'), 'Не указан')}`",
            f"- Документов: {document_count}",
            f"- Критериев всего: {criteria_count}",
            f"- Правил оценено: {rules_count}",
            f"- Подтверждено: {stats['pass']}",
            f"- Не подтверждено: {stats['unknown']}",
            f"- Негативные признаки: {stats['fail']}",
            f"- Противоречия: {stats['conflict']}",
            f"- Низкий риск: {stats['risk_low']}",
            f"- Средний риск: {stats['risk_medium']}",
            f"- Высокий риск: {stats['risk_high']}",
            f"- Требуют ручной проверки: {stats['human_review_required']}",
            "",
        ]
    )

    _append_attention_section(lines, attention_rules)
    _append_pass_section(lines, pass_rules)
    _append_low_unknown_section(lines, low_unknown_rules)

    return "\n".join(lines).rstrip("\n") + "\n"


def write_summary(score_result: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    markdown = render_summary(score_result)
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

    written_path = write_summary(score_result, output_path)
    print(f"Wrote: {written_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
