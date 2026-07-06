from __future__ import annotations

from typing import Any, Protocol

from . import json_guard, schema
from .local_llm_client import LLMClientConfig, LLMClientResponse, LocalLLMClient, load_config_from_env
from .prompt_loader import PromptLoadError, render_classify_criterion_prompt

_UNAVAILABLE_ERROR_TYPES = {"http_error", "url_error", "timeout", "ConnectionRefusedError"}
_PROCUREMENT_METHOD_RULE_ID = "procurement_method"
_PURCHASE_TYPE_GOODS_RULE_ID = "purchase_type_goods"
_MSP_RESTRICTION_RULE_ID = "msp_restriction"


class ChatClient(Protocol):
    config: LLMClientConfig

    def chat(self, prompt: str) -> LLMClientResponse:
        ...


def _first_text(rule: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = rule.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _rule_id(rule: dict[str, Any]) -> str:
    return schema.normalize_rule_id(_first_text(rule, ("id", "rule_id", "criterion_id")))


def _rule_instructions_for_rule_id(rule_id: str) -> str:
    if rule_id == _PROCUREMENT_METHOD_RULE_ID:
        return """- Для `procurement_method` классифицируй только способ закупки, а не электронный документооборот.
- Текст `criterion` не является evidence. Нельзя ставить `pass` только потому, что в criterion написано "электронный аукцион".
- `pass` допустим только если в evidence явно есть одна из формулировок (включая падежные вариации):
  - "электронный аукцион";
  - "аукцион в электронной форме";
  - "проведение электронного аукциона";
  - "электронный аукцион на право заключения договора";
  - близкая грамматическая форма любой из вышеперечисленных фраз, где одновременно присутствует корень "аукцион" и явное указание на электронную форму или электронный способ проведения.
- Если evidence содержит только электронный документооборот, верни `verdict="unknown"` и `confidence="low"`.
- Следующие фразы НЕ подтверждают электронный аукцион и НЕ должны давать `pass`:
  - "электронный документ";
  - "электронная подпись";
  - "КЭП";
  - "электронный документооборот";
  - "электронная почта";
  - "ПИК ЕАСУЗ";
  - "ЭДО";
  - "контракт в форме электронного документа";
  - "заявка в виде электронного документа".
- Если evidence содержит "запрос предложений", "конкурс" или "котировка" как способ закупки, верни `verdict="fail"`, если критерий требует именно электронный аукцион.
- Для `procurement_method`, если в evidence нет явного указания на "аукцион" вместе с электронной формой, верни `verdict="unknown"`, `confidence="low"`, `human_review_required=true`, `supporting_evidence_ids=[]`."""

    if rule_id == _PURCHASE_TYPE_GOODS_RULE_ID:
        return """- Для `purchase_type_goods` классифицируй только тип предмета закупки: товар, услуга или работа.
- `pass` допустим только если evidence явно подтверждает поставку товара (`поставка товара`).
- Верни `verdict="fail"`, если evidence явно показывает оказание услуг или выполнение работ как основной предмет закупки.
- Верни `verdict="unknown"` и `confidence="low"`, если evidence содержит только количество, единицы измерения (литры, кг, штуки и т.п.) или позицию без явного указания на передачу товара.
- Для смешанных случаев товар плюс услуга или работа верни `verdict="conflict"` либо `verdict="unknown"`, если нельзя уверенно определить основной предмет закупки."""

    if rule_id == _MSP_RESTRICTION_RULE_ID:
        return """- Для `msp_restriction` классифицируй только ограничение участия для МСП, СМП, СОНКО или СОНО.
- `pass` допустим, если evidence явно показывает, что закупка только для субъектов МСП/СМП/СОНКО/СОНО.
- Формулировки "только для субъектов", "участниками могут быть только", "среди субъектов", "ограничение участия установлено" могут подтверждать ограничение.
- "Преимущество" субъектам МСП не равно "только для МСП" и само по себе не подтверждает ограничение участия.
- Декларация о принадлежности к субъектам МСП или реестр субъектов МСП без restriction context не подтверждают ограничение участия.
- Формулировки "не установлено", "не предусмотрено", "отсутствует", "участниками могут быть любые лица", "не является закупкой у СМП" или "не является закупкой у МСП" указывают на отсутствие restriction.
- Если positive-маркеры ограничения и negative-маркеры отсутствия restriction конфликтуют, верни `verdict="conflict"`.
- Если evidence недостаточно для уверенной классификации, верни `verdict="unknown"`, `confidence="low"`, `human_review_required=true`, `supporting_evidence_ids=[]`."""

    return ""


def _criterion_text(rule: dict[str, Any]) -> str:
    return _first_text(rule, ("criterion", "description", "name"))


def _evidence_has_text(item: dict[str, Any]) -> bool:
    for key in ("snippet", "text"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return True

    block = item.get("block")
    if isinstance(block, dict):
        value = block.get("text")
        return value is not None and bool(str(value).strip())
    return False


def _evidence_payload(rule: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = rule.get("evidence")
    if not isinstance(evidence, list):
        return []

    payload: list[dict[str, Any]] = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict) or not _evidence_has_text(item):
            continue
        evidence_item = dict(item)
        evidence_item["llm_evidence_id"] = index
        payload.append(evidence_item)
    return payload


def _response_error_verdict(
    *,
    response: LLMClientResponse,
    rule_id: str,
    deterministic_status: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    error_type = response.error_type or "llm_error"
    error_message = response.error_message or "LLM call failed."
    warning = f"LLM call failed: {error_message}"

    if error_type in _UNAVAILABLE_ERROR_TYPES:
        return schema.build_unavailable_verdict(
            rule_id=rule_id,
            deterministic_status=deterministic_status,
            provider=provider,
            model=model,
            reason="LLM endpoint is unavailable.",
            warnings=[warning],
            error_type=error_type,
            error_message=error_message,
        )

    return schema.build_error_verdict(
        rule_id=rule_id,
        deterministic_status=deterministic_status,
        provider=provider,
        model=model,
        reason="LLM classification failed.",
        warnings=[warning],
        error_type=error_type,
        error_message=error_message,
    )


def classify_criterion(rule: dict[str, Any], client: ChatClient | None = None) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise ValueError("rule must be a dict")

    config = client.config if client is not None else load_config_from_env()
    rule_id = _rule_id(rule)
    deterministic_status = schema.normalize_status(rule.get("status"))

    if not config.enabled:
        return schema.build_skipped_verdict(
            rule_id=rule_id,
            deterministic_status=deterministic_status,
            provider=config.provider,
            model=config.model,
            reason="LLM classification skipped because TENDER_LLM_ENABLED is not true.",
        )

    evidence = _evidence_payload(rule)
    if not evidence:
        return schema.build_skipped_verdict(
            rule_id=rule_id,
            deterministic_status=deterministic_status,
            provider=config.provider,
            model=config.model,
            reason="LLM classification skipped because evidence is empty.",
            warnings=["No evidence was provided for LLM classification."],
            human_review_required=True,
        )

    try:
        prompt = render_classify_criterion_prompt(
            rule_id=rule_id,
            criterion=_criterion_text(rule),
            deterministic_status=deterministic_status,
            evidence=evidence,
            provider=config.provider,
            model=config.model,
            rule_instructions=_rule_instructions_for_rule_id(rule_id),
        )
    except PromptLoadError as exc:
        return schema.build_error_verdict(
            rule_id=rule_id,
            deterministic_status=deterministic_status,
            provider=config.provider,
            model=config.model,
            reason="LLM prompt file is unavailable.",
            warnings=[str(exc)],
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    active_client = client if client is not None else LocalLLMClient(config)
    response = active_client.chat(prompt)
    if not response.ok or response.text is None:
        return _response_error_verdict(
            response=response,
            rule_id=rule_id,
            deterministic_status=deterministic_status,
            provider=config.provider,
            model=config.model,
        )

    llm_verdict = json_guard.parse_llm_verdict(
        response.text,
        rule_id=rule_id,
        deterministic_status=deterministic_status,
        provider=config.provider,
        model=config.model,
    )

    if llm_verdict["invocation_status"] == schema.INVOCATION_STATUS_OK:
        return schema.mark_conflict_with_rule(llm_verdict)
    return llm_verdict
