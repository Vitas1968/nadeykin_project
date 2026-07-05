# LLM verdict contract

## Назначение

rule["llm_verdict"] — это вспомогательная диагностическая информация от LLM.
Она нужна для сравнения LLM-классификации с deterministic rule_engine.

## Главное правило

LLM verdict не является источником итогового business decision.

Авторитетными остаются:
- rule["status"]
- rule["risk"]
- rule["human_review_required"]
- scenario_result

## Где хранить

LLM-result хранится внутри конкретного rule:

rule["llm_verdict"]

Не хранить LLM verdict в top-level result на первом этапе.
Не смешивать LLM verdict с scenario_result.

## Структура rule["llm_verdict"]

- invocation_status — статус попытки LLM-вызова: "ok", "skipped", "unavailable", "invalid_json" или "error".
- rule_id — идентификатор rule, к которому относится LLM verdict.
- verdict — LLM-классификация: "pass", "fail", "unknown" или "conflict".
- confidence — уверенность LLM-классификации: "high", "medium" или "low".
- human_review_required — диагностический флаг LLM о необходимости ручной проверки.
- reason — краткое объяснение LLM verdict на основе evidence.
- supporting_evidence_ids — список идентификаторов evidence, на которые опирается LLM.
- warnings — диагностические предупреждения, включая конфликты и ошибки LLM.
- conflicts_with_rule — true, если deterministic status и LLM verdict расходятся.
- deterministic_status — исходный deterministic rule["status"] для сравнения.
- provider — LLM provider, например "ollama".
- model — имя модели, например "qwen3:4b".
- error_type — optional тип ошибки LLM-вызова или JSON-валидации.
- error_message — optional краткое описание ошибки.
- raw_response_saved — optional признак, что raw response сохранён отдельно для debug.

## Поведение при конфликте

Если rule_engine дал status=unknown, а LLM дала verdict=fail:
- rule["status"] остаётся unknown;
- scenario_result не меняется;
- конфликт фиксируется в rule["llm_verdict"]["warnings"];
- conflicts_with_rule=true.

## Поведение при ошибке LLM

Если LLM недоступна или вернула невалидный JSON:
- pipeline не падает;
- deterministic result сохраняется;
- llm_verdict получает invocation_status="unavailable" или "invalid_json";
- warnings содержит причину.

## Feature flag

LLM должна быть выключена по умолчанию:

TENDER_LLM_ENABLED=false

Пока флаг не включён, обычный запуск pipeline должен оставаться deterministic-only.

## Prompt source

Canonical prompt source для классификации критерия должен быть markdown-файл:

tender-assistant-skill/prompts/classify_criterion.md

Если такого файла пока нет — не создавать его в этой задаче, а зафиксировать как будущий canonical source.
Не создавать второй независимый источник prompt-текста в src/llm/prompts.py.
Если позже понадобится Python-модуль prompts.py, он должен быть только loader/renderer markdown prompt-файла, а не отдельным источником prompt-текста.
