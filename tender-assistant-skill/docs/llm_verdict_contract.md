# LLM verdict contract

## Назначение

`rule["llm_verdict"]` — это отдельный блок внутри результата конкретного правила.

Он показывает, вызывалась ли LLM и что она сказала по найденному `evidence`. LLM — локальная языковая модель, то есть нейросеть для анализа коротких текстовых фрагментов. `evidence` — найденный фрагмент документа, на основании которого правило делает вывод.

`llm_verdict` нужен для сравнения мнения LLM с `rule_engine`. `rule_engine` — обычный код, который проверяет правила без нейросети.

## Главное правило

LLM verdict не является источником итогового бизнес-решения.

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
- model — имя модели, например "qwen2.5:14b" в demo selective mode.
- error_type — optional тип ошибки LLM-вызова или JSON-валидации.
- error_message — optional краткое описание ошибки.
- raw_response_saved — optional признак, что raw response сохранён отдельно для debug.

## Поведение при конфликте

Если `rule_engine` дал `status=unknown`, а LLM дала `verdict=fail`:
- rule["status"] остаётся unknown;
- scenario_result не меняется;
- конфликт фиксируется в rule["llm_verdict"]["warnings"];
- conflicts_with_rule=true.

`conflicts_with_rule=true` означает, что мнение LLM расходится с обычным правилом. Это сигнал для анализа, но не автоматическое изменение решения.

## Поведение при ошибке LLM

Если LLM недоступна, сработал timeout или модель вернула невалидный JSON:
- pipeline не падает;
- deterministic result сохраняется;
- llm_verdict получает invocation_status="unavailable", "error" или "invalid_json";
- warnings содержит причину.

## invocation_status

`invocation_status` показывает, что произошло с вызовом LLM:

- `ok` — LLM ответила нормально;
- `skipped` — LLM не вызывалась;
- `unavailable` — LLM недоступна или сработал timeout;
- `error` — произошла ошибка вызова;
- `invalid_json` — LLM ответила невалидным JSON.

При любом статусе итоговые поля правила и `scenario_result` остаются под контролем deterministic pipeline.

## Конфигурация

`TENDER_LLM_ENABLED=true` в `.env.example` — это demo-значение для локального selective shadow режима.

Для production-окружения безопасный дефолт — не включать LLM без явного решения владельца пайплайна. Если переменная не задана или задана как `TENDER_LLM_ENABLED=false`, deterministic pipeline должен оставаться источником итогового решения и работать без обязательного LLM-вызова.

## Prompt source

Canonical prompt source для классификации критерия должен быть markdown-файл:

tender-assistant-skill/prompts/classify_criterion.md

Если такого файла пока нет — не создавать его в этой задаче, а зафиксировать как будущий canonical source.
Не создавать второй независимый источник prompt-текста в src/llm/prompts.py.
Если позже понадобится Python-модуль prompts.py, он должен быть только loader/renderer markdown prompt-файла, а не отдельным источником prompt-текста.
