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
{{rule_instructions}}
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
