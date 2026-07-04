# DOCX template placeholders

## 1. Цель

Документ фиксирует контракт machine-readable placeholders для будущего DOCX-exporter. Контракт нужен, чтобы exporter заполнял `tender_summary.docx` детерминированно, без LLM, с явными fallback-значениями и связью выводов с evidence.

## 2. Шаблон

- Исходный шаблон: `sources_info/Шаблон сводки по тендеру.docx`.
- Новый шаблон: `sources_info/Шаблон сводки по тендеру v2.docx`.
- Исходный шаблон не изменялся.
- v2 создан как бинарная копия исходного шаблона и затем отредактирован.

## 3. Правила именования placeholders

- Формат: `{{namespace.name}}`.
- Допустимы только латиница, цифры, underscore и точка.
- Пробелы и кириллица внутри placeholder запрещены.
- Один placeholder соответствует одному полю.
- Fallback обязателен для каждого placeholder.
- Exporter не должен выдумывать значения: если источник данных отсутствует, используется fallback.

## 4. Конвенции рендера

### Rule placeholders

- `status` размещается в колонке `Значение` / `Оценка`.
- `comment` и `evidence` размещаются в колонке `Примечание` / `Комментарий`.
- `comment` и `evidence` должны рендериться отдельными абзацами внутри одной ячейки:

```text
Комментарий: {{rules.<rule_id>.comment}}
Основание: {{rules.<rule_id>.evidence}}
```

Метка `Основание:` используется намеренно вместо `Evidence:` для единообразия с русскоязычным текстом документа. Имя placeholder-поля `evidence` при этом не меняется.

Для `rules.<rule_id>.evidence` exporter должен брать элементы из `score_result.rules[rule_id].evidence` в стабильном порядке. Текст evidence извлекается по приоритету полей: `snippet` -> `text` -> `block.text`. В ячейках таблиц показывать не более 2 evidence items на rule, каждый item - отдельным абзацем внутри блока `Основание:`. Рекомендуемый лимит одного item - до 500 символов с обрезкой по границе слова и суффиксом `...`. Если после нормализации текст не найден, использовать fallback соответствующего placeholder.

### List placeholders

Списки рендерятся многострочным bullet-форматом, каждый элемент - отдельным абзацем:

```text
- item 1
- item 2
```

Для criteria/evidence допустим формат:

```text
- [rule_id] criterion - status / risk
  Комментарий: ...
  Основание: ...
```

Для `{{scenario.blocking_criteria}}` каждый элемент из `score_result.scenario_result.blocking_criteria` рендерится отдельным bullet-абзацем:

```text
- [rule_id] criterion - status / risk
  message
```

Поля брать в таком порядке:

- `rule_id`: `item.rule_id`, fallback `unknown`;
- `criterion`: `item.criterion`, fallback `Критерий не указан`;
- `status`: `item.status`, fallback `unknown`;
- `risk`: `item.risk`, fallback `unknown`;
- `message`: `item.message`, fallback пустая строка; если message пустой, второй абзац не добавлять.

Для `{{scenario.reasons}}` каждый элемент из `score_result.scenario_result.reasons` рендерится отдельным bullet-абзацем:

```text
- message (rule_id)
```

`message` брать из `item.message`, fallback `Причина не указана`. `rule_id` брать из `item.rule_id`; если `rule_id` отсутствует, скобки не добавлять.

### Human review fields

- `{{scenario.human_review_required}}` - итоговый булевый флаг сценария из `score_result.scenario_result.human_review_required`: `да`, `нет`, `не указано`.
- `{{stats.human_review_required}}` - количество rules, у которых `human_review_required=true`. Источник: `score_result.stats.human_review_required`, если поле есть; иначе будущий exporter должен вычислить count по `score_result.rules[]`.

## 5. Список placeholders

| Placeholder | Источник данных | Обязательность | Fallback | Комментарий |
|---|---|---|---|---|
| `{{input.path}}` | `score_result.input_path` | required | `Путь к входным данным не указан.` | Путь к анализируемому тендеру. |
| `{{stats.document_count}}` | `score_result.document_count` | required | `0` | Количество документов. |
| `{{stats.criteria_count}}` | `score_result.criteria_count` | required | `0` | Количество критериев. |
| `{{stats.rules_count}}` | `score_result.rules_count` | required | `0` | Количество rules. |
| `{{stats.pass}}` | `score_result.stats.pass` | required | `0` | Количество `pass`. |
| `{{stats.fail}}` | `score_result.stats.fail` | required | `0` | Количество `fail`. |
| `{{stats.unknown}}` | `score_result.stats.unknown` | required | `0` | Количество `unknown`. |
| `{{stats.conflict}}` | `score_result.stats.conflict` | required | `0` | Количество `conflict`. |
| `{{stats.risk_low}}` | `score_result.stats.risk_low` | required | `0` | Количество rules с низким риском. |
| `{{stats.risk_medium}}` | `score_result.stats.risk_medium` | required | `0` | Количество rules со средним риском. |
| `{{stats.risk_high}}` | `score_result.stats.risk_high` | required | `0` | Количество rules с высоким риском. |
| `{{stats.human_review_required}}` | `score_result.stats.human_review_required` или count по `score_result.rules[]` | required | `0` | Не дубль `scenario.human_review_required`: это числовая статистика. |
| `{{scenario.scenario}}` | `score_result.scenario_result.scenario` | required | `Итоговый сценарий не рассчитан.` | Один из сценариев classifier. |
| `{{scenario.recommendation}}` | `score_result.scenario_result.recommendation` | required | `Рекомендация не сформирована.` | Итоговая рекомендация. |
| `{{scenario.confidence}}` | `score_result.scenario_result.confidence` | required | `-` | Уверенность сценария. |
| `{{scenario.human_review_required}}` | `score_result.scenario_result.human_review_required` | required | `не указано` | Итоговый флаг сценария. |
| `{{scenario.blocking_criteria}}` | `score_result.scenario_result.blocking_criteria` | required | `Блокирующие критерии не выявлены.` | Список, рендерится отдельными абзацами. |
| `{{scenario.reasons}}` | `score_result.scenario_result.reasons` | required | `Причины не сформированы.` | Список причин сценария. |
| `{{rules.subject_okpd2_oil.status}}` | `score_result.rules[subject_okpd2_oil].status` | required | `unknown` | Статус правила. |
| `{{rules.subject_okpd2_oil.comment}}` | `score_result.rules[subject_okpd2_oil].comment` | required | `Комментарий по ОКПД2 не сформирован.` | Комментарий правила. |
| `{{rules.subject_okpd2_oil.evidence}}` | `score_result.rules[subject_okpd2_oil].evidence` | required | `Evidence по ОКПД2 не найдено.` | Evidence правила. |
| `{{rules.procurement_method.status}}` | `score_result.rules[procurement_method].status` | required | `unknown` | Статус правила. |
| `{{rules.procurement_method.comment}}` | `score_result.rules[procurement_method].comment` | required | `Комментарий по способу закупки не сформирован.` | Комментарий правила. |
| `{{rules.procurement_method.evidence}}` | `score_result.rules[procurement_method].evidence` | required | `Evidence по способу закупки не найдено.` | Evidence правила. |
| `{{rules.price_nmc.status}}` | `score_result.rules[price_nmc].status` | required | `unknown` | Статус правила. |
| `{{rules.price_nmc.comment}}` | `score_result.rules[price_nmc].comment` | required | `Комментарий по НМЦК не сформирован.` | Комментарий правила. |
| `{{rules.price_nmc.evidence}}` | `score_result.rules[price_nmc].evidence` | required | `Evidence по НМЦК не найдено.` | Evidence правила. |
| `{{rules.delivery_location.status}}` | `score_result.rules[delivery_location].status` | required | `unknown` | Статус правила. |
| `{{rules.delivery_location.comment}}` | `score_result.rules[delivery_location].comment` | required | `Комментарий по месту поставки не сформирован.` | Комментарий правила. |
| `{{rules.delivery_location.evidence}}` | `score_result.rules[delivery_location].evidence` | required | `Evidence по месту поставки не найдено.` | Evidence правила. |
| `{{rules.delivery_period.status}}` | `score_result.rules[delivery_period].status` | required | `unknown` | Статус правила. |
| `{{rules.delivery_period.comment}}` | `score_result.rules[delivery_period].comment` | required | `Комментарий по сроку поставки не сформирован.` | Комментарий правила. |
| `{{rules.delivery_period.evidence}}` | `score_result.rules[delivery_period].evidence` | required | `Evidence по сроку поставки не найдено.` | Evidence правила. |
| `{{rules.msp_restriction.status}}` | `score_result.rules[msp_restriction].status` | required | `unknown` | Статус правила. |
| `{{rules.msp_restriction.comment}}` | `score_result.rules[msp_restriction].comment` | required | `Комментарий по ограничению МСП не сформирован.` | Комментарий правила. |
| `{{rules.msp_restriction.evidence}}` | `score_result.rules[msp_restriction].evidence` | required | `Evidence по ограничению МСП не найдено.` | Evidence правила. |
| `{{rules.national_regime.status}}` | `score_result.rules[national_regime].status` | required | `unknown` | Статус правила. |
| `{{rules.national_regime.comment}}` | `score_result.rules[national_regime].comment` | required | `Комментарий по национальному режиму не сформирован.` | Комментарий правила. |
| `{{rules.national_regime.evidence}}` | `score_result.rules[national_regime].evidence` | required | `Evidence по национальному режиму не найдено.` | Evidence правила. |
| `{{rules.security_requirement.status}}` | `score_result.rules[security_requirement].status` | required | `unknown` | Статус правила. |
| `{{rules.security_requirement.comment}}` | `score_result.rules[security_requirement].comment` | required | `Комментарий по обеспечению не сформирован.` | Комментарий правила. |
| `{{rules.security_requirement.evidence}}` | `score_result.rules[security_requirement].evidence` | required | `Evidence по обеспечению не найдено.` | Evidence правила. |
| `{{rules.contract_terms.status}}` | `score_result.rules[contract_terms].status` | required | `unknown` | Статус правила. |
| `{{rules.contract_terms.comment}}` | `score_result.rules[contract_terms].comment` | required | `Комментарий по условиям контракта не сформирован.` | Комментарий правила. |
| `{{rules.contract_terms.evidence}}` | `score_result.rules[contract_terms].evidence` | required | `Evidence по условиям контракта не найдено.` | Evidence правила. |
| `{{summary.general_conclusion}}` | `tender_summary.md` | optional | `Общий вывод не сформирован.` | Раздел общего вывода. |
| `{{summary.attention_criteria}}` | `tender_summary.md` | optional | `Критерии, требующие внимания, не выявлены.` | Список, рендерится отдельными абзацами. |
| `{{summary.confirmed_criteria}}` | `tender_summary.md` | optional | `Подтвержденные критерии не выявлены.` | Список, рендерится отдельными абзацами. |
| `{{summary.low_priority_unknown_criteria}}` | `tender_summary.md` | optional | `Низкоприоритетные неподтвержденные критерии не выявлены.` | Список, рендерится отдельными абзацами. |
| `{{questions.count}}` | `questions_for_customer.md` | optional | `0` | Количество вопросов. |
| `{{questions.items}}` | `questions_for_customer.md` | optional | `Вопросы не выявлены.` | Список вопросов, рендерится отдельными абзацами. |
| `{{evidence.appendix}}` | `score_result.rules[].evidence` | optional | `Evidence не найдено.` | Агрегированный appendix evidence. |

## 6. Размещение placeholders в DOCX

| Раздел DOCX | Placeholder | Назначение |
|---|---|---|
| `ОБЩАЯ ИНФОРМАЦИЯ` | `{{rules.procurement_method.status}}`, `{{rules.procurement_method.comment}}`, `{{rules.procurement_method.evidence}}` | Способ определения поставщика. |
| `ОБЩАЯ ИНФОРМАЦИЯ` | `{{rules.price_nmc.status}}`, `{{rules.price_nmc.comment}}`, `{{rules.price_nmc.evidence}}` | НМЦК. |
| `ОБЩАЯ ИНФОРМАЦИЯ` | `{{rules.msp_restriction.status}}`, `{{rules.msp_restriction.comment}}`, `{{rules.msp_restriction.evidence}}` | Статус МСП. |
| `ОБЩАЯ ИНФОРМАЦИЯ` | `{{input.path}}`, `{{stats.document_count}}`, `{{stats.criteria_count}}`, `{{stats.rules_count}}`, `{{stats.pass}}`, `{{stats.fail}}`, `{{stats.unknown}}`, `{{stats.conflict}}`, `{{stats.risk_low}}`, `{{stats.risk_medium}}`, `{{stats.risk_high}}`, `{{stats.human_review_required}}` | Добавленные строки краткой статистики. |
| `ЛОТЫ` | `{{rules.subject_okpd2_oil.status}}`, `{{rules.subject_okpd2_oil.comment}}`, `{{rules.subject_okpd2_oil.evidence}}` | Код КТРУ / ОКПД2. |
| `УСЛОВИЯ ПОСТАВКИ` | `{{rules.delivery_location.status}}`, `{{rules.delivery_location.comment}}`, `{{rules.delivery_location.evidence}}` | Адреса поставки. |
| `УСЛОВИЯ ПОСТАВКИ` | `{{rules.delivery_period.status}}`, `{{rules.delivery_period.comment}}`, `{{rules.delivery_period.evidence}}` | Срок поставки. |
| `КОММЕРЧЕСКИЕ УСЛОВИЯ` | `{{rules.security_requirement.status}}`, `{{rules.security_requirement.comment}}`, `{{rules.security_requirement.evidence}}` | Обеспечение заявки. |
| `ТРЕБОВАНИЯ К УЧАСТНИКУ` | `{{rules.national_regime.status}}`, `{{rules.national_regime.comment}}`, `{{rules.national_regime.evidence}}` | Национальный режим. |
| `АНАЛИЗ РИСКОВ` | `{{rules.contract_terms.status}}`, `{{rules.contract_terms.comment}}`, `{{rules.contract_terms.evidence}}` | Соответствие типовому договору. |
| `ИТОГОВЫЙ СЦЕНАРИЙ` | `{{scenario.scenario}}`, `{{scenario.recommendation}}`, `{{scenario.confidence}}`, `{{scenario.human_review_required}}`, `{{scenario.blocking_criteria}}`, `{{scenario.reasons}}`, `{{summary.general_conclusion}}` | Итоговый сценарий, причины и общий вывод. |
| `КРИТЕРИИ, ТРЕБУЮЩИЕ ВНИМАНИЯ` | `{{summary.attention_criteria}}`, `{{summary.confirmed_criteria}}`, `{{summary.low_priority_unknown_criteria}}` | Агрегированные списки критериев. |
| `ВОПРОСЫ ДЛЯ ЗАКАЗЧИКА / ЧЕЛОВЕКА` | `{{questions.count}}`, `{{questions.items}}` | Вопросы человеку / заказчику. |
| `EVIDENCE / ОСНОВАНИЯ` | `{{evidence.appendix}}` | Агрегированный appendix evidence. |

## 7. Контракт будущего exporter

Будущий модуль:

`tender-assistant-skill/src/output/docx_summary_writer.py`

Ожидаемые функции:

```python
def render_docx_summary(
    score_result: dict,
    template_path: str | Path,
    output_path: str | Path,
) -> Path:
    ...


def write_docx_summary(
    score_result: dict,
    template_path: str | Path,
    output_path: str | Path,
) -> Path:
    ...
```

Требования:

- deterministic-only;
- без LLM;
- не менять исходный `template_path`;
- заполнять только placeholders;
- если placeholder не найден в шаблоне, report warning или failure в зависимости от обязательности;
- если данные отсутствуют, использовать fallback;
- списки и `comment` / `evidence` рендерить отдельными абзацами по конвенции из раздела 4;
- сохранять результат как `tender_summary.docx`.

## 8. Валидация шаблона v2

Будущий exporter должен:

- проверить наличие обязательных placeholders;
- проверить отсутствие неизвестных placeholders;
- проверить, что все placeholders из DOCX описаны в этом контракте;
- проверить, что required placeholders имеют fallback;
- проверить, что placeholders в raw `word/document.xml` не разбиты между XML-runs.

## 9. Риски

- Word может разбивать placeholder по нескольким XML-runs.
- Простая замена текста может не найти placeholder, если он разбит.
- `python-docx` удобнее для таблиц, если он уже доступен, но добавлять зависимость пока нельзя.
- `python-docx` при сохранении пересериализует весь `document.xml`, что может незаметно изменить структуру документа за пределами видимого текста.
- OOXML `zipfile` + XML возможен, но сложнее.
- Длинные evidence могут ломать читаемость таблиц.
- Aggregated placeholders требуют многострочного текста.
- Таблица 6 `АНАЛИЗ РИСКОВ` и таблица 7 `ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ` в MVP покрыты placeholders только частично; строки без machine-readable placeholders не подлежат автоматическому заполнению exporter'ом без отдельного решения.
- Если пользователь вручную изменит текст placeholder, exporter должен считать это ошибкой валидации.

## 10. Итоговая рекомендация

Шаблон v2 готов для реализации будущего `docx_summary_writer.py` как deterministic exporter. В шаблоне есть обязательные placeholders для сценария, статистики и ключевых rule-полей. Optional остаются поля, которые берутся из markdown-сводки, вопросов и агрегированного appendix evidence. Можно переходить к реализации `docx_summary_writer.py` отдельной задачей.
