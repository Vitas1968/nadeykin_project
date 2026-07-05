from __future__ import annotations

import json
import re
from typing import Any

from . import schema

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def _invalid_json(
    *,
    rule_id: str,
    deterministic_status: str,
    provider: str,
    model: str,
    reason: str,
    warning: str,
    error_type: str,
    error_message: str,
) -> dict[str, Any]:
    return schema.build_invalid_json_verdict(
        rule_id=rule_id,
        deterministic_status=deterministic_status,
        provider=provider,
        model=model,
        reason=reason,
        warnings=[warning],
        error_type=error_type,
        error_message=error_message,
        raw_response_saved=False,
    )


def _extract_json_text(raw_response: str) -> str:
    text = str(raw_response).strip()
    match = _FENCED_JSON_RE.search(text)
    if match:
        return match.group(1).strip()
    return text


def _require_fields(payload: dict[str, Any]) -> str | None:
    missing = sorted(schema.REQUIRED_LLM_VERDICT_FIELDS - set(payload))
    if missing:
        return "Missing required fields: " + ", ".join(missing)
    return None


def _validate_values(payload: dict[str, Any]) -> str | None:
    if payload["invocation_status"] not in schema.ALLOWED_INVOCATION_STATUSES:
        return "Invalid invocation_status value"
    if payload["verdict"] not in schema.ALLOWED_VERDICTS:
        return "Invalid verdict value"
    if payload["confidence"] not in schema.ALLOWED_CONFIDENCES:
        return "Invalid confidence value"
    if payload["deterministic_status"] not in schema.ALLOWED_VERDICTS:
        return "Invalid deterministic_status value"
    return None


def _is_list_of_int(value: Any) -> bool:
    return isinstance(value, list) and all(type(item) is int for item in value)


def _is_list_of_str(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _validate_types(payload: dict[str, Any]) -> str | None:
    string_fields = (
        "invocation_status",
        "rule_id",
        "verdict",
        "confidence",
        "reason",
        "deterministic_status",
        "provider",
        "model",
    )
    for field in string_fields:
        if not isinstance(payload[field], str):
            return f"Field '{field}' must be a string"

    if not isinstance(payload["human_review_required"], bool):
        return "Field 'human_review_required' must be a boolean"
    if not isinstance(payload["conflicts_with_rule"], bool):
        return "Field 'conflicts_with_rule' must be a boolean"
    if not _is_list_of_int(payload["supporting_evidence_ids"]):
        return "Field 'supporting_evidence_ids' must be list[int]"
    if not _is_list_of_str(payload["warnings"]):
        return "Field 'warnings' must be list[str]"
    return None


def _validate_contract(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "LLM response JSON must be an object"

    for validator in (_require_fields, _validate_types, _validate_values):
        error = validator(payload)
        if error:
            return error
    return None


def parse_llm_verdict(
    raw_response: str,
    *,
    rule_id: str,
    deterministic_status: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    json_text = _extract_json_text(raw_response)

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return _invalid_json(
            rule_id=rule_id,
            deterministic_status=deterministic_status,
            provider=provider,
            model=model,
            reason="LLM response is not valid JSON.",
            warning=f"Invalid JSON response: {exc.msg}",
            error_type="json_decode_error",
            error_message=str(exc),
        )
    
    if isinstance(payload, dict):
        payload.setdefault("provider", provider)
        payload.setdefault("model", model)

    contract_error = _validate_contract(payload)
    if contract_error:
        return _invalid_json(
            rule_id=rule_id,
            deterministic_status=deterministic_status,
            provider=provider,
            model=model,
            reason="LLM response violates the llm_verdict contract.",
            warning=f"Contract violation: {contract_error}",
            error_type="contract_validation_error",
            error_message=contract_error,
        )

    return schema.build_ok_verdict(
        rule_id=rule_id,
        deterministic_status=deterministic_status,
        provider=provider,
        model=model,
        verdict=payload["verdict"],
        confidence=payload["confidence"],
        human_review_required=payload["human_review_required"],
        reason=payload["reason"],
        supporting_evidence_ids=payload["supporting_evidence_ids"],
        warnings=payload["warnings"],
        conflicts_with_rule=payload["conflicts_with_rule"],
    )
