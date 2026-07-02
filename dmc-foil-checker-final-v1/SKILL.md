---
name: dmc-foil-checker
description: >-
  Verify DataMatrix (DMC / Честный Знак) marking codes and pack-foil status from
  a large field-audit spreadsheet (the FMC / "Проверка DMC" export with Photo
  URL and Photo URL DMC columns). Use this skill WHENEVER the user wants to (a)
  confirm that the DMC code decoded from a pack photo matches the expected code
  on file, (b) check whether the foil has been removed from a cigarette pack in
  a photo, or (c) process an .xlsx where columns like "DMC Code", "Photo URL",
  "Photo URL DMC", "Фольга снята с пачки", "На Photo URL есть фото DMC", or "DMC
  код совпадает с кодом на пачке" need to be filled in. Trigger this even if the
  user just says "проверь dmc коды", "сверь коды с фоток", "проверь снята ли
  фольга", or uploads a big FMC/marking audit file — the workbook is far too
  large to eyeball and needs the bundled OCR/barcode + multimodal pipeline.
  The columns AI/AJ/AK use the audit convention "1 = критерий НЕ соблюдается,
  пусто = соблюдается", and the final verdict AN ("1" валидный / "0" не
  валидный) is derived from them plus the AE/AF presence rules.
---

# DMC + Foil Checker

> **Окружение Forge:** `zxingcpp`, `cv2`, `Pillow`, `numpy` уже установлены. Не запускай `pip install`.

## Выбор модели для foil-проверки

Модель берётся из `--model` / `LITELLM_MODEL` (+ `--base-url`/`--api-key` или
`LITELLM_BASE_URL`/`LITELLM_API_KEY`). **Дефолт — `dots.mocr`** (мультимодальная,
которую сейчас отдаёт внутренний прокси-ключ). На пробе из 15 фото она показала
лучший open-recall и при этом локальная/бесплатная/быстрая (~0.2 с/фото):

| Режим | open-recall (проба 15 фото) | Стоимость* (41k) |
|-------|------------------------------|------------------|
| `dots.mocr` (дефолт, локальная) | **14/14** | $0, ~0.2 с/фото |
| `gemini-2.5-flash` + `--reasoning-effort none` | ~11–12/14 | ~$20 (~$0.0005/фото) |
| `gemini-2.5-flash` (thinking on) | ~12/14 | ~$120 (~$0.003/фото) |
| `gemma-4-31b-nd` (старый локальный) | ~2–3/14 на полном кадре | $0, ~20 с/фото |

> ⚠️ **Оговорка по dots.mocr:** проба перекошена (14 открытых / 1 закрытая), и модель
> назвала открытыми ВСЕ кадры. Её **specificity на закрытых пачках не проверена** —
> возможен уклон «всегда open». Прогони на заведомо закрытых/запечатанных пачках,
> прежде чем доверять ей пометку «закрыта».

Переключение на Gemini (если нужна проверенная точность на закрытых):
```bash
export LITELLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
export LITELLM_API_KEY="<твой Google AI ключ, AIzaSy...>"
export LITELLM_MODEL="gemini-2.5-flash"
# и добавь --reasoning-effort none  (на gemini-2.5-flash убирает ~930 thinking-токенов
# на фото → ~6× дешевле при ≈той же точности)
```

`gemma-4-31b-nd` для foil ненадёжна (масштабо-зависима: на полном кадре почти всегда
«закрыто»). Парсер ответов модели терпим к мусору: код-фенсы, обрезанный JSON и
кривой JSON со «съехавшими» скобками чинятся regex-салвэджем, плюс один авто-ретрай
на `bad_schema`.

\* по замеренным токенам (фото ~733 in; out ~100 без thinking / ~1050 с thinking) и
ориентировочным тарифам Gemini 2.5 Flash (input ~$0.30/1M, output ~$2.50/1M) — **уточни
актуальные тарифы**. Токен вида `AQ.Ab8…` похож на короткоживущий OAuth (протухнет за
~час и уронит долгий батч) — для прода нужен стабильный API-ключ `AIzaSy…`.

## ВЫПОЛНИ ЭТИ ШАГИ ПО ПОРЯДКУ. БЕЗ ОТСТУПЛЕНИЙ.

**Шаг 1 — извлечь строки (запусти прямо сейчас, без каких-либо проверок до этого):**

```bash
python scripts/extract_rows.py ПУТЬ_К_ФАЙЛУ.xlsx -o rows.jsonl
```

> **СТОП. НЕ ДЕЛАЙ перед этим:** не читай .xlsx через openpyxl/pandas, не открывай
> zip вручную, не смотри заголовки через python -c, не декодируй XML.
> Заголовки в raw XML хранятся как HTML-entities (&#1058;&#1080;&#1087;...) — читать их
> глазами бесполезно. Скрипт сам находит колонки по буквам AE/AF/AG/AH.
> Результат будет через секунды, и только тогда проверяй что вышло.

> **Проверь stderr extract_rows.** Он печатает `dmc_ref/photo_pack/photo_dmc: N/N
> непустых`. Если видишь `WARNING: колонка … пуста` — значит не та буква колонки
> или не тот лист (НЕ дамси XML руками!): сверь заголовок и передай `--col-ref /
> --col-photo-pack / --col-photo-dmc / --sheet`. Чини это ДО прогона — иначе
> получишь «AN=0 у всех» на пустом входе.

**Шаг 2 — sample-прогон + PRE-FLIGHT доступности картинок:**

```bash
python scripts/run_batch.py rows.jsonl --limit 10 --out results.jsonl --foil --workers 5
```

Убедись что в results.jsonl у строк есть `AI_foil_removed` (не null), `decoded` (не null)
и `decode_error` пустой. **Если `decode_error` = `download_error: …` у всех — картинки
недоступны со стенда** (внешний хост за VPN/файрволом, напр. `icontact.one`). Проверь
руками одну ссылку и не запускай полный прогон, пока не починишь доступ:

```bash
python3 -c "import json;print(json.loads(open('rows.jsonl').readline())['photo_dmc'])"
curl -sS -o /dev/null -m 20 -w "HTTP=%{http_code} time=%{time_total}s\n" "<URL_из_строки_выше>"
```

Таймаут/000 → картинки не качаются: это сеть/доступность, **а не баг extract и не плохие данные**.
Foil тогда у всех будет «не определено», а AN=0 — но это про пайплайн, не про партию.

> Если переменные Gemini не заданы и используется локальный прокси — замени `--workers 5` на `--workers 2` (сервер не держит больше 2 параллельных запросов).

**Шаг 3 — полный прогон через FOREGROUND-цикл с `--max-seconds`. Фон НЕ нужен.**

Полный прогон длинный (тысячи фото), а у bash-тула таймаут (часто ~120с) и **фоновые
процессы (`nohup … &`) на некоторых стендах НЕ выживают** после обрыва вызова. Поэтому
НЕ полагайся на фон и НЕ пиши свои скрипты с ручной нарезкой батчей (`--limit`/offset) —
именно так теряются строки и плодятся race-condition'ы. Вместо этого — `run_batch`
с **бюджетом по времени**: один вызов сам останавливается до таймаута тула, дописывает
`results.jsonl`, выходит; чекпоинтинг (`load_done`) при следующем вызове продолжает.

Гоняй ОДНУ И ТУ ЖЕ команду по одному вызову за ход, пока `results` не догонит `rows`:

Для большого файла иди в ДВА паса — сперва быстрый DMC, потом долгий foil.

**Пас 1 — DMC у ВСЕХ строк, БЫСТРО (минуты).** Загрузки I/O-bound → воркеров много,
БЕЗ `--foil`. Даёт AJ/AK сразу (можно отдать частичный результат, пока идёт фольга):
```bash
mkdir -p output
python scripts/run_batch.py rows.jsonl --out results.jsonl --workers 32 --max-seconds 100
echo "$(wc -l < results.jsonl)/$(wc -l < rows.jsonl) DMC"   # повторяй, пока не сравняется
```

**Пас 2 — фольга (AI/AN), ДОЛГО.** Та же команда + `--foil --workers 2`. Чекпоинтинг
foil-aware: строки из паса 1 (только DMC) дозаливаются фольгой, готовое не трогается:
```bash
python scripts/run_batch.py rows.jsonl --out results.jsonl --foil --workers 2 --max-seconds 100
echo "фольга: $(grep -c '\"foil_checked\": true' results.jsonl)/$(wc -l < rows.jsonl)"   # повторяй до полноты
```
Повторяй ровно эту команду паса 2 на каждом ходе, пока счётчик не сравняется. Каждый
вызов выходит сам по бюджету (`[run_batch] бюджет … исчерпан`).

> ## ДОЛГО — это НОРМАЛЬНО. НЕ паникуй и НИЧЕГО не «оптимизируй».
> foil = один вызов LLM на фото (~4с у `dots.mocr`), и эндпоинт держит максимум 2
> параллельных. Замерено на реальных фото:
>
> | `--workers` (foil) | скорость | 5000 строк |
> |---|---|---|
> | 1 | 0.22 стр/с | ~6 ч |
> | **2 — оптимум** | **0.40 стр/с** | **~3.5 ч** |
> | 4 | 0.35 стр/с | МЕДЛЕННЕЕ (сервер деградирует) |
> | 8 | 0.28 стр/с | ещё хуже |
>
> **НЕ поднимай `--workers` выше 2 для foil — это измеримо МЕДЛЕННЕЕ**, сервер
> захлёбывается. НЕ перезапускай с нуля, НЕ нарезай батчи руками, НЕ пиши свой скрипт,
> НЕ ищи «обходные пути». 5000 строк ≈ 3.5 часа — это просто цена эндпоинта, а не
> поломка. Твоя единственная задача: вызывать ту же команду паса 2 каждый ход до
> полноты. Пауза/подвисание на кадре — норма (хост медленно отдаёт фото).
>
> Хочешь реально быстрее (это решает пользователь, не ты): либо масштабировать сам
> эндпоинт `dots.mocr` (больше реплик/GPU → тогда воркеры >2 помогут), либо перейти
> на Gemini (`--workers 5`, см. «Выбор модели»). В рамках скилла ускорить нельзя.

**ПРОВЕРЬ ПОЛНОТУ перед Шагом 4** — гарантия, что ни одно фото не потеряно:

```bash
echo "results=$(wc -l < results.jsonl)  rows=$(wc -l < rows.jsonl)"   # должны совпасть
```

Если `results` меньше `rows` — повтори команду ещё раз, она догонит (чекпоинтинг).

> **Падение/таймаут/убийство не теряют данные:** `results.jsonl` дописывается построчно,
> чекпоинтинг пропускает готовые. Каждый упавший кадр пишется как ошибка (= «обработан»),
> поэтому цикл сходится. Ручная нарезка батчей не нужна и вредна.
>
**Опционально — hands-off фон через `setsid` (если выживает на стенде).** `setsid`
кладёт процесс в НОВУЮ сессию/группу, поэтому переживает kill группы bash-вызова
(в отличие от `nohup`, который остаётся в той же группе). Но это не «гарантированно»:
если песочница сносит весь cgroup/контейнер после вызова — не выживет ничего. Сначала
ОДНОРАЗОВО проверь пробой:

```bash
rm -f /tmp/_alive; setsid bash -c 'sleep 8; echo ok > /tmp/_alive' </dev/null >/dev/null 2>&1 &
echo "проба запущена — проверь /tmp/_alive СЛЕДУЮЩИМ ходом"
```
Следующим ходом: `cat /tmp/_alive 2>/dev/null && echo "ФОН ВЫЖИВАЕТ" || echo "НЕ выжил → foreground --max-seconds"`.

Если выжил — запусти тот же resumable-цикл в фоне и полли лог (без `--max-seconds`):
```bash
mkdir -p output; TOTAL=$(wc -l < rows.jsonl)
setsid bash -c '
  for p in $(seq 1 60); do
    d=$([ -f results.jsonl ] && wc -l < results.jsonl || echo 0); [ "$d" -ge "'"$TOTAL"'" ] && break
    python scripts/run_batch.py rows.jsonl --out results.jsonl --foil --workers 2
  done; echo "[loop] ГОТОВО $(wc -l < results.jsonl)/'"$TOTAL"'"' </dev/null > output/batch.log 2>&1 &
echo launched
```
Поллинг: `tail -n 3 output/batch.log; echo "$(wc -l < results.jsonl)/$(wc -l < rows.jsonl)"`.
Не выжил — остаёшься на foreground `--max-seconds` выше (работает ВЕЗДЕ).

`--foil` нужен только если просят фольгу. Без него AI/AN не имеют смысла — на Шаге 4
заполняй исходник с `--dmc-only` (только AJ/AK).

**Шаг 4 — отчёт в Excel = КОПИЯ ИСХОДНИКА с заполненными колонками. НЕ рисуй свой xlsx!**

🚫 **НЕ создавай отдельный workbook со своими листами/аналитикой.** Отчёт — это сам
исходный файл, дополненный. `--mode xlsx` грузит исходник (все листы/форматирование
сохраняются), вписывает только существующие колонки и сохраняет в копию. Одна команда:

```bash
# DMC + фольга:
python scripts/write_results.py results.jsonl \
    --mode xlsx --template ИСХОДНЫЙ.xlsx --out output/ИСХОДНЫЙ_заполнен.xlsx --review output/review.csv

# ТОЛЬКО DMC (прогон без --foil): добавь --dmc-only — впишет только AJ/AK,
# а AI/AN НЕ тронет (без фольги они были бы вечными AI=1/AN=0 — враньё):
python scripts/write_results.py results.jsonl \
    --mode xlsx --template ИСХОДНЫЙ.xlsx --out output/ИСХОДНЫЙ_заполнен.xlsx --dmc-only
```

> ⚠️ Пишутся РОВНО нужные колонки (AI/AJ/AK/AN, либо только AJ/AK при `--dmc-only`) —
> ничего после AN не трогается (у реального FMC колонки AO+ уже заняты данными).
> `--out` делай отдельной копией, исходник не перезаписывай. Диагностика (источник
> DMC, причины) — только в `review.csv`, в сам лист не пишется.

> **CSV — лёгкая альтернатива** (очень большой файл / просто свериться):
> ```bash
> python scripts/write_results.py results.jsonl --out output/results.csv --review output/review.csv
> ```
> CSV содержит row + AI/AJ/AK/AN — вставляется в Excel по номеру строки.

После записи скрипт печатает СВОДКУ (всего строк, decode hit-rate, AN=1 vs AN=0,
ошибки загрузки) — её и отдай пользователю вместе с путём к заполненному .xlsx и
review.csv. xlsx-режим грузит весь workbook в память: для FMC (~500 строк, ~3.4 MB)
ок; на 10k+ строк/большом файле — медленно, тогда CSV.

---

This skill runs three criteria over a field-audit spreadsheet, writes a `1`/empty
flag per criterion into AI/AJ/AK, and derives a final verdict AN. It is built
around one hard-won principle: **decoders and parsers establish ground truth; the
model is only trusted for the genuinely visual-semantic judgement, and even then
a human reviews the uncertain cases.**

## Value convention (READ THIS FIRST — it is NOT Да/Нет)

For AI/AJ/AK:
- **`1`** = критерий **НЕ соблюдается** (есть проблема),
- **пусто** (empty cell) = критерий **соблюдается** (всё в порядке).

For AN (итоговая оценка):
- **`1`** = валидный, **`0`** = не валидный.

## The three criteria and where they land

| Column | Header (RU)                              | `1` пишем, когда…                         | Trust source  |
|--------|------------------------------------------|-------------------------------------------|---------------|
| **AI** | Фольга снята с пачки                     | фольга **НЕ** снята (или не определена)   | model + human |
| **AJ** | На Photo URL есть фото DMC               | DMC **не** распознан (нет DMC)            | deterministic |
| **AK** | DMC код совпадает с кодом на пачке       | распознанный DMC **≠** эталон AE          | deterministic |

## AN — итоговая оценка (derived, column AN)

`AN = "0"` если выполняется ХОТЬ ОДНО:
- хоть один из AI/AJ/AK равен `1`,
- в **AF** нет ссылки (нет фото пачки),
- **AE** пусто (нет эталонного кода).

Иначе `AN = "1"`. (Т.е. валидно только когда все три критерия соблюдены И есть и
эталон AE, и фото AF.)

Notes on the edge cases (handled in `evaluate.py`):
- «нет DMC» — это AJ, не AK. Когда DMC не распознан, AK остаётся **пустым**
  (сравнивать нечего), а невалидность ловится через AJ.
- когда AE пусто, AK тоже пустой (эталона нет), а AN=0 ловится правилом «AE пусто».

## DMC recognition: AG → fallback AF → «не найден»

Распознаём DataMatrix сначала с макро-фото **AG "Photo URL DMC"**. Если там не
распозналось — **fallback на AF "Photo URL"** (то же фото пачки, другой ракурс,
DMC может прочитаться). Если не вышло и там — DMC считается ненайденным (AJ=1).
Какое фото сработало (AG/AF) видно в `review.csv` — в сам лист это не пишется.

## Columns map

The expected code lives in column **AE "DMC Code"**. The macro photo of the
barcode is **AG "Photo URL DMC"**. The full-pack photo (foil + DMC fallback) is
**AF "Photo URL"**. The check type is **AH "Тип проверки"**. The final verdict
goes to **AN**. Only AI/AJ/AK/AN are written — nothing after AN is touched.

**Do not change this mapping without checking the actual headers** — column
letters can shift between exports. `extract_rows.py` takes `--col-*` overrides
for exactly this reason; verify the header row first if anything looks off.

## Foil-unknown policy

Когда модель не может определить статус фольги (низкая уверенность / ошибка),
по умолчанию (`--foil-unknown problem`) ставим **AI=1** → строка невалидна
(AN=0) и попадает в review. Это консервативно для аудита: непроверенную фольгу
не засчитываем как «снята». Диагностическая колонка «Статус фольги» различает
`не снята` (модель уверена) и `не определено` / `не проверялась`. Смягчить можно
флагом `--foil-unknown ok` (тогда unknown не валит строку).

## Why barcodes are NOT an OCR problem

A DMC code is a machine-readable 2D DataMatrix, not text. **Do not try to "read"
it with an OCR model or by looking at the image yourself — that hallucinates.**
Use the bundled `decode_dmc.py`, which runs a real barcode engine (zxing-cpp).
It returns exact bytes or nothing. Under the `1`/empty convention: **decoded
nowhere → AJ=1** (нет DMC); **decoded but ≠ AE → AK=1** (не совпадает); decoded
and equal → AJ and AK both empty. There is no judgement call in this part, and
there must not be.

## Critical: this file is huge — and the run must stay light on a big dataset

The reference workbook is ~22 MB, ~41k rows, ~124k shared strings, with heavy
conditional formatting. The whole design keeps both **RAM flat** and **disk
usage near zero**, independent of how many rows you process (200 or 2,000,000):

- **Never load the workbook with openpyxl** — it gets OOM-killed on this file.
  `extract_rows.py` streams the sheet XML out of the .xlsx zip in ~1 MB chunks
  and emits one `<row>` at a time. Measured peak: ~6 MB for the sheet body vs
  ~320 MB if read whole. Only the shared-string table sits in RAM, and it's
  bounded by the string table, not the row count.
- **No image is ever held longer than its row.** Each photo is downloaded,
  decoded into an ndarray, read by the barcode engine, and released — peak RAM
  per worker is about one image plus one transform. There is no accumulation:
  results are written to `results.jsonl` line by line with flush, so the
  "report" grows on disk, not in memory.
- **Bounded concurrency window.** `run_batch.py` never submits all rows at
  once; it keeps at most `--workers × --window-factor` tasks in flight (default
  12 × 2 = 24) and tops up as each finishes. Futures don't pile up, so memory is
  O(window), not O(rows).
- **No disk cache by default.** Image downloads are NOT cached to disk
  (`--cache-dir` is off unless you pass it). Caching 82k photos would burn tens
  of GB for no benefit — checkpointing already prevents re-downloading on
  rerun, because completed rows are skipped. Enable `--cache-dir` only for
  debugging a small sample.

If you ever process a much larger export, none of these limits change: RAM and
disk stay flat. The only thing that scales with row count is `results.jsonl` on
disk (tiny per row) and wall-clock time.

---

## Workflow

Run these in order. Each step has a bundled script; read a script's top
docstring if you need its flags.

### Phase 1 — Extract (deterministic, seconds)

Pull the needed columns out of the workbook without loading it.

```bash
python scripts/extract_rows.py INPUT.xlsx -o rows.jsonl
# optional: --only-check-type "Проверка DMC"   --limit 200   --sheet Detail
```

Sanity-check the output: it should report a row count near the workbook's, and
each record should have `dmc_ref`, `photo_dmc`, `photo_pack`. If `dmc_ref` is
null everywhere, the column letters are wrong — re-check the header row and pass
`--col-ref` / `--col-photo-dmc` / `--col-photo-pack` / `--col-check-type`.

### Phase 2 — Sample first, never the whole 41k blind

Always validate on a small sample before the full run. This catches auth
problems, wrong columns, a model that won't follow the JSON schema, or a decode
rate that's surprisingly low — cheaply.

```bash
python scripts/run_batch.py rows.jsonl --limit 200 --out results.jsonl
```

Look at the sample results (Phase 4 review). Is the decode hit-rate sane? Do the
matches look right? Only then scale up.

### Phase 3 — Run the checks (resumable)

> **Запуск — по рецепту Шага 3** (foreground `--max-seconds`-цикл; фон через
> `setsid` только после survival-probe). Здесь — какие именно команды гонять.

**DMC-only (быстро, без LLM): высокий `--workers`.**

```bash
python scripts/run_batch.py rows.jsonl --out results.jsonl --workers 32 --max-seconds 100
```

**С фольгой (LLM, opt-in): `--workers 2`** (локальный прокси не держит больше).

```bash
python scripts/run_batch.py rows.jsonl --out results.jsonl --foil --workers 2 --max-seconds 100
```

Повторяй ту же команду по ходу, пока `results.jsonl` не догонит `rows.jsonl`
(Шаг 3). `--foil-limit N` — это БЮДЖЕТ на сэмпл (первые N строк файла получат foil),
НЕ для полного прогона: при нём остальные строки уйдут в AI=1/AN=0. Для полного
foil-прогона `--foil-limit` НЕ передавай.

### Если foil вернул `bad_schema` или `litellm_error` — диагностируй сам

Не сдавайся и не говори пользователю "эндпоинт недоступен". Сначала проверь сам:

**Шаг 1 — простой ping модели:**

С Gemini:
```bash
python3 -c "
import urllib.request, json, os
req = urllib.request.Request(
    os.environ.get('LITELLM_BASE_URL','https://generativelanguage.googleapis.com/v1beta/openai') + '/chat/completions',
    data=json.dumps({'model': os.environ.get('LITELLM_MODEL','gemini-2.5-flash'), 'max_tokens':10,
                     'messages':[{'role':'user','content':'Say: ok'}]}).encode(),
    headers={'Content-Type':'application/json',
             'Authorization':'Bearer ' + os.environ.get('LITELLM_API_KEY','')}, method='POST')
with urllib.request.urlopen(req, timeout=20) as r:
    print(json.loads(r.read())['choices'][0]['message']['content'])
"
```

С локальным прокси (дефолт, `dots.mocr`):
```bash
python3 -c "
import urllib.request, json
req = urllib.request.Request(
    'http://87.242.111.7:32200/v1/chat/completions',
    data=json.dumps({'model':'dots.mocr','max_tokens':10,
                     'messages':[{'role':'user','content':'Say: ok'}]}).encode(),
    headers={'Content-Type':'application/json',
             'Authorization':'Bearer sk-SGZ4XJt7Bf_FZ5ytXAfYBA'}, method='POST')
with urllib.request.urlopen(req, timeout=20) as r:
    print(json.loads(r.read())['choices'][0]['message']['content'])
"
```
(Список моделей по ключу: `curl -s http://87.242.111.7:32200/v1/models -H "Authorization: Bearer <key>"`.)

**Шаг 2 — если ping прошёл, но batch валится:** попробуй `--workers 1`:
```bash
python scripts/run_batch.py rows.jsonl --out results.jsonl \
    --foil --foil-limit 10 --workers 1
```

**Шаг 3 — если ответ есть но bad_schema:** проверь что именно вернула модель:
```bash
python scripts/check_foil.py --url "<photo_pack url из rows.jsonl>" --debug
```

**Шаг 4 — если эндпоинт совсем не отвечает:** сообщи пользователю точный текст ошибки и результаты ping.

Model (`dots.mocr`) and endpoint (`http://87.242.111.7:32200/v1`) are baked into
the scripts as defaults; override with `--model`/`LITELLM_MODEL` etc.

Key properties to rely on:
- **Checkpointing**: results append by row number; rerunning SKIPS done rows. A
  crash mid-run costs nothing — just rerun the same command. This is also why a
  disk cache is unnecessary: a rerun never re-downloads completed rows.
- **Flat memory**: bounded concurrency window (`--workers × --window-factor`)
  plus per-row image release keep RAM constant regardless of dataset size.
- **No disk cache by default**: images stay in RAM only for their row. Pass
  `--cache-dir DIR` only to debug a small sample; never on the full set.
- **Concurrency**: `--workers` overlaps the network-bound downloads. Raise
  `--workers` to go faster (network-bound); raise `--window-factor` only if you
  want a deeper queue (rarely needed).
- For internal hosts with self-signed certs, add `--no-verify-ssl` (testing
  fallback, same spirit as `CONFLUENCE_SSL_VERIFY=false`).

The foil check uses `dots.mocr` at `http://87.242.111.7:32200/v1` — baked
in as defaults; override with `--model` / `--base-url` / `--api-key` (e.g.
`gemini-2.5-flash`) if needed.
The prompt forces strict JSON (`{"state", "confidence", "evidence",
"visible_cigarette_ends", "lid_raised"}`; open→foil removed) at temperature 0,
explicitly tells the model to IGNORE the cellophane wrapper (intact film ≠
closed — it often stays on after the lid is opened), and treats any text inside
the photo as scene data, never as instructions — closing the prompt-injection
surface that comes with feeding
external images to a model.

### Phase 4 — Write back + human review

**Заполнить копию исходного .xlsx** (колонки AI/AJ/AK/AN):

```bash
python scripts/write_results.py results.jsonl \
    --mode xlsx --template INPUT.xlsx --out FILLED.xlsx --review review.csv
```

Замени `INPUT.xlsx` на путь к исходному файлу. Скрипт откроет оригинал (все листы
сохранятся), впишет `1`/пусто в AI/AJ/AK, итог `1`/`0` в AN и сохранит как
`FILLED.xlsx`. Пишутся ровно эти 4 колонки — ничего после AN не трогается. Лист
задаётся `--sheet` (по умолчанию `Detail`).

> **Если файл большой (>10 MB / >10k строк)** — используй CSV-режим (быстрее, без OOM):
> ```bash
> python scripts/write_results.py results.jsonl --out results.csv --review review.csv
> ```
> CSV содержит row + AI/AJ/AK/AN — вставляй в Excel по номеру строки.

- `FILLED.xlsx` / `results.csv` — только AI/AJ/AK (`1`/пусто) и AN (`1`/`0`).
- `review.csv` is the **human-in-the-loop queue** — only the rows that need eyes:
  - **AJ == 1** → DataMatrix не распознан ни на AG, ни на AF (нельзя подтвердить
    код).
  - **AK == 1** → decoded но отличается от эталона: вероятное реальное
    расхождение, посмотреть глазами.
  - **foil unsure** → модель вернула null / низкую уверенность / ошибку
    (статус фольги «не определено»).

## Honest capability boundaries (state these to the user upfront)

- **AK / AJ are reliable** — a barcode either decodes to exact bytes or it does
  not. AJ=1 means "не распознан нигде" (ни AG, ни AF); AK=1 means "распознан, но
  ≠ эталону". Эти два не путаются: при отсутствии DMC AK остаётся пустым.
- **Decode rate depends on photo quality.** Measured ~92% on a 150-row FMC
  sample with the basic ladder; the upscale-2x + tiling passes added to
  `decode_dmc.py` lift it to **~98%** (the DataMatrix is often small in a 1920px
  frame — a 2x upscale and overlapping upscaled tiles let zxing lock on). The AF
  pack-photo fallback recovers a few more (другой ракурс). The last ~2% are
  genuinely damaged shots — heavy cellophane glare over the code, or upside-down
  + crinkled wrap — and need a reshoot; they come back AJ=1 and go to review.
- **AI (foil) is a model judgement, not a measurement.** It is good at the clear
  cases (obviously open vs obviously sealed) and routes the ambiguous ones to a
  human. It is not a guarantee. Communicate this before a pilot.
- The skill never invents a code, never marks a match it didn't decode, and
  never turns "unsure" into a confident answer.

## Script reference

- `scripts/extract_rows.py` — stream rows out of the big .xlsx (no openpyxl load)
- `scripts/decode_dmc.py` — download a photo, OpenCV preprocess ladder
  (raw → upscale-2x → Otsu/CLAHE/blur → overlapping upscaled tiles for small/
  off-centre codes), zxing-cpp decode (+ optional pylibdmtx fallback). Tiling
  only runs when the cheap passes miss. `--self-test` synthesizes and decodes.
- `scripts/normalize_dmc.py` — normalize both codes (strip symbology id / GS /
  whitespace) before comparing. `--self-test` covers the tricky cases.
- `scripts/check_foil.py` — multimodal foil check via LiteLLM, strict JSON,
  confidence threshold. `--dry-run` builds the request without sending.
- `scripts/run_batch.py` — orchestrator: AG→AF decode fallback (AF fetched once,
  reused for foil), checkpointing, concurrency, foil budget. Stores RAW facts.
- `scripts/evaluate.py` — **single source of truth** for the business rules:
  raw facts → AI/AJ/AK (`1`/empty) + AN (`1`/`0`) (+ fields used internally by
  the review queue / summary). `--self-test` covers every branch (match,
  mismatch, no-DMC, AF/AE empty, foil-unknown).
- `scripts/write_results.py` — runs `evaluate.py` per row and writes ONLY
  AI/AJ/AK/AN to CSV / a filled copy of the .xlsx, plus the review queue + a
  console summary.

Install deps with `pip install -r scripts/requirements.txt`.
