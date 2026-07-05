from __future__ import annotations

from typing import Any

DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen3:4b"

INVOCATION_STATUS_OK = "ok"
INVOCATION_STATUS_SKIPPED = "skipped"
INVOCATION_STATUS_UNAVAILABLE = "unavailable"
INVOCATION_STATUS_INVALID_JSON = "invalid_json"
INVOCATION_STATUS_ERROR = "error"

ALLOWED_INVOCATION_STATUSES = {
    INVOCATION_STATUS_OK,
    INVOCATION_STATUS_SKIPPED,
    INVOCATION_STATUS_UNAVAILABLE,
    INVOCATION_STATUS_INVALID_JSON,
    INVOCATION_STATUS_ERROR,
}

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_UNKNOWN = "unknown"
VERDICT_CONFLICT = "conflict"

ALLOWED_VERDICTS = {
    VERDICT_PASS,
    VERDICT_FAIL,
    VERDICT_UNKNOWN,
    VERDICT_CONFLICT,
}

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

ALLOWED_CONFIDENCES = {
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
}

REQUIRED_LLM_VERDICT_FIELDS = {
    "invocation_status",
    "rule_id",
    "verdict",
    "confidence",
    "human_review_required",
    "reason",
    "supporting_evidence_ids",
    "warnings",
    "conflicts_with_rule",
    "deterministic_status",
    "provider",
    "model",
}


def normalize_status(status: Any) -> str:
    value = str(status).strip().lower() if status is not None else ""
    if value in ALLOWED_VERDICTS:
        return value
    return VERDICT_UNKNOWN


def normalize_confidence(confidence: Any) -> str:
    value = str(confidence).strip().lower() if confidence is not None else ""
    if value in ALLOWED_CONFIDENCES:
        return value
    return CONFIDENCE_LOW


def normalize_rule_id(rule_id: Any) -> str:
    value = str(rule_id).strip() if rule_id is not None else ""
    return value or "criterion_unknown"


def _clean_warnings(warnings: list[str] | None) -> list[str]:
    if warnings is None:
        return []
    return [str(warning) for warning in warnings if str(warning).strip()]


def _clean_evidence_ids(evidence_ids: list[int] | None) -> list[int]:
    if evidence_ids is None:
        return []
    return [item for item in evidence_ids if type(item) is int]


def build_llm_verdict(
    *,
    invocation_status: str,
    rule_id: str,
    verdict: str,
    confidence: str,
    human_review_required: bool,
    reason: str,
    supporting_evidence_ids: list[int] | None,
    warnings: list[str] | None,
    conflicts_with_rule: bool,
    deterministic_status: str,
    provider: str,
    model: str,
    error_type: str | None = None,
    error_message: str | None = None,
    raw_response_saved: bool | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "invocation_status": invocation_status,
        "rule_id": normalize_rule_id(rule_id),
        "verdict": normalize_status(verdict),
        "confidence": normalize_confidence(confidence),
        "human_review_required": bool(human_review_required),
        "reason": str(reason),
        "supporting_evidence_ids": _clean_evidence_ids(supporting_evidence_ids),
        "warnings": _clean_warnings(warnings),
        "conflicts_with_rule": bool(conflicts_with_rule),
        "deterministic_status": normalize_status(deterministic_status),
        "provider": str(provider or DEFAULT_PROVIDER),
        "model": str(model or DEFAULT_MODEL),
    }

    if error_type is not None:
        result["error_type"] = str(error_type)
    if error_message is not None:
        result["error_message"] = str(error_message)
    if raw_response_saved is not None:
        result["raw_response_saved"] = bool(raw_response_saved)

    return result


def build_skipped_verdict(
    *,
    rule_id: str,
    deterministic_status: str,
    provider: str,
    model: str,
    reason: str,
    warnings: list[str] | None = None,
    verdict: str = VERDICT_UNKNOWN,
    confidence: str = CONFIDENCE_LOW,
    human_review_required: bool = False,
) -> dict[str, Any]:
    return build_llm_verdict(
        invocation_status=INVOCATION_STATUS_SKIPPED,
        rule_id=rule_id,
        verdict=verdict,
        confidence=confidence,
        human_review_required=human_review_required,
        reason=reason,
        supporting_evidence_ids=[],
        warnings=warnings,
        conflicts_with_rule=False,
        deterministic_status=deterministic_status,
        provider=provider,
        model=model,
    )


def build_unavailable_verdict(
    *,
    rule_id: str,
    deterministic_status: str,
    provider: str,
    model: str,
    reason: str,
    warnings: list[str] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return build_llm_verdict(
        invocation_status=INVOCATION_STATUS_UNAVAILABLE,
        rule_id=rule_id,
        verdict=VERDICT_UNKNOWN,
        confidence=CONFIDENCE_LOW,
        human_review_required=True,
        reason=reason,
        supporting_evidence_ids=[],
        warnings=warnings,
        conflicts_with_rule=False,
        deterministic_status=deterministic_status,
        provider=provider,
        model=model,
        error_type=error_type,
        error_message=error_message,
    )


def build_invalid_json_verdict(
    *,
    rule_id: str,
    deterministic_status: str,
    provider: str,
    model: str,
    reason: str,
    warnings: list[str] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    raw_response_saved: bool | None = None,
) -> dict[str, Any]:
    return build_llm_verdict(
        invocation_status=INVOCATION_STATUS_INVALID_JSON,
        rule_id=rule_id,
        verdict=VERDICT_UNKNOWN,
        confidence=CONFIDENCE_LOW,
        human_review_required=True,
        reason=reason,
        supporting_evidence_ids=[],
        warnings=warnings,
        conflicts_with_rule=False,
        deterministic_status=deterministic_status,
        provider=provider,
        model=model,
        error_type=error_type,
        error_message=error_message,
        raw_response_saved=raw_response_saved,
    )


def build_error_verdict(
    *,
    rule_id: str,
    deterministic_status: str,
    provider: str,
    model: str,
    reason: str,
    warnings: list[str] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return build_llm_verdict(
        invocation_status=INVOCATION_STATUS_ERROR,
        rule_id=rule_id,
        verdict=VERDICT_UNKNOWN,
        confidence=CONFIDENCE_LOW,
        human_review_required=True,
        reason=reason,
        supporting_evidence_ids=[],
        warnings=warnings,
        conflicts_with_rule=False,
        deterministic_status=deterministic_status,
        provider=provider,
        model=model,
        error_type=error_type,
        error_message=error_message,
    )


def build_ok_verdict(
    *,
    rule_id: str,
    deterministic_status: str,
    provider: str,
    model: str,
    verdict: str,
    confidence: str,
    human_review_required: bool,
    reason: str,
    supporting_evidence_ids: list[int],
    warnings: list[str] | None = None,
    conflicts_with_rule: bool = False,
) -> dict[str, Any]:
    return build_llm_verdict(
        invocation_status=INVOCATION_STATUS_OK,
        rule_id=rule_id,
        verdict=verdict,
        confidence=confidence,
        human_review_required=human_review_required,
        reason=reason,
        supporting_evidence_ids=supporting_evidence_ids,
        warnings=warnings,
        conflicts_with_rule=conflicts_with_rule,
        deterministic_status=deterministic_status,
        provider=provider,
        model=model,
    )


def mark_conflict_with_rule(llm_verdict: dict[str, Any]) -> dict[str, Any]:
    deterministic_status = normalize_status(llm_verdict.get("deterministic_status"))
    verdict = normalize_status(llm_verdict.get("verdict"))
    result = dict(llm_verdict)
    if (
        verdict == VERDICT_UNKNOWN
        or deterministic_status == VERDICT_UNKNOWN
        or deterministic_status == verdict
    ):
        result["conflicts_with_rule"] = False
        return result

    result["conflicts_with_rule"] = True
    warnings = list(result.get("warnings") or [])
    warning = f"LLM verdict '{verdict}' conflicts with deterministic status '{deterministic_status}'."
    if warning not in warnings:
        warnings.append(warning)
    result["warnings"] = warnings
    return result
