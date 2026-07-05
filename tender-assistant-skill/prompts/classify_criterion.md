# Классификация одного критерия по evidence

Ты классифицируешь только один критерий тендера по переданным фрагментам evidence.
Не анализируй весь тендер и не делай выводы по данным, которых нет в evidence.
LLM verdict является только диагностической metadata и не является итоговым business decision.

## Входные данные

rule_id: {{rule_id}}

deterministic_status: {{deterministic_status}}

provider: {{provider}}

model: {{model}}

criterion:
{{criterion}}

evidence:
{{evidence_json}}

## Правила

- Используй только переданные evidence.
- Не добавляй supporting_evidence_ids вне значений `llm_evidence_id` из evidence.
- Если evidence недостаточно для уверенного вывода, верни `verdict="unknown"` и `confidence="low"`.
- Если `verdict="unknown"`, не указывай supporting evidence: верни `supporting_evidence_ids=[]`.
- Если `verdict="unknown"`, поставь `human_review_required=true`.
- `supporting_evidence_ids` можно заполнять только для `verdict="pass"`, `verdict="fail"` или `verdict="conflict"`, когда конкретные evidence действительно подтверждают вывод.
- Если deterministic_status и твой verdict расходятся, поставь `conflicts_with_rule=true` и добавь короткое предупреждение в `warnings`.
- Для `procurement_method` классифицируй только способ закупки, а не электронный документооборот.
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
- Для `procurement_method`, если в evidence нет явного указания на "аукцион" вместе с электронной формой, верни `verdict="unknown"`, `confidence="low"`, `human_review_required=true`, `supporting_evidence_ids=[]`.
- Не добавляй поля вне контракта.
- Верни только JSON без markdown, пояснений и code fence.

## Контракт ответа

```json
{
  "invocation_status": "ok",
  "rule_id": "{{rule_id}}",
  "verdict": "pass | fail | unknown | conflict",
  "confidence": "high | medium | low",
  "human_review_required": true,
  "reason": "краткое объяснение на основе evidence",
  "supporting_evidence_ids": [0],
  "warnings": [],
  "conflicts_with_rule": false,
  "deterministic_status": "{{deterministic_status}}",
  "provider": "{{provider}}",
  "model": "{{model}}"
}
```
