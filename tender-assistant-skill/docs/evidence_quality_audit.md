# Evidence Quality Audit

## 1. Цель

Этот документ фиксирует audit качества `evidence` текущего deterministic MVP tender pipeline. Audit проверяет, насколько найденные snippets в `tender_score.json` действительно подтверждают выводы `rule_engine` и итоговый `scenario_result`.

Audit не меняет логику pipeline, не является юридическим заключением и не заменяет ручную проверку тендерных документов.

## 2. Методика

Перед анализом были прочитаны:

- `README.md`
- `tender-assistant-skill/config/criteria.yaml`
- `tender-assistant-skill/src/retrieval/keyword_search.py`
- `tender-assistant-skill/src/scoring/rule_engine.py`
- `tender-assistant-skill/src/scoring/scenario_classifier.py`
- `tender-assistant-skill/src/output/questions_writer.py`
- `tender-assistant-skill/src/output/summary_writer.py`
- `tender-assistant-skill/scripts/regression_check.py`

Pipeline запускался командами:

```bash
python tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/evidence_quality_audit/tender_1" --top-k 5 --min-score 0
python tender-assistant-skill/run.py --input "sources_info/Тендер 2" --out "outputs/debug/evidence_quality_audit/tender_2" --top-k 5 --min-score 0
python tender-assistant-skill/run.py --input "sources_info/Тендер 3" --out "outputs/debug/evidence_quality_audit/tender_3" --top-k 5 --min-score 0
```

Параметры `--top-k 5 --min-score 0` использованы намеренно как audit-конфигурация: они расширяют поверхность найденного evidence и показывают слабые, шумные и пограничные совпадения. Это не рекомендация для production-настроек.

Для каждого успешно обработанного тендера анализировались:

- `tender_score.json`
- `tender_summary.md`
- `questions_for_customer.md`

`tender_summary.docx` содержательно не анализировался, потому что audit касается качества evidence в JSON/MD.

Quality labels:

- `good`: snippet прямо подтверждает критерий, относится к нужному условию, вывод `rule_engine` выглядит обоснованным.
- `weak`: snippet частично связан с критерием, но подтверждение неполное или требует ручной проверки.
- `noisy`: snippet найден по ключевым словам, но относится не к сути критерия или может вести к ложному `pass`.
- `missing`: evidence отсутствует, и вывод основан на отсутствии подтверждающих фрагментов.
- `conflict`: найденные фрагменты дают разные признаки или противоречат выводу `rule_engine`.

Первичный audit был основан на тогдашних `criteria.yaml`, `keyword_search.py` и `rule_engine.py`. Важное наблюдение по коду: `rule_engine` считает подтверждающим любое evidence со `score > 0`. До refinement в `criteria.yaml` не было явных `negative_keywords` / `negative_terms`, поэтому часть `pass` фактически означала "найдено keyword evidence", а не "критерий надежно подтвержден".

Checkpoint после `Тендер 1`: labels применяются согласованно. `missing` использован только при отсутствии evidence, `conflict` только при противоречивых признаках, `good` не ставился для косвенных procedural snippets. Audit продолжен по `Тендер 2` и `Тендер 3`.

## 2.1 Актуализация после production-fix

Первичный audit выявил два production-impact дефекта:

- `security_requirement` мог получать clean `pass` при evidence вида "обеспечение ... не требуется" и не попадал в вопросы человеку.
- `msp_restriction` мог вести к `relevant_dealer` по noisy evidence без явного признака МСП/СМП, дилера или партнера.

После audit был выполнен production-fix бизнес-логики. Текущий pipeline больше не должен рассматривать эти findings как актуальное поведение:

- high-priority `pass` с подозрительным или отрицательным evidence получает `evidence_concerns`, повышенный risk и `human_review_required`;
- `questions_for_customer.md` включает вопросы по high-priority `pass` с `evidence_concerns`;
- `relevant_dealer` допускается только при явном подтверждении МСП/СМП/dealer/partner признака;
- `msp_unconfirmed_pass` снижает confidence успешного сценария.

Старые observations в разделах rule-level audit сохранены как причина фикса и как regression context. Актуальные scenario summaries ниже указывают post-fix поведение pipeline.

## 2.2 Актуализация после criteria.yaml refinement

После production-fix был выполнен config-only refinement `criteria.yaml`. Код pipeline, `regression_check.py` и regression snapshots при этом не менялись.

В `criteria.yaml` актуально отражены следующие изменения:

- `security_requirement` получил explicit `negative_terms` для фраз вида "обеспечение ... не требуется", "не установлено", "не предусмотрено";
- `msp_restriction` сужен до explicit МСП/СМП terms;
- `procurement_method` стал строже вокруг электронного аукциона;
- `quantity_measure` уточнен в сторону количества закупки, а не упаковочного объема;
- `oil_classification` расширен на промышленные масла и марки: `ТП-22С`, `ТП-22`, `ХФ 12-16`, `VDL`, "турбинное масло", "компрессорное масло", "гидравлическое масло";
- standalone `ГОСТ` / `ТУ` / `ISO` / `DIN` не добавлены как keywords, чтобы не увеличивать шум.

Свежая проверка после refinement запускалась с теми же audit-параметрами `--top-k 5 --min-score 0`, что и исторический audit. Поэтому comparison ниже считается сопоставимым по параметрам запуска; изменения в counts и rule behavior относятся к текущему `criteria.yaml` и уже существующей post-fix логике.

## 3. Общая сводка

| Tender | Pre-fix scenario | Post-fix scenario | Post-criteria scenario | Post-criteria confidence | Rules total | Good | Weak | Noisy | Missing | Conflict | Main issue |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| Тендер 1 | `relevant_dealer` | `need_human_review` | `need_human_review` | `medium` | 18 | 14 | 2 | 2 | 0 | 0 | `security_requirement` остается `pass` с `security_requirement_negative_evidence`, `risk=medium`, `human_review_required=true`; criteria refinement не меняет scenario. |
| Тендер 2 | `relevant_dealer` | `relevant_direct` | `relevant_direct` | `medium` | 18 | 9 | 5 | 4 | 0 | 0 | `msp_restriction` still pass with concern and question, но без explicit МСП/СМП/dealer/partner evidence не ведет к `relevant_dealer`. |
| Тендер 3 | `need_human_review` | `need_human_review` | `need_human_review` | `medium` | 18 | 13 | 2 | 1 | 1 | 1 | `oil_classification` улучшился с `unknown` до `pass` за счет industrial oil terms; scenario все равно `need_human_review` из-за negative `security_requirement`. |

## 4. Cross-tender findings

- Чаще всего weak/noisy evidence встречается у `oil_purpose`, `quantity_measure`, `procurement_method`, `security_requirement`, `msp_restriction`.
- Лучший evidence обычно дают технические задания, спецификации и project contract sections, где есть таблицы с предметом, сроками, местом поставки, упаковкой, качеством и ценой.
- Хуже всего работают общие procedural documents: они дают много совпадений по словам "закупка", "договор", "обеспечение", "поставщик", но не всегда подтверждают конкретный критерий.
- `keyword_search.py` ранжирует совпадения по сумме term matches без proximity к смысловому объекту. Поэтому фразы "обеспечение не требуется", "только зарегистрированный участник", "приложение 2" могут попадать в evidence surface.
- Исторически `criteria.yaml` смешивал must-have признаки и broad query terms. После refinement часть критериев стала строже, но `procurement_method` все еще может получать snippets про generic electronic document / electronic form вместо прямого "электронный аукцион".
- Pre-fix `rule_engine.py` не различал подтверждающее, отрицательное и нейтральное evidence для целевых high-priority pass. Это было особенно заметно по `security_requirement`.
- Pre-fix `questions_writer.py` формировал вопросы только по `human_review_required` / `unknown` / `fail` / `conflict`. Production-fix добавил вопросы для high-priority `pass` с `evidence_concerns`.

## 5. Tender 1 audit

### 5.1 Scenario

- pre-fix scenario: `relevant_dealer`
- post-fix scenario: `need_human_review`
- post-fix recommendation: передать на ручную проверку.
- post-fix confidence: `medium`
- post-fix human_review_required: `true`
- post-fix blocking_criteria: `security_requirement`
- post-fix reasons: `security_requirement` требует ручной проверки из-за evidence с отрицанием требования обеспечения.
- post-criteria scenario: `need_human_review`
- post-criteria recommendation: передать на ручную проверку.
- post-criteria confidence: `medium`
- post-criteria human_review_required: `true`
- post-criteria blocking_criteria: `security_requirement`
- post-criteria reasons: `security_requirement` остается high-priority `pass` с `security_requirement_negative_evidence`, `risk=medium` и вопросом человеку.

Post-criteria pipeline stats:

- documents: 7
- rules: 18
- pass: 18
- unknown/fail/conflict: 0
- human_review_required: 1

Pre-fix finding retained for context: audit выявил, что `security_requirement` ошибочно выглядел clean `pass` на snippets "обеспечение ... не требуется". Production-fix изменил это поведение: rule остается `pass` по keyword evidence, но получает concern, `risk=medium`, `human_review_required=true` и вопрос человеку. Criteria refinement добавил explicit `negative_terms`; в свежем запуске это подтверждает уже существующее post-fix поведение, а не меняет scenario.

### 5.2 Rule-level evidence quality

| rule_id | status | risk | human_review_required | evidence_count | quality | comment |
|---|---|---|---|---:|---|---|
| `subject_okpd2_oil` | pass | low | false | 5 | good | Top snippets прямо содержат `ОКПД2 19.20.29` и поставку эксплуатационного масла. |
| `subject_title_oil` | pass | low | false | 5 | good | Snippets содержат "масло моторное", `SAE 15W-40`, объем и НМЦ. |
| `purchase_type_goods` | pass | low | false | 5 | good | Есть прямой договорный фрагмент "поставщик поставляет, покупатель принимает и оплачивает". |
| `oil_purpose` | pass | low | false | 1 | noisy | Evidence про "материалы / оборудование" в гарантийных требованиях, а не про назначение масла. |
| `oil_classification` | pass | low | false | 5 | good | Есть API CI4/CI4+, SAE 15W40 и класс вязкости. |
| `quantity_measure` | pass | low | false | 5 | weak | Evidence показывает заголовок количества и отдельные косвенные фрагменты; потребность подтверждена неполно. |
| `delivery_period` | pass | low | false | 5 | weak | Есть "срок поставки продукции", но часть top snippets относится к срокам протоколов/оплаты. |
| `delivery_location` | pass | low | false | 5 | good | Есть склад в Петропавловске-Камчатском и график поставки. |
| `packaging_format` | pass | low | false | 5 | good | Есть прямое требование по металлическим бочкам 200-220 л и поддонам. |
| `quality_freshness` | pass | low | false | 4 | good | Есть "дата изготовления ... не ранее 2025 года". |
| `quality_documents` | pass | low | false | 5 | good | Есть паспорт качества и протоколы испытаний. |
| `msp_restriction` | pass | low | false | 5 | good | Evidence прямо говорит, что участниками могут быть только субъекты МСП. |
| `procurement_method` | pass | low | false | 5 | good | Evidence подтверждает аукцион в электронной форме. |
| `price_nmc` | pass | low | false | 5 | good | Есть НМЦ `20 166 500.00 руб. без учета НДС`. |
| `security_requirement` | pass | medium | true | 5 | noisy | Post-fix: evidence содержит "обеспечение заявки ... не требуется" и "обеспечение исполнения договора ... не требуется"; rule требует ручной проверки. |
| `national_regime` | pass | low | false | 5 | good | Есть режим преимущества российской продукции. |
| `contract_terms` | pass | low | false | 5 | good | Есть проект договора и протокол разногласий. |
| `after_sales_service` | pass | low | false | 5 | good | Есть обязанности поставщика по пробам/протоколам и качеству после поставки. |

### 5.3 Problematic rules

#### rule_id: `oil_purpose`

- criterion: Назначение масла связано с оборудованием/техникой.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 1.
- quality: `noisy`
- evidence snippets:
  - `Документация.docx`, section `Термины и определения`: "соответствие требованиям к гарантии на поставляемые материалы / оборудование..."
- audit note: snippet относится к общим гарантийным требованиям и не подтверждает, что масло предназначено для конкретного оборудования.
- recommendation: уточнить keywords: искать рядом "масло" + тип оборудования/узла, а generic "оборудование" снижать в score.

#### rule_id: `quantity_measure`

- criterion: Есть измеримая потребность.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `weak`
- evidence snippets:
  - `Приложение №1 Технические требования.docx`: "п/п | наименование продукции | единица измерения | количество"
  - `Приложение №1 Технические требования.docx`: "вид упаковки | ... бочках объемом 200-220 литров..."
- audit note: evidence связан с количеством, но top snippet не показывает конкретную потребность. Требуется вытаскивать строку таблицы с названием товара, единицей и значением.
- recommendation: улучшить table evidence grouping.

#### rule_id: `delivery_period`

- criterion: Есть фиксированный период поставки.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `weak`
- evidence snippets:
  - `Приложение № 4 к ДоЗ - Формы документов .docx`: "срок поставки продукции"
  - `Документация.docx`: "не позднее 3 трех календарных дней с даты подписания такого протокола..."
- audit note: часть evidence относится к срокам процедурных протоколов, а не к сроку поставки товара.
- recommendation: добавить negative/proximity признаки для слов "протокол", "аукцион", "размещение", если рядом нет "товар/продукция/поставка".

#### rule_id: `security_requirement`

- criterion: Обязательство по обеспечению участия в тендере или обеспечения по договору.
- status/risk: `pass` / `medium`
- pipeline comment: Найдено evidence с отрицанием требования обеспечения; требуется ручная проверка.
- quality: `noisy`
- evidence snippets:
  - `Документация.docx`: "обеспечение заявки на участие в закупке | не требуется"
  - `Документация.docx`: "обеспечение исполнения договора | не требуется."
- historical pre-fix issue: evidence прямо указывал отсутствие требования, но rule выглядел clean `pass`.
- post-fix behavior: rule получает `evidence_concerns`, `risk=medium`, `human_review_required=true` и вопрос человеку.
- post-criteria behavior: explicit `negative_terms` в `criteria.yaml` сохраняют тот же актуальный outcome: `security_requirement_negative_evidence` найден, scenario остается `need_human_review`.

## 6. Tender 2 audit

### 6.1 Scenario

- pre-fix scenario: `relevant_dealer`
- post-fix scenario: `relevant_direct`
- post-fix recommendation: передать тендер в прямую обработку профильному подразделению.
- post-fix confidence: `medium`
- post-fix human_review_required: `false`
- blocking_criteria: нет
- post-fix reasons: `msp_restriction` имеет status `pass`, но явный МСП/СМП/dealer/partner признак в evidence не найден; core subject criteria подтверждены.
- post-criteria scenario: `relevant_direct`
- post-criteria recommendation: передать тендер в прямую обработку профильному подразделению.
- post-criteria confidence: `medium`
- post-criteria human_review_required: `false`
- post-criteria blocking_criteria: нет
- post-criteria reasons: `msp_restriction` остается `pass` с `msp_indicator_not_explicit`, но этот concern не блокирует direct scenario; core subject criteria подтверждены.

Post-criteria pipeline stats:

- documents: 8
- rules: 18
- pass: 18
- unknown/fail/conflict: 0
- human_review_required: 1

Pre-fix finding retained for context: audit выявил, что noisy `msp_restriction` был единственным основанием `relevant_dealer`. Production-fix изменил это поведение: без явного МСП/СМП/dealer/partner evidence сценарий не становится `relevant_dealer`, а confidence снижается до `medium`.

### 6.2 Rule-level evidence quality

| rule_id | status | risk | human_review_required | evidence_count | quality | comment |
|---|---|---|---|---:|---|---|
| `subject_okpd2_oil` | pass | low | false | 5 | good | Есть `ОКПД2 19.20.29.111` и `масло моторное`. |
| `subject_title_oil` | pass | low | false | 5 | good | Есть строки с "масло моторное SAE 5W40/10W40/15W40". |
| `purchase_type_goods` | pass | low | false | 5 | good | Есть "поставка товара осуществляется по заявкам заказчика". |
| `oil_purpose` | pass | low | false | 1 | noisy | Evidence про соисполнителей со специальным оборудованием, не про назначение масла. |
| `oil_classification` | pass | low | false | 5 | good | Есть API CI-4, SL CI-4 и SAE classes. |
| `quantity_measure` | pass | low | false | 5 | weak | Есть header "количество | ед. измерения", но top snippets частично уходят в маркировку/упаковку. |
| `delivery_period` | pass | low | false | 5 | good | Есть "общий срок поставки товара 20 рабочих дней". |
| `delivery_location` | pass | low | false | 5 | weak | Есть "место поставки" в заявке и доставка силами поставщика, но адрес/склад не виден в top evidence. |
| `packaging_format` | pass | low | false | 5 | noisy | Top snippets generic: обязательства, документы, обеспечение; формат упаковки не подтвержден. |
| `quality_freshness` | pass | low | false | 4 | good | Есть "товар должен быть изготовлен не ранее 2025 года". |
| `quality_documents` | pass | low | false | 5 | good | Есть паспорта качества, сертификаты и декларации. |
| `msp_restriction` | pass | medium | true | 5 | noisy | Post-criteria: evidence все еще не содержит explicit МСП/СМП/dealer/partner признака; rule получает concern и вопрос человеку, но не ведет к `relevant_dealer`. |
| `procurement_method` | pass | low | false | 5 | noisy | Несмотря на stricter criteria, top snippets остаются про электронный документооборот, а не про электронный аукцион. |
| `price_nmc` | pass | low | false | 5 | weak | Evidence показывает price table fields и "итого не указано"; НМЦ подтверждена неполно. |
| `security_requirement` | pass | low | false | 5 | good | Есть "обеспечение исполнения контракта" и независимая гарантия. |
| `national_regime` | pass | low | false | 5 | weak | Evidence в основном шаблонное: "если ... установлены запрет/ограничение/преимущество". |
| `contract_terms` | pass | low | false | 5 | weak | Evidence в основном "приложение 2"; проект контракта вероятен, но условие подтверждено слабо. |
| `after_sales_service` | pass | low | false | 5 | good | Есть обязанности по устранению недостатков и поставке остатка. |

### 6.3 Problematic rules

#### rule_id: `msp_restriction`

- criterion: Закупка только для субъектов МСП.
- status/risk: `pass` / `medium`
- pipeline comment: Найденные фрагменты не содержат явного признака МСП/СМП, дилера или партнера; требуется проверка.
- quality: `noisy`
- evidence snippets:
  - `Приложение ПИК...docx`: "личный кабинет ... доступная только зарегистрированным ... пользователям"
  - `Требование к содержанию...docx`: "участник закупки вправе подать только одну заявку..."
  - `Требование к содержанию...docx`: "подать заявку ... вправе только зарегистрированный ... участник закупки..."
- historical pre-fix issue: noisy `msp_restriction pass` был достаточен для `relevant_dealer`.
- post-fix behavior: `scenario_classifier` больше не допускает dealer routing без explicit МСП/СМП/dealer/partner evidence.
- post-criteria behavior: критерий сужен до explicit terms, но top evidence в fresh run все еще содержит procedural snippets; outcome остается `pass` with concern, `risk=medium`, question generated.

#### rule_id: `packaging_format`

- criterion: Определен формат упаковки.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `noisy`
- evidence snippets:
  - `Приложение ПИК...docx`: "наименование | условия предоставления результатов..."
  - `Проект контракта...docx`: "представления надлежащим образом оформленных документов..."
- audit note: evidence не содержит явных "канистра", "бочка", объем, масса или упаковочный формат.
- recommendation: сделать для упаковки must-terms: `канистра`, `бочка`, `литр`, `кг`, `тара`, `упаковка`.

#### rule_id: `procurement_method`

- criterion: Способ закупки - электронный аукцион.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `noisy`
- evidence snippets:
  - `Приложение ПИК...docx`: "способ обеспечения исполнения контракта..."
  - `Приложение ПИК...docx`: "электронный документ..."
- historical issue: keyword matching по "способ" и "электронный" не подтверждало "электронный аукцион".
- post-criteria behavior: stricter criteria не устранил шум в этом тендере; top snippets все еще про `электронный документ` / ЭДО, а не про способ закупки.
- recommendation: сохраняется backlog для proximity/phrase matching и source priority; не считать generic electronic document evidence подтверждением электронного аукциона.

#### rule_id: `national_regime`

- criterion: Применяется преимущество российской продукции.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `weak`
- evidence snippets:
  - `Требование к содержанию...docx`: "в случае если ... установлены ... запрет ограничение преимущество..."
- audit note: snippet говорит об условном случае, но не подтверждает, что режим реально установлен в этой закупке.
- recommendation: различать "если установлено" и "установлено".

## 7. Tender 3 audit

### 7.1 Scenario

- pre-fix scenario: `need_human_review`
- post-fix scenario: `need_human_review`
- post-fix recommendation: передать на ручную проверку из-за недостаточности данных и security evidence concern.
- post-fix confidence: `medium`
- post-fix human_review_required: `true`
- post-fix blocking_criteria: `oil_classification`
- post-fix reasons: high-priority criterion `oil_classification` не подтвержден; `security_requirement` также формирует вопрос человеку из-за evidence "не требуется".
- post-criteria scenario: `need_human_review`
- post-criteria recommendation: передать на ручную проверку из-за negative `security_requirement` evidence.
- post-criteria confidence: `medium`
- post-criteria human_review_required: `true`
- post-criteria blocking_criteria: `security_requirement`
- post-criteria reasons: `oil_classification` теперь подтвержден industrial oil evidence, но `security_requirement` получает `security_requirement_negative_evidence`, `risk=medium`, `human_review_required=true`.

Post-criteria pipeline stats:

- documents: 11
- rules: 18
- pass: 17
- unknown: 1
- fail/conflict: 0
- human_review_required: 1

### 7.2 Rule-level evidence quality

| rule_id | status | risk | human_review_required | evidence_count | quality | comment |
|---|---|---|---|---:|---|---|
| `subject_okpd2_oil` | pass | low | false | 5 | weak | Evidence подтверждает масла, но не показывает ОКПД2. |
| `subject_title_oil` | pass | low | false | 5 | good | Есть "турбинное масло", "масло ХФ 12-16", compressor oil. |
| `purchase_type_goods` | pass | low | false | 5 | good | Есть договорные положения о товаре, поставке, приемке и разгрузке. |
| `oil_purpose` | unknown | low | false | 0 | missing | Evidence отсутствует. |
| `oil_classification` | pass | low | false | 5 | good | Post-criteria evidence прямо содержит `ТП-22С`, "турбинное масло", вязкость и другие признаки industrial oil classification. |
| `quantity_measure` | pass | low | false | 5 | weak | Evidence теперь ближе к строкам номенклатуры с `ед. изм.` / `кол-во`, но конкретные значения потребности видны неполно. |
| `delivery_period` | pass | low | false | 5 | good | Есть "август 2026 г." и срок поставки товара. |
| `delivery_location` | pass | low | false | 5 | good | Есть склад заказчика: г. Советск, ул. Энергетиков, д. 1г. |
| `packaging_format` | pass | low | false | 5 | good | Есть металлические бочки 200-250 л и полимерные канистры/бутыли 1/3/5/10 л. |
| `quality_freshness` | pass | low | false | 5 | good | Есть "срок изготовления товара - не ранее второй половины 2025г.". |
| `quality_documents` | pass | low | false | 5 | good | Есть паспорт качества, сертификат качества, декларация соответствия. |
| `msp_restriction` | pass | low | false | 5 | good | Evidence прямо говорит, что участниками могут быть только субъекты МСП. |
| `procurement_method` | pass | low | false | 5 | noisy | Evidence говорит о закупочной процедуре, но не подтверждает "электронный аукцион"; manual source check показывает "запрос предложений". |
| `price_nmc` | pass | low | false | 5 | good | Есть НМЦ `12 417 117.71 руб.` с НДС и `10 177 965.33 руб.`. |
| `security_requirement` | pass | medium | true | 5 | conflict | Post-criteria: условные snippets и прямые "не требуется" формируют `security_requirement_negative_evidence`, concern и вопрос человеку. |
| `national_regime` | pass | low | false | 5 | good | Есть national regime section и форма страны происхождения товара. |
| `contract_terms` | pass | low | false | 5 | good | Есть проект договора и протокол разногласий. |
| `after_sales_service` | pass | low | false | 5 | good | Есть обязанности по замене некачественного товара, уведомлению об отгрузке, документам и вывозу непринятого товара. |

### 7.3 Problematic rules

#### rule_id: `subject_okpd2_oil`

- criterion: Код ОКПД2 относится к маслам/смазочным материалам.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `weak`
- evidence snippets:
  - `Приложение №1 к ДоЗ - Техническое задание.xlsx`: "турбинное масло | марка - тп-22с..."
  - `Приложение №1 к ДоЗ - Техническое задание.xlsx`: "масло хф 12-16..."
- audit note: snippets подтверждают наличие масел, но не код ОКПД2.
- recommendation: для `subject_okpd2_oil` требовать совпадение ОКПД2-кода или отдельный fallback label "subject oil without OKPD2".

#### rule_id: `oil_purpose`

- criterion: Назначение масла связано с оборудованием/техникой.
- status/risk: `unknown` / `low`
- pipeline comment: Подтверждающие фрагменты не найдены.
- quality: `missing`
- evidence snippets:
  - Evidence отсутствует.
- audit note: отсутствие evidence не блокирует pipeline, потому что priority `low`. Для ручной оценки назначение масла все равно полезно уточнить.
- recommendation: добавить synonyms по типам оборудования: турбины, компрессоры, гидросистемы, трансформаторы, редукторы.

#### rule_id: `oil_classification`

- criterion: Указан тип масла и стандарт применимости.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `good`
- evidence snippets:
  - `Приложение №1 к ДоЗ - Техническое задание.xlsx`: "турбинное масло | марка - тп-22с..."
  - `Приложение №1 к ДоЗ - Техническое задание.xlsx`: "вязкость кинематическая ... индекс вязкости..."
- historical post-fix behavior: до criteria refinement evidence отсутствовал, и `oil_classification` был high-priority blocker для `need_human_review`.
- post-criteria behavior: критерий расширен на industrial oils; `ТП-22С` / "турбинное масло" дают `pass`, `risk=low`, `human_review_required=false`.
- current scenario note: scenario все равно остается `need_human_review`, но уже не из-за `oil_classification`, а из-за `security_requirement`.

#### rule_id: `quantity_measure`

- criterion: Есть измеримая потребность.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `weak`
- evidence snippets:
  - `Приложение №1 к ДоЗ - Техническое задание.xlsx`: "наименование товара | ... | ед. изм. | кол-во"
  - `Приложение №1 к ДоЗ - Техническое задание.xlsx`: "нормативный документ ... | ед. изм. | кол-во"
- historical issue: top evidence раньше уходил в тару/упаковочные объемы.
- post-criteria behavior: evidence стал ближе к purchase quantity columns, но top snippets все еще не показывают полную строку товара с конкретным количеством.
- recommendation: backlog остается прежним: table evidence grouping для строки `товар + единица измерения + количество`.

#### rule_id: `procurement_method`

- criterion: Способ закупки - электронный аукцион.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `noisy`
- evidence snippets:
  - `Документация о закупке.docx`: "закупочная комиссия ... по результатам проведенной закупочной процедуры..."
  - `Документация о закупке.docx`: "изменить способ проведения закупки"
- manual source check: в related evidence по `msp_restriction` указано "запрос предложений в электронной форме", а не "электронный аукцион".
- historical issue: generic "закупочная процедура" не подтверждала электронный аукцион.
- post-criteria behavior: stricter criteria не устранил шум полностью; fresh top snippets содержат "не в электронной форме", договорные сроки и "на право заключения договора", но не прямой "электронный аукцион".
- recommendation: разделить способы закупки и не считать generic "электронная форма" / "закупочная процедура" подтверждением аукциона.

#### rule_id: `security_requirement`

- criterion: Обязательство по обеспечению участия в тендере или обеспечения по договору.
- status/risk: `pass` / `medium`
- pipeline comment: Найдено evidence с отрицанием требования обеспечения; требуется ручная проверка.
- quality: `conflict`
- evidence snippets:
  - `Документация о закупке.docx`: "если требование о предоставлении такого обеспечения было предусмотрено..."
  - `Извещение о закупке.docx`: "обеспечение заявки на участие ... не требуется"
  - `Извещение о закупке.docx`: "обеспечение исполнения обязательств по договору | не требуется"
- historical issue: rule получал `pass`, хотя evidence содержал как условные mentions, так и явные отрицательные признаки.
- post-fix behavior: negative security evidence уже ведет к concern, `risk=medium`, `human_review_required=true`.
- post-criteria behavior: explicit `negative_terms` подтверждают этот outcome; именно `security_requirement`, а не `oil_classification`, теперь является актуальной причиной `need_human_review`.

## 8. Recommendations

Часть рекомендаций из первичного audit уже закрыта production-fix и criteria refinement. Уже сделано:

- high-priority `pass` с `evidence_concerns` попадает в вопросы;
- `security_requirement` с отрицательным evidence не остается clean pass;
- `relevant_dealer` требует explicit МСП/СМП/dealer/partner evidence;
- `security_requirement` получил explicit `negative_terms` в `criteria.yaml`;
- `msp_restriction` сужен до explicit МСП/СМП terms;
- `procurement_method` стал строже вокруг электронного аукциона;
- `quantity_measure` уточнен в сторону количества закупки;
- `oil_classification` расширен на industrial oil terms.

Остальные пункты ниже остаются backlog-направлениями улучшения evidence quality.

### 8.1 `keyword_search.py`

- Добавить proximity scoring: повышать score, если ключевые признаки находятся рядом с предметом критерия.
- Понижать score для слишком общих слов: "договор", "товар", "поставщик", "закупка", "электронный", "обеспечение".
- Лучше группировать table evidence: возвращать строку таблицы целиком, если в ней есть товар + количество + единица.
- Учитывать source/document priority: техническое задание и спецификация выше общих процедурных разделов.
- Добавить поддержку negative keywords / negative phrases в search result metadata, без принятия решения на уровне поиска.

### 8.2 `criteria.yaml`

- Не добавлять standalone `ГОСТ` / `ТУ` / `ISO` / `DIN` как keywords без предметных соседей: это может усилить шум.
- Если потребуется следующий config-only pass, уточнять его по fresh false positives, а не возвращать уже закрытые broad terms.
- Для `procurement_method` может потребоваться еще более строгая phrase/proximity логика, потому что fresh run все еще ловит generic electronic document / electronic form snippets.
- Для `quantity_measure` может потребоваться отдельный table-aware критерий или metadata hint, потому что даже уточненные terms не вытаскивают полную строку с конкретным количеством.

### 8.3 `rule_engine.py`

- Расширить уже добавленную обработку suspicious evidence за пределы целевых rules, если это потребуется после новых audit samples.
- Учитывать `evidence_count`, source type и score distribution: один слабый procedural snippet не должен давать уверенный `pass`.
- Развить metadata `evidence_concerns` для `weak_evidence`, чтобы downstream мог задавать более точные вопросы.
- Усиливать `human_review_required` для других high-priority rules с noisy или contradictory evidence.
- Дальше уточнить `security_requirement`: различать "обеспечение требуется", "обеспечение не требуется" и "условное описание обеспечения" не только по exact phrases.

### 8.4 `questions_writer.py`

- Текущая post-fix механика уже выводит вопросы по high-priority `pass` с `evidence_concerns`, включая `security_requirement` и `msp_restriction`.
- Backlog: расширить механику вопросов на будущий deterministic quality layer для weak/noisy high-priority criteria.
- Добавлять human-readable reason: "найдено keyword evidence, но не подтверждено текущим evidence".
- Группировать вопросы по блокам: предмет, поставка, качество, процедура, цена.

### 8.5 DOCX/summary output

- Добавить раздел "Слабые основания" для criteria с weak/noisy evidence.
- Отдельно выводить criteria с missing evidence.
- Ограничить noisy snippets в summary: не показывать procedural snippets как подтвержденные без пометки.
- Для `scenario_result` показывать, какие rules реально повлияли на scenario и насколько evidence надежен.
- В DOCX-summary добавить предупреждение, что `pass` означает keyword confirmation, если quality layer еще не внедрен.

## 9. Suggested next implementation steps

1. Small safe improvements:
   - добавить в summary/questions пометку для high-priority `pass` с низким evidence quality после отдельного quality layer.
2. Medium improvements:
   - доработать ranking/snippet extraction для таблиц;
   - добавить source priority;
   - добавить proximity scoring для phrase groups.
3. Risky / needs review improvements:
   - расширить `rule_engine` до evidence-quality-aware scoring;
   - добавить отдельный deterministic quality layer между retrieval и rule scoring;
   - расширять scenario logic только при появлении новых business cases, не закрытых текущим `relevant_dealer` explicit indicator gate.

Большой rewrite не требуется. Уже выполненные criteria refinements не нужно повторять как backlog; оставшиеся проблемы лучше закрывать через table grouping, proximity/source ranking и отдельный evidence quality layer.

## 10. Appendix: commands and generated files

Preflight:

```bash
git branch --show-current
git status --short
git check-ignore -q outputs/debug && echo "outputs/debug ignored" || echo "outputs/debug NOT ignored"
```

Результаты preflight:

- branch: `develop`
- initial `git status --short`: empty
- `outputs/debug`: ignored
- `AGENTS.md`: найден и прочитан
- current update scope: изменялся только `tender-assistant-skill/docs/evidence_quality_audit.md`
- regression snapshots: отдельные tracked snapshot-файлы не обнаружены; expected scenarios заданы в `tender-assistant-skill/scripts/regression_check.py` (`EXPECTED_TENDER_SCENARIOS`) и рабочие regression outputs пишутся в ignored `outputs/debug/regression_check`

Historical pipeline commands:

```bash
python tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/evidence_quality_audit/tender_1" --top-k 5 --min-score 0
python tender-assistant-skill/run.py --input "sources_info/Тендер 2" --out "outputs/debug/evidence_quality_audit/tender_2" --top-k 5 --min-score 0
python tender-assistant-skill/run.py --input "sources_info/Тендер 3" --out "outputs/debug/evidence_quality_audit/tender_3" --top-k 5 --min-score 0
```

Historical audit parameters:

- `--top-k 5 --min-score 0`

Criteria refinement verification:

```bash
python tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_1" --top-k 5 --min-score 0
python tender-assistant-skill/run.py --input "sources_info/Тендер 2" --out "outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_2" --top-k 5 --min-score 0
python tender-assistant-skill/run.py --input "sources_info/Тендер 3" --out "outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_3" --top-k 5 --min-score 0
```

Criteria refinement pipeline results:

- `Тендер 1`: exit code `0`, generated `tender_score.json`, `questions_for_customer.md`, `tender_summary.md`, `tender_summary.docx`.
- `Тендер 2`: exit code `0`, generated `tender_score.json`, `questions_for_customer.md`, `tender_summary.md`, `tender_summary.docx`.
- `Тендер 3`: exit code `0`, generated `tender_score.json`, `questions_for_customer.md`, `tender_summary.md`, `tender_summary.docx`.

Criteria refinement analyzed output files:

- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_1/tender_score.json`
- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_1/tender_summary.md`
- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_1/questions_for_customer.md`
- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_2/tender_score.json`
- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_2/tender_summary.md`
- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_2/questions_for_customer.md`
- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_3/tender_score.json`
- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_3/tender_summary.md`
- `outputs/debug/evidence_quality_audit_after_criteria_refinement/tender_3/questions_for_customer.md`

Pipeline results:

- `Тендер 1`: exit code `0`, generated `tender_score.json`, `questions_for_customer.md`, `tender_summary.md`, `tender_summary.docx`.
- `Тендер 2`: exit code `0`, generated `tender_score.json`, `questions_for_customer.md`, `tender_summary.md`, `tender_summary.docx`.
- `Тендер 3`: exit code `0`, generated `tender_score.json`, `questions_for_customer.md`, `tender_summary.md`, `tender_summary.docx`.

Analyzed output files:

- `outputs/debug/evidence_quality_audit/tender_1/tender_score.json`
- `outputs/debug/evidence_quality_audit/tender_1/tender_summary.md`
- `outputs/debug/evidence_quality_audit/tender_1/questions_for_customer.md`
- `outputs/debug/evidence_quality_audit/tender_2/tender_score.json`
- `outputs/debug/evidence_quality_audit/tender_2/tender_summary.md`
- `outputs/debug/evidence_quality_audit/tender_2/questions_for_customer.md`
- `outputs/debug/evidence_quality_audit/tender_3/tender_score.json`
- `outputs/debug/evidence_quality_audit/tender_3/tender_summary.md`
- `outputs/debug/evidence_quality_audit/tender_3/questions_for_customer.md`

Generated output directories:

- `outputs/debug/evidence_quality_audit/tender_1`
- `outputs/debug/evidence_quality_audit/tender_2`
- `outputs/debug/evidence_quality_audit/tender_3`

Cleanup and verification:

- `outputs/debug` is ignored, so temporary audit outputs were left in ignored debug storage.
- `regression_check.py` used ignored `outputs/debug/regression_check` and finished with `ALL CHECKS PASSED`.
- During regression cleanup, Windows returned `PermissionError` warnings for ignored `outputs/debug/regression_check` files, but final regression git checks confirmed no `outputs/debug`, `__pycache__`, or `.pyc` entries in `git status --short`.

Verification commands run after this file was created:

```bash
test -f tender-assistant-skill/docs/evidence_quality_audit.md
git diff --stat
python tender-assistant-skill/scripts/regression_check.py
git diff -- tender-assistant-skill/docs/evidence_quality_audit.md
git status --short
```

Historical original audit verification results:

- `test -f ...`: Git Bash command could not start in this environment (`Bash/Service/CreateInstance/E_ACCESSDENIED`); PowerShell fallback `Test-Path` returned `exists`.
- `git diff --stat`: empty output because the audit file is new and still untracked.
- `python tender-assistant-skill/scripts/regression_check.py`: exit code `0`, final result `ALL CHECKS PASSED`.
- `git diff -- tender-assistant-skill/docs/evidence_quality_audit.md`: empty output because the audit file is new and still untracked.
- `git status --short`: `?? tender-assistant-skill/docs/evidence_quality_audit.md`.

Post-fix docs-only update:

- This document was updated after production-fix to separate historical audit findings from current pipeline behavior.
- No code, `regression_check.py`, or `README.md` changes are part of this docs-only update.

Current criteria-refinement docs-only verification:

- Fresh pipeline commands used `--top-k 5 --min-score 0`, matching historical audit parameters.
- Fresh outputs are under `outputs/debug/evidence_quality_audit_after_criteria_refinement`.
- Regression check command after this docs update: `python tender-assistant-skill/scripts/regression_check.py`.
- Regression check result: exit code `0`, final result `ALL CHECKS PASSED`.
- Regression expected scenarios remained:
  - `Тендер 1` -> `need_human_review`
  - `Тендер 2` -> `relevant_direct`
  - `Тендер 3` -> `need_human_review`
- Regression snapshots location: no separate tracked snapshot files were found; expected scenarios are stored in `tender-assistant-skill/scripts/regression_check.py`, while generated regression outputs are under ignored `outputs/debug/regression_check`.
- Regression cleanup warning: Windows `PermissionError` warnings remained only for ignored `outputs/debug/regression_check` files; `git status --short` did not include `outputs/debug`.
- Final git diff/status commands after this docs update:

```bash
git diff -- tender-assistant-skill/docs/evidence_quality_audit.md
git diff --stat
git status --short
```
