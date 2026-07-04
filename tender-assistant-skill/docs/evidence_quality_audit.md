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

Audit основан на текущих `criteria.yaml`, `keyword_search.py` и `rule_engine.py`. Важное наблюдение по коду: `rule_engine` считает подтверждающим любое evidence со `score > 0`, а текущий `criteria.yaml` не задает явных `negative_keywords` / `negative_terms`. Поэтому часть `pass` фактически означает "найдено keyword evidence", а не "критерий надежно подтвержден".

Checkpoint после `Тендер 1`: labels применяются согласованно. `missing` использован только при отсутствии evidence, `conflict` только при противоречивых признаках, `good` не ставился для косвенных procedural snippets. Audit продолжен по `Тендер 2` и `Тендер 3`.

## 3. Общая сводка

| Tender | Scenario | Rules total | Good | Weak | Noisy | Missing | Conflict | Main issue |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Тендер 1 | `relevant_dealer` | 18 | 14 | 2 | 2 | 0 | 0 | `pass` по нескольким правилам держится на слабых или процедурных snippets, при этом `security_requirement` ошибочно выглядит подтвержденным на фразах "не требуется". |
| Тендер 2 | `relevant_dealer` | 18 | 9 | 5 | 4 | 0 | 0 | Наиболее рискован ложный `pass` по `msp_restriction`: evidence не подтверждает ограничение МСП, но именно это правило ведет к `relevant_dealer`. |
| Тендер 3 | `need_human_review` | 18 | 12 | 1 | 2 | 2 | 1 | Сценарий корректно уходит в ручную проверку из-за missing `oil_classification`, но есть шумные `pass` по ОКПД2/количеству/способу закупки и конфликт по обеспечению. |

## 4. Cross-tender findings

- Чаще всего weak/noisy evidence встречается у `oil_purpose`, `quantity_measure`, `procurement_method`, `security_requirement`, `msp_restriction`.
- Лучший evidence обычно дают технические задания, спецификации и project contract sections, где есть таблицы с предметом, сроками, местом поставки, упаковкой, качеством и ценой.
- Хуже всего работают общие procedural documents: они дают много совпадений по словам "закупка", "договор", "обеспечение", "поставщик", но не всегда подтверждают конкретный критерий.
- `keyword_search.py` ранжирует совпадения по сумме term matches без proximity к смысловому объекту. Поэтому фразы "обеспечение не требуется", "только зарегистрированный участник", "приложение 2" могут стать `pass`.
- `criteria.yaml` смешивает must-have признаки и broad query terms. Например, `procurement_method` ищет "способ закупки электронный аукцион url адрес процедуры", но находит generic "закупочная процедура".
- `rule_engine.py` не различает подтверждающее, отрицательное и нейтральное evidence. Отсутствие negative patterns особенно заметно по `security_requirement`.
- `questions_writer.py` сейчас формирует вопросы только по `human_review_required` / `unknown` / `fail` / `conflict`. Weak/noisy `pass` не попадают в вопросы, хотя именно они требуют ручной проверки.

## 5. Tender 1 audit

### 5.1 Scenario

- scenario: `relevant_dealer`
- recommendation: передать тендер дилеру/партнеру из-за признака ограничения МСП.
- confidence: `high`
- human_review_required: `false`
- blocking_criteria: нет
- reasons: `msp_restriction` имеет status `pass`

Pipeline stats:

- documents: 7
- rules: 18
- pass: 18
- unknown/fail/conflict: 0
- human_review_required: 0

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
| `security_requirement` | pass | low | false | 5 | noisy | Evidence содержит "обеспечение заявки ... не требуется" и "обеспечение исполнения договора ... не требуется"; keyword match не подтверждает обязательство. |
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
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `noisy`
- evidence snippets:
  - `Документация.docx`: "обеспечение заявки на участие в закупке | не требуется"
  - `Документация.docx`: "обеспечение исполнения договора | не требуется."
- audit note: evidence прямо указывает отсутствие требования, но rule получает `pass`.
- recommendation: добавить negative patterns для "не требуется", "не установлено", "не предусмотрено" рядом с обеспечением.

## 6. Tender 2 audit

### 6.1 Scenario

- scenario: `relevant_dealer`
- recommendation: передать тендер дилеру/партнеру из-за признака ограничения МСП.
- confidence: `high`
- human_review_required: `false`
- blocking_criteria: нет
- reasons: `msp_restriction` имеет status `pass`

Pipeline stats:

- documents: 8
- rules: 18
- pass: 18
- unknown/fail/conflict: 0
- human_review_required: 0

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
| `msp_restriction` | pass | low | false | 5 | noisy | Evidence про личный кабинет/ЕИС/аккредитацию, не про МСП; этот `pass` влияет на сценарий. |
| `procurement_method` | pass | low | false | 5 | noisy | Snippets про электронный документооборот и обеспечение, не про электронный аукцион. |
| `price_nmc` | pass | low | false | 5 | weak | Evidence показывает price table fields и "итого не указано"; НМЦ подтверждена неполно. |
| `security_requirement` | pass | low | false | 5 | good | Есть "обеспечение исполнения контракта" и независимая гарантия. |
| `national_regime` | pass | low | false | 5 | weak | Evidence в основном шаблонное: "если ... установлены запрет/ограничение/преимущество". |
| `contract_terms` | pass | low | false | 5 | weak | Evidence в основном "приложение 2"; проект контракта вероятен, но условие подтверждено слабо. |
| `after_sales_service` | pass | low | false | 5 | good | Есть обязанности по устранению недостатков и поставке остатка. |

### 6.3 Problematic rules

#### rule_id: `msp_restriction`

- criterion: Закупка только для субъектов МСП.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `noisy`
- evidence snippets:
  - `Приложение ПИК...docx`: "личный кабинет ... доступная только зарегистрированным ... пользователям"
  - `Требование к содержанию...docx`: "участник закупки вправе подать только одну заявку..."
  - `Требование к содержанию...docx`: "подать заявку ... вправе только зарегистрированный ... участник закупки..."
- audit note: snippets не подтверждают ограничение МСП. При этом `scenario_classifier` использует `msp_restriction pass` как основание для `relevant_dealer`.
- recommendation: усилить критерий МСП: требовать фразу "субъекты МСП/СМП/малого и среднего предпринимательства" в одном snippet.

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
- audit note: keyword matching по "способ" и "электронный" не подтверждает "электронный аукцион".
- recommendation: искать точную phrase "электронный аукцион" или конкретное поле "способ закупки".

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

- scenario: `need_human_review`
- recommendation: передать на ручную проверку из-за недостаточности данных.
- confidence: `medium`
- human_review_required: `true`
- blocking_criteria: `oil_classification`
- reasons: high-priority criterion `oil_classification` не подтвержден.

Pipeline stats:

- documents: 11
- rules: 18
- pass: 16
- unknown: 2
- fail/conflict: 0
- human_review_required: 1

### 7.2 Rule-level evidence quality

| rule_id | status | risk | human_review_required | evidence_count | quality | comment |
|---|---|---|---|---:|---|---|
| `subject_okpd2_oil` | pass | low | false | 5 | weak | Evidence подтверждает масла, но не показывает ОКПД2. |
| `subject_title_oil` | pass | low | false | 5 | good | Есть "турбинное масло", "масло ХФ 12-16", compressor oil. |
| `purchase_type_goods` | pass | low | false | 5 | good | Есть договорные положения о товаре, поставке, приемке и разгрузке. |
| `oil_purpose` | unknown | low | false | 0 | missing | Evidence отсутствует. |
| `oil_classification` | unknown | medium | true | 0 | missing | Evidence отсутствует; это корректно ведет к `need_human_review`. |
| `quantity_measure` | pass | low | false | 5 | noisy | Top evidence про тару/упаковку и объемы упаковки, а не измеримую потребность по товару. |
| `delivery_period` | pass | low | false | 5 | good | Есть "август 2026 г." и срок поставки товара. |
| `delivery_location` | pass | low | false | 5 | good | Есть склад заказчика: г. Советск, ул. Энергетиков, д. 1г. |
| `packaging_format` | pass | low | false | 5 | good | Есть металлические бочки 200-250 л и полимерные канистры/бутыли 1/3/5/10 л. |
| `quality_freshness` | pass | low | false | 5 | good | Есть "срок изготовления товара - не ранее второй половины 2025г.". |
| `quality_documents` | pass | low | false | 5 | good | Есть паспорт качества, сертификат качества, декларация соответствия. |
| `msp_restriction` | pass | low | false | 5 | good | Evidence прямо говорит, что участниками могут быть только субъекты МСП. |
| `procurement_method` | pass | low | false | 5 | noisy | Evidence говорит о закупочной процедуре, но не подтверждает "электронный аукцион"; manual source check показывает "запрос предложений". |
| `price_nmc` | pass | low | false | 5 | good | Есть НМЦ `12 417 117.71 руб.` с НДС и `10 177 965.33 руб.`. |
| `security_requirement` | pass | low | false | 5 | conflict | Есть условные snippets про обеспечение и прямые snippets "не требуется". |
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
- status/risk: `unknown` / `medium`
- pipeline comment: Подтверждающие фрагменты не найдены.
- quality: `missing`
- evidence snippets:
  - Evidence отсутствует.
- audit note: это корректный high-priority blocker для `need_human_review`.
- recommendation: расширить критерий за пределы моторных масел: ГОСТ/ТУ, DIN, ISO, марка ТП-22С, ХФ 12-16, compressor oil standards.

#### rule_id: `quantity_measure`

- criterion: Есть измеримая потребность.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `noisy`
- evidence snippets:
  - `Приложение №1 к ДоЗ - Техническое задание.xlsx`: "требования к таре упаковке маркировке товара | ... бочки ... 200 до 250 литров..."
- audit note: snippet подтверждает формат упаковки, но не количество закупаемой потребности.
- recommendation: искать значения в строках номенклатуры: товар + единица измерения + количество.

#### rule_id: `procurement_method`

- criterion: Способ закупки - электронный аукцион.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `noisy`
- evidence snippets:
  - `Документация о закупке.docx`: "закупочная комиссия ... по результатам проведенной закупочной процедуры..."
  - `Документация о закупке.docx`: "изменить способ проведения закупки"
- manual source check: в related evidence по `msp_restriction` указано "запрос предложений в электронной форме", а не "электронный аукцион".
- audit note: current evidence не подтверждает критерий; status `pass` слишком уверенный.
- recommendation: разделить способы закупки и не считать generic "закупочная процедура" подтверждением аукциона.

#### rule_id: `security_requirement`

- criterion: Обязательство по обеспечению участия в тендере или обеспечения по договору.
- status/risk: `pass` / `low`
- pipeline comment: Критерий подтвержден найденными фрагментами: 5.
- quality: `conflict`
- evidence snippets:
  - `Документация о закупке.docx`: "если требование о предоставлении такого обеспечения было предусмотрено..."
  - `Извещение о закупке.docx`: "обеспечение заявки на участие ... не требуется"
  - `Извещение о закупке.docx`: "обеспечение исполнения обязательств по договору | не требуется"
- audit note: rule получает `pass`, но evidence содержит как условные mentions, так и явные отрицательные признаки.
- recommendation: обрабатывать "не требуется" как negative evidence; при смеси conditional и direct-negative ставить `human_review_required`.

## 8. Recommendations

### 8.1 `keyword_search.py`

- Добавить proximity scoring: повышать score, если ключевые признаки находятся рядом с предметом критерия.
- Понижать score для слишком общих слов: "договор", "товар", "поставщик", "закупка", "электронный", "обеспечение".
- Лучше группировать table evidence: возвращать строку таблицы целиком, если в ней есть товар + количество + единица.
- Учитывать source/document priority: техническое задание и спецификация выше общих процедурных разделов.
- Добавить поддержку negative keywords / negative phrases в search result metadata, без принятия решения на уровне поиска.

### 8.2 `criteria.yaml`

- Уточнить `procurement_method`: искать точные phrase values (`электронный аукцион`, `запрос предложений`, `конкурс`) вместо broad "способ закупки".
- Для `msp_restriction` требовать explicit terms: `субъекты МСП`, `субъекты малого и среднего предпринимательства`, `СМП`.
- Для `security_requirement` добавить negative patterns: `не требуется`, `не установлено`, `не предусмотрено`.
- Для `oil_classification` расширить synonyms за пределы моторных масел: `ГОСТ`, `ТУ`, `DIN`, `ISO`, `ТП-22С`, `ХФ 12-16`, `VDL`.
- Разделить критерий `quantity_measure` на "есть количество закупки" и "есть требования к упаковочным объемам".

### 8.3 `rule_engine.py`

- Не ставить `pass` только из-за наличия `score > 0`, если evidence содержит negative patterns.
- Учитывать `evidence_count`, source type и score distribution: один слабый procedural snippet не должен давать уверенный `pass`.
- Ввести промежуточный статус или metadata для `weak_evidence`, чтобы downstream мог задавать вопросы.
- Усиливать `human_review_required` для high-priority rules с noisy или contradictory evidence.
- Для `security_requirement` различать "обеспечение требуется", "обеспечение не требуется" и "условное описание обеспечения".

### 8.4 `questions_writer.py`

- Формировать вопросы по weak/noisy high-priority criteria, даже если `rule_engine` поставил `pass`.
- Добавлять human-readable reason: "найдено keyword evidence, но не подтверждено текущим evidence".
- Группировать вопросы по блокам: предмет, поставка, качество, процедура, цена.
- Добавлять вопросы по `msp_restriction`, если scenario зависит от этого rule, а evidence не содержит explicit MСП terms.
- Для `security_requirement` задавать вопрос при наличии "не требуется" рядом с "обеспечение".

### 8.5 DOCX/summary output

- Добавить раздел "Слабые основания" для criteria с weak/noisy evidence.
- Отдельно выводить criteria с missing evidence.
- Ограничить noisy snippets в summary: не показывать procedural snippets как подтвержденные без пометки.
- Для `scenario_result` показывать, какие rules реально повлияли на scenario и насколько evidence надежен.
- В DOCX-summary добавить предупреждение, что `pass` означает keyword confirmation, если quality layer еще не внедрен.

## 9. Suggested next implementation steps

1. Small safe improvements:
   - добавить negative patterns в `criteria.yaml` для `security_requirement`;
   - уточнить keywords для `msp_restriction` и `procurement_method`;
   - добавить в summary/questions пометку для high-priority `pass` с низким evidence quality после отдельного quality layer.
2. Medium improvements:
   - доработать ranking/snippet extraction для таблиц;
   - добавить source priority;
   - добавить proximity scoring для phrase groups.
3. Risky / needs review improvements:
   - расширить `rule_engine` до evidence-quality-aware scoring;
   - добавить отдельный deterministic quality layer между retrieval и rule scoring;
   - пересмотреть сценарную логику, чтобы `relevant_dealer` не зависел от шумного `msp_restriction pass`.

Большой rewrite не требуется. Основные проблемы можно закрывать точечно: criteria refinements, negative patterns, table grouping, proximity/source ranking.

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
- `tender-assistant-skill/docs/evidence_quality_audit.md`: файла не было, создан новый

Pipeline commands:

```bash
python tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/evidence_quality_audit/tender_1" --top-k 5 --min-score 0
python tender-assistant-skill/run.py --input "sources_info/Тендер 2" --out "outputs/debug/evidence_quality_audit/tender_2" --top-k 5 --min-score 0
python tender-assistant-skill/run.py --input "sources_info/Тендер 3" --out "outputs/debug/evidence_quality_audit/tender_3" --top-k 5 --min-score 0
```

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

Verification results:

- `test -f ...`: Git Bash command could not start in this environment (`Bash/Service/CreateInstance/E_ACCESSDENIED`); PowerShell fallback `Test-Path` returned `exists`.
- `git diff --stat`: empty output because the audit file is new and still untracked.
- `python tender-assistant-skill/scripts/regression_check.py`: exit code `0`, final result `ALL CHECKS PASSED`.
- `git diff -- tender-assistant-skill/docs/evidence_quality_audit.md`: empty output because the audit file is new and still untracked.
- `git status --short`: `?? tender-assistant-skill/docs/evidence_quality_audit.md`.
