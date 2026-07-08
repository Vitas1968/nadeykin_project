# [A-ARCH-002] Архитектура анализа тендеров с selective shadow

## 1. Общая идея

В проекте есть две разные части анализа:

```text
1. Основной анализатор правил — deterministic layer
2. LLM-проверка — selective shadow
```

Главный принцип: **решение принимает обычный код**, а LLM используется только как дополнительная проверка в спорных местах.

Мини-словарь:

- **deterministic layer** — основной слой правил, то есть обычный код без нейросети;
- **LLM** — локальная языковая модель, то есть нейросеть для анализа коротких текстовых фрагментов;
- **shadow mode** — теневой режим, когда LLM проверяет результат, но не управляет решением;
- **selective shadow** — режим, в котором LLM вызывается только для полезных спорных случаев;
- **guardrail** — защитное правило, которое не даёт LLM гадать по слабым данным;
- **evidence** — найденный фрагмент документа, на основании которого правило делает вывод;
- **rule** — отдельное правило проверки;
- **status** — результат правила: пройдено, не пройдено, неизвестно или конфликт;
- **risk** — уровень риска: низкий, средний или высокий;
- **human_review_required** — флаг «нужна ручная проверка»;
- **scenario_result** — итоговый сценарий по тендеру;
- **llm_verdict** — мнение LLM по конкретному правилу.

Упрощённая схема:

```text
тендерные документы
        ↓
поиск evidence / релевантных фрагментов
        ↓
deterministic rule_engine
        ↓
rules: status / risk / human_review_required / comment
        ↓
selective LLM shadow
        ↓
scenario_classifier
        ↓
tender_score.json / tender_summary.md / questions_for_customer.md
```

---

## 2. Основной анализатор правил

Основной анализатор — это обычный код без нейросети.

Он берёт документы тендера, ищет нужные фрагменты и проверяет критерии:

```text
способ закупки
тип закупки: товар или услуга
ограничение МСП
обеспечение заявки / договора
и другие критерии
```

По каждому критерию он выставляет результат:

```text
status                 что с критерием
risk                   насколько это рискованно
human_review_required  нужна ли ручная проверка
comment                пояснение
evidence               найденные фрагменты из документов
```

Пример:

```text
procurement_method
status: fail
risk: high
human_review_required: true
comment: найден запрос предложений, а нужен электронный аукцион
```

Это главный слой. Именно он принимает решение.

---

## 3. Что такое `status`

`status` — это итог по конкретному правилу.

Основные варианты:

```text
pass      критерий пройден
fail      критерий не пройден
unknown   данных недостаточно
conflict  найдены противоречивые данные
```

Примеры:

```text
pass:
  найдено "электронный аукцион"
  критерий "способ закупки — электронный аукцион" выполнен

fail:
  найдено "запрос предложений"
  а нам нужен "электронный аукцион"

unknown:
  есть только слабые признаки электронной площадки,
  но явного способа закупки нет

conflict:
  в одном месте написано "аукцион",
  в другом — "запрос предложений"
```

---

## 4. Что такое `risk`

`risk` — насколько опасен результат.

```text
low     всё нормально
medium  есть неопределённость
high    есть блокирующая проблема
```

Примеры:

```text
pass + low:
  всё хорошо

unknown + medium:
  нужно проверить руками

fail + high:
  скорее всего тендер не подходит
```

---

## 5. Что такое `human_review_required`

`human_review_required` — это простой флаг:

```text
true   нужна ручная проверка
false  ручная проверка не нужна
```

Пример:

```text
procurement_method = unknown / medium / true
```

Это значит: способ закупки явно не найден, нужно смотреть человеку.

---

## 6. Что такое `scenario_result`

После проверки всех правил отдельный классификатор сценария смотрит на итоговую картину и выдаёт общий результат по тендеру:

```text
relevant_dealer       можно передавать дилеру / партнёру
relevant_direct       можно участвовать напрямую
need_human_review     нужна ручная проверка
not_relevant          тендер не подходит
```

Примеры по нашим тендерам:

```text
Тендер 1:
  все ключевые правила pass
  scenario = relevant_dealer

Тендер 2:
  procurement_method = unknown
  scenario = need_human_review

Тендер 3:
  procurement_method = fail
  scenario = need_human_review
```

---

## 7. Где здесь LLM

LLM — это нейросеть. В demo selective mode используется модель `qwen2.5:14b`.

Но в нашей архитектуре она **не принимает решение**.

Она не меняет:

```text
status
risk
human_review_required
comment
scenario_result
```

Она только добавляет дополнительное поле:

```text
llm_verdict
```

То есть LLM работает как проверяющий сбоку.

Отсюда название **shadow** — “теневой режим”.

Она смотрит на уже найденный `evidence` и говорит:

```text
я согласна с deterministic-решением
я не согласна
я не уверена
я не вызывалась
я не смогла ответить
```

Пример:

```text
procurement_method
deterministic: fail high true

llm_verdict:
  invocation_status: ok
  verdict: fail
  confidence: high
  conflicts_with_rule: false
  reason: найден запрос предложений, это не электронный аукцион
```

Это значит: LLM подтвердила решение обычного кода.

LLM нужна не для финального ответа, а для дополнительной проверки спорных фрагментов. В тендерных документах часто встречаются длинные формулировки, разные названия одного и того же требования и неоднозначные места. Обычный код остаётся главным, а LLM помогает увидеть, согласуется ли найденный `evidence` с выводом правила.

---

## 8. Что такое `llm_verdict`

`llm_verdict` — это мнение LLM по конкретному правилу.

Внутри него есть:

```text
invocation_status      что произошло с вызовом LLM
verdict                мнение LLM: pass/fail/unknown/conflict
confidence             уверенность LLM
conflicts_with_rule    конфликтует ли LLM с deterministic-решением
reason                 объяснение
error_type             ошибка, если была
```

Пример успешного вызова:

```text
llm.invocation_status: ok
llm.verdict: fail
llm.confidence: high
llm.conflicts_with_rule: False
llm.reason: запрос предложений не соответствует электронному аукциону
```

Пример пропуска:

```text
llm.invocation_status: skipped
llm.verdict: pass
llm.confidence: high
llm.reason: правило уже pass/low/no-review, LLM пропущена
```

Пример timeout:

```text
llm.invocation_status: unavailable
llm.verdict: unknown
llm.confidence: low
llm.error_type: timeout
```

---

## 9. Что такое selective shadow

Раньше LLM вызывалась по всем shadow-правилам подряд.

Например, по `Тендер 1`:

```text
purchase_type_goods
msp_restriction
procurement_method
security_requirement
```

Хотя все они уже были:

```text
pass / low / human_review_required=False
```

То есть обычный код уже сказал: всё нормально.

Но LLM всё равно запускалась. На `qwen2.5:14b` это занимало 10–12 минут.

Selective shadow решает эту проблему.

Теперь логика такая:

```text
если правило уже:
  status = pass
  risk = low
  human_review_required = false

то LLM не вызываем
```

Вместо реального вызова LLM сразу записываем:

```text
llm.invocation_status = skipped
llm.verdict = pass
llm.confidence = high
reason = skipped by selective mode
```

Эта логика включается через:

```powershell
$env:TENDER_LLM_SELECTIVE_ENABLED="true"
```

А если нужно временно отключить selective-пропуск и снова гонять LLM даже по `pass`-правилам:

```powershell
$env:TENDER_LLM_RUN_ON_PASS="true"
```

---

## 10. Что такое guardrail skip

Есть ещё один вид пропуска LLM — **guardrail skip**.

Это не то же самое, что selective skip.

### Selective skip

Правило хорошее, LLM не нужна.

Пример:

```text
procurement_method
deterministic: pass low false
LLM skipped
```

### Guardrail skip

Правило может быть проблемным, но `evidence` слишком слабый, чтобы давать его LLM.

Пример из `Тендер 2`:

```text
procurement_method
deterministic: unknown medium true
llm: skipped unknown low
reason: Evidence does not contain explicit procurement method phrase.
```

Смысл: если нет явной фразы типа:

```text
электронный аукцион
запрос предложений
запрос котировок
конкурс
```

то LLM не спрашиваем. Иначе она начнёт угадывать.

Коротко:

```text
selective skip = всё уже хорошо, LLM не нужна
guardrail skip = данных мало, LLM не должна гадать
```

---

## 11. Когда LLM реально вызывается

LLM вызывается только если одновременно выполняются два условия:

```text
1. Правило не очевидно хорошее
2. Evidence достаточно явный для LLM
```

То есть LLM вызывается, если есть что-то вроде:

```text
status = fail
risk = high
human_review_required = true
```

и при этом `evidence` содержит понятную фразу.

Пример из `Тендер 3`:

```text
procurement_method
deterministic: fail high true
evidence: запрос предложений
```

Тут LLM вызывается, потому что:

```text
правило проблемное
найден явный способ закупки
LLM может проверить, соответствует ли это электронному аукциону
```

Результат:

```text
llm.verdict: fail
llm.confidence: high
llm.conflicts_with_rule: False
```

То есть LLM подтвердила deterministic-решение.

---

## 12. Что будет, если LLM ошиблась или не ответила

Если LLM ошиблась, не ответила, вернула невалидный JSON или сработал timeout, итоговое решение не меняется.

В `tender_score.json` это отражается только внутри `llm_verdict`:

```text
invocation_status: unavailable / error / invalid_json
verdict: unknown
confidence: low
warnings: причина проблемы
```

Поля обычного правила остаются прежними:

```text
status
risk
human_review_required
comment
scenario_result
```

Именно поэтому итоговое решение нельзя отдавать LLM: модель может ошибиться, не увидеть контекст или не ответить вовремя. Для MVP безопаснее, чтобы решение принимал deterministic layer, а LLM оставалась диагностическим помощником.

---

## 13. Как это выглядит на наших трёх тендерах

### Тендер 1

```text
scenario: relevant_dealer
blocking: []
```

Все shadow-правила:

```text
pass / low / false
```

Поэтому:

```text
LLM real calls = 0
все llm_verdict = skipped/pass/high
время = около 4.5 секунды
```

### Тендер 2

```text
scenario: need_human_review
blocking: procurement_method
```

Почему ручная проверка:

```text
procurement_method = unknown / medium / true
```

LLM не вызвалась, потому что guardrail сказал:

```text
нет явной фразы способа закупки
```

Это правильно: не заставляем модель угадывать.

### Тендер 3

```text
scenario: need_human_review
blocking: procurement_method
```

Почему:

```text
procurement_method = fail / high / true
```

Нашли:

```text
запрос предложений
```

А нужно:

```text
электронный аукцион
```

LLM вызвалась один раз и подтвердила:

```text
verdict = fail
confidence = high
conflicts_with_rule = false
```

---

## 14. Главное преимущество

Раньше:

```text
LLM вызывалась почти всегда
qwen2.5:14b тормозила
один тендер мог идти 10–12 минут
часть вызовов падала по timeout
```

Теперь:

```text
LLM вызывается только там, где есть смысл
pass-правила не гоняются через модель
слабые evidence не отправляются в модель
batch из 3 тендеров прошёл примерно за 1:44
timeout = 0
```

Итоговая идея простая:

```text
Обычный код принимает решение.
LLM выборочно проверяет спорные места.
Если всё очевидно хорошо — LLM не трогаем.
Если данных мало — LLM не заставляем гадать.
Если найден явный риск — LLM может подтвердить или показать конфликт.
```
