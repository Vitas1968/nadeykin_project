Задача: сделать ИИ-скилл для тендерного ассистента и запустить локально/на малой модели.

A-20260702-05

Тебе нужно делать не «чат-бота, который читает тендер», а скилл-пайплайн для скоринговой оценки тендера.

Правильная архитектура:

Документы тендера
        ↓
Извлечение текста / таблиц
        ↓
Нормализация в JSON
        ↓
Поиск фактов по критериям
        ↓
Скоринг релевантности / риска
        ↓
Сводка на 1–2 А4
        ↓
Список вопросов человеку / заказчику
Что именно надо сделать
1. MVP-цель

На вход:

папка с тендером

На выход:

tender_summary.md
tender_score.json
questions_for_customer.md

На первом этапе не нужно сразу заполнять анкеты и коммерческие документы. Заказчик прямо сказал, что текущие критерии относятся к первому этапу — скоринговой оценке тендера.

2. Основная бизнес-логика

Тендер должен попадать в один из сценариев:

Сценарий	Что означает	Действие
not_relevant	нерелевантный тендер	исключить из воронки
relevant_llk	релевантен для ЛЛК	передать в CRM
relevant_dealer	релевантен для дилера ЛЛК	направить дилеру
need_human_review	данных мало / противоречия / спорный риск	человек должен проверить

Это главное. Не просто «заполнить шаблон», а классифицировать тендер и объяснить почему.

3. Как использовать критерии

Каждый критерий из Excel надо превратить в rule-объект:

{
  "id": 1,
  "block": "Предмет закупки",
  "criterion": "Код ОКПД2 относится к маслам/смазочным материалам",
  "priority": "high",
  "evidence": [],
  "status": "pass | fail | unknown | conflict",
  "risk": "low | medium | high",
  "human_review_required": false,
  "comment": ""
}

Правила:

pass — критерий подтверждён документами.
fail — найден явный негативный признак.
unknown — данных нет.
conflict — разные документы дают разные значения.
human_review_required = true — если риск ошибки высокий или есть противоречие.

Важно: отсутствие данных не всегда fail. Например, если не указано назначение масла, это скорее unknown, а не нерелевантность. Заказчик прямо сказал, что критерий назначения не должен автоматически выбрасывать тендер.

4. Как использовать приоритет

Приоритет нужен не для текста сводки, а для решения:

high priority fail      → может выбросить тендер
medium priority fail    → риск / human review
low priority unknown    → не влияет на итог
high priority conflict  → human review обязательно

Пример логики:

if criterion_1_subject_oil == "fail":
    scenario = "not_relevant"

elif has_msp_restriction:
    scenario = "relevant_dealer"

elif has_oil_subject and not has_msp_restriction and logistics_ok:
    scenario = "relevant_llk"

else:
    scenario = "need_human_review"
5. Что должна делать малая модель

Маленькую модель нельзя заставлять «думать за всё». Ей надо давать узкие задачи:

Извлечь факты из конкретного фрагмента.
Классифицировать фрагмент по одному критерию.
Сформулировать краткое объяснение.
Сформировать итоговую сводку из уже готового JSON.

Не надо просить модель:

проанализируй весь тендер и скажи, участвовать или нет

Надо просить так:

Вот критерий.
Вот найденные фрагменты документов.
Верни JSON:
status, evidence, risk, comment, human_review_required.
6. Структура проекта

Я бы сделал так:

tender-assistant-skill/
│
├── README.md
├── config/
│   ├── criteria.yaml
│   ├── document_priority.yaml
│   └── scoring_rules.yaml
│
├── prompts/
│   ├── extract_fact.md
│   ├── classify_criterion.md
│   └── render_summary.md
│
├── src/
│   ├── ingest/
│   │   ├── docx_reader.py
│   │   ├── xlsx_reader.py
│   │   ├── pdf_reader.py
│   │   └── html_reader.py
│   │
│   ├── normalize/
│   │   └── tender_document.py
│   │
│   ├── retrieval/
│   │   └── keyword_search.py
│   │
│   ├── scoring/
│   │   ├── rule_engine.py
│   │   ├── scenario_classifier.py
│   │   └── risk_resolver.py
│   │
│   ├── llm/
│   │   ├── local_llm_client.py
│   │   └── json_guard.py
│   │
│   └── output/
│       ├── summary_writer.py
│       └── questions_writer.py
│
├── examples/
│   ├── tender_1/
│   ├── tender_2/
│   └── tender_3/
│
└── run.py
7. Минимальный CLI

Команда должна быть простой:

python run.py \
  --input "./examples/tender_2" \
  --criteria "./config/criteria.yaml" \
  --out "./output/tender_2"

Результат:

output/tender_2/
├── tender_score.json
├── tender_summary.md
├── questions_for_customer.md
└── evidence.json
8. Что показать заказчику / команде

Тебе нужно показать не просто код, а результат на их трёх тендерах:

Тендер 1 → relevant_llk / relevant_dealer / need_human_review
Тендер 2 → relevant_llk / relevant_dealer / need_human_review
Тендер 3 → relevant_llk / relevant_dealer / need_human_review

И для каждого:

краткая сводка;
найденные факты;
риски;
противоречия;
вопросы человеку;
итоговая рекомендация.
9. Главный акцент для победы

Сделай упор на то, что твой скилл:

Не галлюцинирует, потому что каждое решение связано с evidence.
Работает на малой модели, потому что модель получает короткие фрагменты, а не весь тендер.
Разделяет факты и выводы.
Не выбрасывает тендер из-за отсутствия второстепенных данных.
Подсвечивает противоречия и вопросы заказчику.
Возвращает машинный JSON, который потом можно отправить в CRM.
10. Ближайший план работы

Я бы делал в таком порядке:

Перевести Критерии для тендера.xlsx в criteria.yaml.
Написать парсеры docx/xlsx/pdf/html.
Сделать индекс документов по абзацам и строкам таблиц.
Реализовать keyword retrieval по каждому критерию.
Сделать LLM-классификацию одного критерия по найденным фрагментам.
Сделать rule-based итоговый сценарий.
Сгенерировать сводку Markdown.
Прогнать на Тендер 1, Тендер 2, Тендер 3.
Сравнить результаты вручную.
Упаковать как skill.

Ключевое: сначала скоринг, потом заполнение документов. Заполнение анкет и коммерческих форм — это второй этап, его лучше не смешивать с MVP.


Рекомендуемый порядок дальше на 11:00 03.07.2026
Сделать run.py как тонкий CLI-оркестратор.
Он должен вызывать уже готовый evaluate_tender_path() и сохранять минимум tender_score.json.
Сделать questions_writer.py.
На первом этапе deterministic: брать unknown, conflict, fail, human_review_required=true и формировать вопросы человеку.
Сделать summary_writer.py.
На первом этапе deterministic Markdown: статистика, риски, top evidence, вопросы, предварительная рекомендация.
Потом делать scenario_classifier.py.
Он должен превращать набор rule-объектов в один сценарий: not_relevant, relevant_llk, relevant_dealer, need_human_review. Сценарии прямо зафиксированы в плане.
Только после этого возвращаться к LLM-слою.
В плане LLM должен работать с короткими фрагментами и узкими задачами, а не анализировать весь тендер целиком.
Ближайшая задача

Следующий prompt лучше дать на реализацию run.py, но в минимальном варианте:

input folder
→ evaluate_tender_path()
→ output/tender_score.json

Без summary, questions и scenario. Сначала нужно получить стабильный машинный JSON на реальном тендере. Потом уже на него навешивать questions_writer, summary_writer и scenario_classifier.