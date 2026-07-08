from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCENARIOS = {"not_relevant", "relevant_direct", "relevant_dealer", "need_human_review"}

CORE_SUBJECT_RULE_IDS = {"subject_okpd2_oil", "subject_title_oil", "purchase_type_goods"}
INDICATOR_ONLY_RULE_IDS = {"msp_restriction"}
MSP_RULE_ID = "msp_restriction"

VALID_STATUSES = {"pass", "fail", "unknown", "conflict"}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_RISKS = {"low", "medium", "high"}

RECOMMENDATIONS = {
    "not_relevant": (
        "Исключить тендер из воронки: базовая релевантность предмета закупки "
        "не подтверждена или найден явный негативный признак."
    ),
    "relevant_direct": (
        "Передать тендер в прямую обработку профильному подразделению: предмет закупки подтверждён, "
        "блокирующие риски по текущим критериям не выявлены."
    ),
    "relevant_dealer": (
        "Передать тендер дилеру/партнёру: тендер релевантен, но есть признак "
        "ограничения МСП или участия через партнёра."
    ),
    "need_human_review": (
        "Передать на ручную проверку: данных недостаточно, есть противоречия "
        "или значимые риски."
    ),
}


def classify_scenario(score_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(score_result, dict):
        raise ValueError("score_result must be a dict")

    return classify_rules(score_result.get("rules"))


def classify_rules(rules: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_rules = _normalize_rules(rules)
    stats = _build_stats(normalized_rules)
    reasons: list[dict[str, Any]] = []
    blocking_criteria: list[dict[str, Any]] = []
    seen_blocking_rule_ids: set[str] = set()

    def add_rule_reason(rule: dict[str, Any], message: str) -> None:
        reasons.append(_make_reason(message, rule))

    def add_general_reason(message: str) -> None:
        reasons.append(_make_reason(message))

    def add_blocker(rule: dict[str, Any]) -> None:
        rule_id = rule["output_rule_id"]
        blocking_key = rule["blocking_key"]
        if blocking_key in seen_blocking_rule_ids:
            return

        seen_blocking_rule_ids.add(blocking_key)
        blocking_criteria.append(
            {
                "rule_id": rule_id,
                "criterion": rule["criterion"],
                "status": rule["status"],
                "risk": rule["risk"],
                "priority": rule["priority"],
                "comment": rule["comment"],
            }
        )

    if not normalized_rules:
        add_general_reason("Скоринг не содержит правил.")
        return _make_result(
            "need_human_review",
            "low",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    core_rules = [rule for rule in normalized_rules if rule["rule_id"] in CORE_SUBJECT_RULE_IDS]
    if stats["core_total"] == 0:
        add_general_reason("Core subject criteria не найдены в rules.")
        return _make_result(
            "need_human_review",
            "low",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    core_fails_with_review = [
        rule for rule in core_rules if rule["status"] == "fail" and rule["human_review_required"]
    ]
    if core_fails_with_review:
        for rule in core_fails_with_review:
            add_rule_reason(
                rule,
                "Core subject criterion имеет status fail и требует ручной проверки.",
            )
            add_blocker(rule)
        return _make_result(
            "need_human_review",
            "medium",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    core_fails_without_review = [
        rule for rule in core_rules if rule["status"] == "fail" and not rule["human_review_required"]
    ]
    if core_fails_without_review:
        for rule in core_fails_without_review:
            add_rule_reason(
                rule,
                "Core subject criterion имеет status fail без требования ручной проверки.",
            )
            add_blocker(rule)
        return _make_result(
            "not_relevant",
            "medium",
            False,
            reasons,
            blocking_criteria,
            stats,
        )

    msp_high_risk_rules = [
        rule for rule in normalized_rules if rule["rule_id"] == MSP_RULE_ID and rule["risk"] == "high"
    ]
    if msp_high_risk_rules:
        for rule in msp_high_risk_rules:
            add_rule_reason(rule, "По msp_restriction найден высокий риск.")
            add_blocker(rule)
        return _make_result(
            "need_human_review",
            "medium",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    msp_conflict_rules = [
        rule for rule in normalized_rules if rule["rule_id"] == MSP_RULE_ID and rule["status"] == "conflict"
    ]
    if msp_conflict_rules:
        for rule in msp_conflict_rules:
            add_rule_reason(rule, "По msp_restriction найдено противоречие.")
            add_blocker(rule)
        return _make_result(
            "need_human_review",
            "medium",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    high_conflict_rules = [
        rule
        for rule in normalized_rules
        if rule["rule_id"] != MSP_RULE_ID
        and rule["priority"] == "high"
        and rule["status"] == "conflict"
    ]
    if high_conflict_rules:
        for rule in high_conflict_rules:
            add_rule_reason(rule, "По high-priority rule найдено противоречие.")
            add_blocker(rule)
        return _make_result(
            "need_human_review",
            "medium",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    significant_fail_rules = [
        rule
        for rule in normalized_rules
        if rule["rule_id"] not in CORE_SUBJECT_RULE_IDS
        and rule["rule_id"] not in INDICATOR_ONLY_RULE_IDS
        and rule["status"] == "fail"
        and rule["priority"] in {"high", "medium"}
    ]
    if significant_fail_rules:
        for rule in significant_fail_rules:
            add_rule_reason(rule, "Найден fail по значимому non-core критерию.")
            add_blocker(rule)
        return _make_result(
            "need_human_review",
            "medium",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    high_unknown_rules = [
        rule
        for rule in normalized_rules
        if rule["rule_id"] not in INDICATOR_ONLY_RULE_IDS
        and rule["priority"] == "high"
        and rule["status"] == "unknown"
    ]
    if high_unknown_rules:
        for rule in high_unknown_rules:
            add_rule_reason(rule, "Не подтверждён high-priority критерий.")
            add_blocker(rule)
        return _make_result(
            "need_human_review",
            "medium",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    human_review_rules = [
        rule
        for rule in normalized_rules
        if rule["human_review_required"] and not _is_neutral_rule(rule)
    ]
    if human_review_rules:
        for rule in human_review_rules:
            add_rule_reason(rule, "Rule-level логика требует ручной проверки.")
            add_blocker(rule)
        return _make_result(
            "need_human_review",
            "medium",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    core_not_pass_rules = [rule for rule in core_rules if rule["status"] != "pass"]
    if core_not_pass_rules:
        for rule in core_not_pass_rules:
            add_rule_reason(rule, "Core subject criterion не имеет status pass.")
            add_blocker(rule)
        return _make_result(
            "need_human_review",
            "medium",
            True,
            reasons,
            blocking_criteria,
            stats,
        )

    msp_unconfirmed_pass_rules = [
        rule
        for rule in normalized_rules
        if rule["rule_id"] == MSP_RULE_ID
        and rule["status"] == "pass"
        and not rule["explicit_dealer_indicator"]
    ]
    for rule in msp_unconfirmed_pass_rules:
        add_rule_reason(
            rule,
            "msp_restriction имеет status pass, но явный МСП/СМП, dealer или partner признак в evidence не найден.",
        )

    if stats["msp_indicator_pass"]:
        msp_pass_rules = [
            rule
            for rule in normalized_rules
            if rule["rule_id"] == MSP_RULE_ID
            and rule["status"] == "pass"
            and rule["explicit_dealer_indicator"]
        ]
        for rule in msp_pass_rules:
            add_rule_reason(rule, "msp_restriction имеет явный МСП/СМП, dealer или partner признак.")
        return _make_result(
            "relevant_dealer",
            _confidence_for_success(stats, blocking_criteria),
            False,
            reasons,
            blocking_criteria,
            stats,
        )

    add_general_reason("Core subject criteria подтверждены, блокирующие риски не выявлены.")
    return _make_result(
        "relevant_direct",
        _confidence_for_success(stats, blocking_criteria),
        False,
        reasons,
        blocking_criteria,
        stats,
    )


def _normalize_rules(rules: Any) -> list[dict[str, Any]]:
    if not isinstance(rules, list):
        return []

    normalized_rules = []
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            continue

        rule_id = _rule_id(rule)
        output_rule_id = rule_id or f"unknown:{index}"
        normalized_rules.append(
            {
                "rule_id": rule_id,
                "output_rule_id": output_rule_id,
                "blocking_key": rule_id or output_rule_id,
                "criterion": _text(rule.get("criterion"), output_rule_id),
                "status": _normalize_choice(rule.get("status"), VALID_STATUSES, "unknown"),
                "risk": _normalize_choice(rule.get("risk"), VALID_RISKS, "medium"),
                "priority": _normalize_choice(rule.get("priority"), VALID_PRIORITIES, "medium"),
                "human_review_required": rule.get("human_review_required") is True,
                "comment": _text(rule.get("comment"), ""),
                "evidence_concerns": _list_text(rule.get("evidence_concerns")),
                "explicit_dealer_indicator": rule.get("explicit_dealer_indicator") is True,
            }
        )

    return normalized_rules


def _build_stats(rules: list[dict[str, Any]]) -> dict[str, Any]:
    core_rules = [rule for rule in rules if rule["rule_id"] in CORE_SUBJECT_RULE_IDS]

    return {
        "rules_total": len(rules),
        "core_passed": sum(1 for rule in core_rules if rule["status"] == "pass"),
        "core_total": len(core_rules),
        "core_fails": sum(1 for rule in core_rules if rule["status"] == "fail"),
        "core_unknown_or_not_pass": sum(1 for rule in core_rules if rule["status"] != "pass"),
        "high_conflicts": sum(
            1 for rule in rules if rule["priority"] == "high" and rule["status"] == "conflict"
        ),
        "high_unknowns": sum(
            1
            for rule in rules
            if rule["rule_id"] not in INDICATOR_ONLY_RULE_IDS
            and rule["priority"] == "high"
            and rule["status"] == "unknown"
        ),
        "significant_fails": sum(
            1
            for rule in rules
            if rule["rule_id"] not in CORE_SUBJECT_RULE_IDS
            and rule["rule_id"] not in INDICATOR_ONLY_RULE_IDS
            and rule["status"] == "fail"
            and rule["priority"] in {"high", "medium"}
        ),
        "human_review_rules": sum(
            1 for rule in rules if rule["human_review_required"] and not _is_neutral_rule(rule)
        ),
        "neutral_human_review_rules": sum(
            1 for rule in rules if rule["human_review_required"] and _is_neutral_rule(rule)
        ),
        "msp_indicator_pass": any(
            rule["rule_id"] == MSP_RULE_ID
            and rule["status"] == "pass"
            and rule["explicit_dealer_indicator"]
            for rule in rules
        ),
        "msp_unconfirmed_pass": any(
            rule["rule_id"] == MSP_RULE_ID
            and rule["status"] == "pass"
            and not rule["explicit_dealer_indicator"]
            for rule in rules
        ),
        "msp_high_risk": any(
            rule["rule_id"] == MSP_RULE_ID and rule["risk"] == "high" for rule in rules
        ),
        "msp_conflict": any(
            rule["rule_id"] == MSP_RULE_ID and rule["status"] == "conflict" for rule in rules
        ),
    }


def _is_neutral_rule(rule: dict[str, Any]) -> bool:
    if rule["risk"] == "high":
        return False

    if rule["rule_id"] == MSP_RULE_ID and rule["status"] in {"fail", "unknown"}:
        return True
    if (
        rule["rule_id"] == MSP_RULE_ID
        and rule["status"] == "pass"
        and not rule.get("explicit_dealer_indicator")
    ):
        return True

    return rule["priority"] == "low" and rule["status"] == "unknown"


def _make_result(
    scenario: str,
    confidence: str,
    human_review_required: bool,
    reasons: list[dict[str, Any]],
    blocking_criteria: list[dict[str, Any]],
    stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "recommendation": RECOMMENDATIONS[scenario],
        "confidence": confidence,
        "reasons": reasons,
        "blocking_criteria": blocking_criteria,
        "human_review_required": human_review_required,
        "stats": stats,
    }


def _make_reason(message: str, rule: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "rule_id": None if rule is None else rule["output_rule_id"],
        "message": message,
        "status": None if rule is None else rule["status"],
        "risk": None if rule is None else rule["risk"],
        "priority": None if rule is None else rule["priority"],
    }


def _confidence_for_success(stats: dict[str, Any], blocking_criteria: list[dict[str, Any]]) -> str:
    if (
        stats["core_total"] > 0
        and stats["core_passed"] == stats["core_total"]
        and not blocking_criteria
        and stats["significant_fails"] == 0
        and stats["high_conflicts"] == 0
        and stats["high_unknowns"] == 0
        and not stats["msp_high_risk"]
        and not stats["msp_conflict"]
        and not stats["msp_unconfirmed_pass"]
        and stats["human_review_rules"] == 0
    ):
        return "high"

    return "medium"


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    if not isinstance(value, str):
        return default

    normalized = value.strip().lower()
    if normalized in allowed:
        return normalized

    return default


def _rule_id(rule: dict[str, Any]) -> str:
    raw_rule_id = rule.get("id")
    if raw_rule_id in (None, ""):
        raw_rule_id = rule.get("criterion_id")

    if raw_rule_id in (None, ""):
        return ""

    return str(raw_rule_id).strip()


def _text(value: Any, default: str) -> str:
    if value in (None, ""):
        return default

    return str(value)


def _list_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify tender scenario from score JSON.")
    parser.add_argument("score_json_path", type=Path)
    args = parser.parse_args(argv)

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

        score_result = json.loads(args.score_json_path.read_text(encoding="utf-8"))
        result = classify_scenario(score_result)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
