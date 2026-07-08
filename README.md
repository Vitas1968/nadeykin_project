# Tender Assistant Skill

## 1.1. Что это за проект

`tender-assistant-skill` анализирует документы тендера и помогает быстро понять, подходит ли тендер для участия, можно ли передать его дилеру или нужно проверить спорные места вручную.

Проект не заменяет юриста, менеджера или специалиста по закупкам. Он делает первичную машинную проверку: ищет важные фрагменты в документах, проверяет правила, оценивает риски и готовит короткую сводку.

Ключевой принцип: каждый вывод должен быть связан с `evidence` — найденным фрагментом документа, на основании которого правило делает вывод.

## 1.2. Что подаётся на вход

На вход подаётся файл или папка с тендерными документами через параметр `--input`.

Поддерживаемые форматы документов:

- `.docx`;
- `.html`;
- `.htm`;
- `.xlsx`;
- `.pdf`.

`.sign`-файлы не анализируются как содержательные документы. Если при чтении папки встречается неподдерживаемое расширение, файл попадает в `skipped_files`.

Дополнительно последовательность обработки, или `pipeline`, использует:

- `criteria.yaml` — файл критериев, то есть список правил проверки;
- DOCX-шаблон сводки, если нужна Word-сводка.

Если `--criteria` не указан, используется `tender-assistant-skill/config/criteria.yaml`. Если `--docx-template` не указан, используется `sources_info/Шаблон сводки по тендеру v2.docx`.

## 1.3. Что получается на выходе

`run.py` создаёт папку, указанную через `--out`, и пишет туда результат анализа:

- `tender_score.json` — машинно-читаемый результат проверки: правила, статусы, риски, найденные `evidence` и итоговый сценарий;
- `tender_summary.md` — краткая сводка по тендеру для чтения человеком;
- `questions_for_customer.md` — вопросы, которые нужно уточнить у заказчика или проверить вручную;
- `tender_summary.docx` — Word-сводка, если запускать без `--no-docx`.

Если запуск выполнен с `--no-docx`, файл `tender_summary.docx` не создаётся, остальные выходные файлы формируются как обычно.

## 1.4. Как работает анализ

Цепочка анализа выглядит так:

```text
документы
    ↓
поиск фрагментов
    ↓
проверка правил
    ↓
итоговый сценарий
    ↓
отчёты
```

По фактическому коду pipeline делает следующее:

1. Читает один файл или папку с тендерными документами.
2. Извлекает текстовые блоки и таблицы.
3. Нормализует данные в общий JSON-подобный формат.
4. Ищет `evidence` по критериям через keyword search — поиск по ключевым словам.
5. Проверяет правила через `rule_engine`.
6. Выбирает итоговый сценарий через `scenario_classifier`.
7. Создаёт выходные файлы в папке `--out`.

**deterministic layer** — основной слой правил, то есть обычный код без нейросети. Именно он остаётся источником итогового решения.

## 1.5. Что такое итоговые сценарии

`scenario_result` — итоговый сценарий по тендеру. Он показывает, что делать с тендером дальше:

- `relevant_dealer` — тендер подходит, можно передать дилеру или партнёру;
- `relevant_direct` — тендер подходит для прямого участия;
- `need_human_review` — нужна ручная проверка;
- `not_relevant` — тендер не подходит.

`run.py` записывает `scenario_result` в `tender_score.json`, а `summary_writer.py` показывает его в `tender_summary.md`.

## 1.6. Что такое правило

`rule` — отдельное правило проверки. Например:

- товар это или услуга;
- какой указан способ закупки;
- есть ли ограничение для МСП;
- требуется ли обеспечение заявки или договора.

У каждого правила есть результат, риск, пояснение и найденные фрагменты документа.

## 1.7. Как читать `status`, `risk` и `human_review_required`

`status` — результат правила:

- `status=pass` — правило пройдено;
- `status=fail` — правило не пройдено;
- `status=unknown` — данных недостаточно;
- `status=conflict` — найдены противоречивые данные.

`risk` — уровень риска:

- `risk=low` — низкий риск;
- `risk=medium` — средний риск;
- `risk=high` — высокий риск.

`human_review_required` — флаг «нужна ручная проверка»:

- `human_review_required=true` — нужно смотреть человеку;
- `human_review_required=false` — ручная проверка по этому правилу не требуется.

Если данных мало, есть противоречия или риск высокий, результат должен вести к ручной проверке, а не к уверенной автоматической рекомендации.

## 1.8. LLM selective shadow runtime

LLM — локальная языковая модель, то есть нейросеть, которая может прочитать короткий фрагмент текста и дать своё мнение по конкретному правилу.

В текущем MVP LLM подключена как **shadow mode** — теневой режим, когда модель проверяет результат, но не управляет решением. Она не принимает итоговое бизнес-решение, не меняет `status`, `risk`, `human_review_required`, `comment` и `scenario_result`.

LLM добавляет только `llm_verdict`. `llm_verdict` — мнение LLM по конкретному правилу: вызывалась ли модель, что она сказала, уверена ли она и конфликтует ли её мнение с обычным правилом.

**selective shadow** означает, что LLM вызывается только там, где это полезно. Если обычный код уже уверенно оценил правило как `pass / low / human_review_required=false`, LLM не вызывается.

**guardrail** — защитное правило, которое не даёт LLM гадать по слабым данным. Если `evidence` слишком слабый или в нём нет явной фразы, такой фрагмент не отправляется в модель.

Рабочая demo-модель для selective mode:

```text
qwen2.5:14b
```

Короткий пример env:

```env
TENDER_LLM_ENABLED=true
TENDER_LLM_SELECTIVE_ENABLED=true
TENDER_LLM_RUN_ON_PASS=false
TENDER_LLM_MODEL=qwen2.5:14b
```

Подробная архитектура: `tender-assistant-skill/docs/selective_shadow_architecture.md`

Контракт `llm_verdict`: `tender-assistant-skill/docs/llm_verdict_contract.md`

## 1.9. Как запускать тесты

Перед тестами нужно очистить `TENDER_LLM*` переменные окружения. Demo-env может влиять на mock-тесты, поэтому тесты запускаются в чистом окружении без LLM-настроек.

```powershell
Get-ChildItem Env:TENDER_LLM* | ForEach-Object {
  Remove-Item "Env:\$($_.Name)"
}

$env:PYTHONDONTWRITEBYTECODE="1"
.\.venv\Scripts\python.exe -m pytest tender-assistant-skill/tests -q -p no:cacheprovider
Remove-Item Env:\PYTHONDONTWRITEBYTECODE
```

## 1.10. Где смотреть конфигурацию

Основные примеры конфигурации:

- `.env.example`;
- `tender-assistant-skill/.env.example`.

Оба файла описывают demo-конфигурацию selective shadow mode через локальный Ollama endpoint и OpenAI-compatible API формат. Ollama endpoint — это локальный адрес сервера модели, а OpenAI-compatible API — формат запросов, совместимый с API OpenAI.

## Дополнительная техническая справка

### 1. Назначение

`tender-assistant-skill` делает первичную deterministic-оценку тендерных документов.

Цель текущего MVP:

- найти подтверждения по критериям из `criteria.yaml`;
- оценить риски и статусы критериев;
- сформировать итоговый сценарий обработки тендера;
- подготовить краткую сводку, DOCX-сводку и вопросы для человека / заказчика.

Каждый вывод должен опираться на найденное `evidence`. Результат pipeline не является финальным юридическим или коммерческим решением: это предварительная машинная проверка для последующей оценки человеком.

### 2. Что делает pipeline

По фактическому коду pipeline выполняет следующие шаги:

1. Читает один файл или папку с документами тендера.
2. Извлекает текстовые блоки и таблицы из поддерживаемых форматов.
3. Нормализует документы в общий JSON-подобный формат с `documents`, `blocks`, `full_text`, `stats`, `skipped_files` и `failed_files`.
4. Ищет `evidence` по критериям через keyword search.
5. Оценивает критерии через `rule_engine`.
6. Классифицирует итоговый сценарий через `scenario_classifier`.
7. Пишет выходные файлы в указанную папку.
8. Формирует DOCX-сводку по шаблону, если DOCX-выгрузка не отключена через `--no-docx`.

Поддерживаемые форматы входных документов: `.docx`, `.html`, `.htm`, `.xlsx`, `.pdf`. При чтении папки неподдерживаемые расширения попадают в `skipped_files` с причиной `unsupported_extension`. `.sign`-файлы не анализируются как содержательные тендерные документы в рамках текущего MVP.

### 3. Основные входы

Основные входы:

- папка или файл с документами тендера, передаётся через `--input`;
- файл критериев, передаётся через `--criteria`;
- DOCX-шаблон сводки, передаётся через `--docx-template`.

Если `--criteria` не указан, `run.py` использует default:

`tender-assistant-skill/config/criteria.yaml`

Если `--docx-template` не указан, `run.py` использует default:

`sources_info/Шаблон сводки по тендеру v2.docx`

Default DOCX-шаблон резолвится относительно корня репозитория, а не только относительно текущей рабочей директории. Для явного относительного `--docx-template` pipeline сначала проверяет путь относительно текущей рабочей директории, затем относительно корня репозитория.

### 4. Основные выходы

`run.py` создаёт указанную через `--out` папку и пишет в неё:

- `tender_score.json` — полный результат scoring, включая правила, статистику и `scenario_result`;
- `questions_for_customer.md` — вопросы по критериям, которые требуют ручной проверки или уточнения;
- `tender_summary.md` — краткая markdown-сводка по тендеру, включая итоговый сценарий, статистику, критерии внимания и найденное `evidence`;
- `tender_summary.docx` — DOCX-сводка по шаблону `sources_info/Шаблон сводки по тендеру v2.docx`.

Если запуск выполнен с флагом `--no-docx`, файл `tender_summary.docx` не создаётся, остальные выходные файлы формируются как обычно.

### 5. Итоговые сценарии

Фактический набор сценариев из `scenario_classifier.py`:

- `not_relevant` — нерелевантный тендер;
- `relevant_direct` — релевантен для прямой обработки;
- `relevant_dealer` — релевантен для дилера / партнёра;
- `need_human_review` — требуется ручная проверка.

`run.py` записывает результат `classify_scenario()` в поле `scenario_result` внутри `tender_score.json`. `summary_writer.py` отображает `scenario_result` в разделе `## 2. Итоговый сценарий` файла `tender_summary.md`. DOCX-exporter использует тот же `result` уже после добавления `scenario_result`.

### 6. Быстрый запуск pipeline

Команды ниже приведены для Windows PowerShell. На Linux/macOS используйте `python` или `./.venv/bin/python` вместо `.\.venv\Scripts\python.exe`.

Пример обычного запуска:

```powershell
.\.venv\Scripts\python.exe tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/tender_1" --top-k 5 --min-score 0
```

В обычном режиме в output-папке будут созданы:

- `tender_score.json`;
- `questions_for_customer.md`;
- `tender_summary.md`;
- `tender_summary.docx`.

Пример запуска с явным DOCX-шаблоном:

```powershell
.\.venv\Scripts\python.exe tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/tender_1" --top-k 5 --min-score 0 --docx-template "sources_info/Шаблон сводки по тендеру v2.docx"
```

Пример запуска без DOCX-выгрузки:

```powershell
.\.venv\Scripts\python.exe tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/tender_1_no_docx" --top-k 5 --min-score 0 --no-docx
```

Параметры `run.py`:

- `--input` — обязательный путь к файлу или папке с документами тендера;
- `--out` — обязательный путь к папке для выходных файлов;
- `--criteria` — путь к YAML/JSON-файлу критериев, default: `tender-assistant-skill/config/criteria.yaml`;
- `--top-k` — максимальное число найденных фрагментов на критерий, default: `5`;
- `--min-score` — минимальный score для найденного фрагмента, default: `0.0`;
- `--docx-template` — путь к DOCX-шаблону сводки, default: `sources_info/Шаблон сводки по тендеру v2.docx`;
- `--no-docx` — отключает DOCX-выгрузку. Если одновременно указан `--docx-template`, флаг `--no-docx` имеет приоритет, а template path игнорируется.

### 7. LLM selective shadow runtime

LLM runtime уже подключён как advisory/shadow layer — вспомогательный теневой слой. Он не заменяет `keyword_search`, `rule_engine` и `scenario_classifier`.

LLM получает на вход один критерий и короткий список найденных `evidence`. Ответ хранится только в `rule["llm_verdict"]`.

LLM не анализирует весь тендер целиком и не принимает итоговое решение об участии. Итоговое решение принимает deterministic pipeline: `rule_engine` + `scenario_classifier`.

LLM-result не меняет deterministic rule status и не влияет на `scenario_result`.

Подробный контракт описан в `tender-assistant-skill/docs/llm_verdict_contract.md`.

Demo provider: Ollama.

Demo model для selective mode: `qwen2.5:14b`.

Base URL: `http://localhost:11434/v1`.

API format: OpenAI-compatible.

### 8. DOCX-выгрузка

DOCX-сводка формируется модулем:

`tender-assistant-skill/src/output/docx_summary_writer.py`

Exporter работает без `python-docx` и без новых зависимостей: он обрабатывает DOCX как ZIP-архив и заменяет machine-readable placeholders в `word/document.xml`.

Основной шаблон:

`sources_info/Шаблон сводки по тендеру v2.docx`

Контракт placeholders описан в:

`tender-assistant-skill/docs/docx_template_placeholders.md`

DOCX-exporter:

- получает тот же `result`, который пишется в `tender_score.json`;
- использует `scenario_result`, добавленный в `run.py`;
- валидирует наличие placeholders;
- использует fallback-значения для отсутствующих данных;
- экранирует XML-текст;
- проверяет, что output DOCX создан, содержит `word/document.xml` и не содержит незаменённых placeholders.

На уровне `run.py` дополнительно проверяется, что `tender_summary.docx` существует и имеет размер больше `0`.

### 9. Regression check

Команда ниже приведена для Windows PowerShell. На Linux/macOS используйте `python` или `./.venv/bin/python` вместо `.\.venv\Scripts\python.exe`.

Команда запуска:

```powershell
.\.venv\Scripts\python.exe tender-assistant-skill/scripts/regression_check.py
```

`regression_check.py` по фактическому коду проверяет:

- окружение, текущую ветку, начальный `git status --short` и правила `.gitignore` для `outputs`, `outputs/debug`, `__pycache__`, `.pyc`;
- syntax check через чтение исходников как UTF-8 и `compile(..., "exec")` без создания `.pyc`;
- runtime imports для `classify_scenario` и `render_summary`;
- запуск `run.py --help`;
- `summary_writer.py` на artificial JSON с полным `scenario_result`, без `scenario_result` и с partial `scenario_result`;
- реальные тендеры из `sources_info/Тендер 1`, `sources_info/Тендер 2`, `sources_info/Тендер 3`, если эти папки доступны;
- создание `tender_score.json`, `tender_summary.md`, `questions_for_customer.md`, `tender_summary.docx` для реальных тендеров;
- что `tender_summary.docx` существует и имеет размер больше `0`;
- stdout marker обычного DOCX-export: `DOCX summary written to:`;
- отдельный `--no-docx` check: старые outputs создаются, `tender_summary.docx` не создаётся, stdout содержит `DOCX export disabled by --no-docx`;
- наличие валидного `scenario_result` в `tender_score.json`;
- наличие разделов итогового сценария и краткой статистики в `tender_summary.md`;
- соответствие snapshot-сценариям для тестовых тендеров;
- очистку временных файлов и результатов проверки;
- отсутствие `outputs/debug`, `__pycache__` и `.pyc` в `git status --short`;
- отсутствие diff в production-файлах, которые перечислены внутри `regression_check.py`.

`regression_check.py` нужно запускать перед изменениями pipeline и после них.

- exit code `0` означает успешную проверку;
- exit code `1` означает ошибку.

### 10. Snapshot-сценарии для тестовых тендеров

Фактические expected scenarios из `regression_check.py`:

- `Тендер 1` -> `relevant_dealer`;
- `Тендер 2` -> `relevant_dealer`;
- `Тендер 3` -> `need_human_review`.

Эти значения являются regression snapshots для текущих тестовых данных. Если бизнес-логика scoring меняется намеренно, expected-сценарии в `regression_check.py` нужно обновлять осознанно.

### 11. Ограничения текущего MVP

- Deterministic pipeline остаётся источником итогового решения.
- LLM-слой подключён только как advisory/shadow layer и пишет `rule["llm_verdict"]`.
- Выводы зависят от `criteria.yaml` и найденных `evidence`.
- DOCX-выгрузка использует заранее подготовленный шаблон v2 с machine-readable placeholders.
- Regression поверхностно проверяет DOCX-output через `exists`, `size > 0` и stdout marker; глубокая DOCX-валидация выполняется внутри `docx_summary_writer.py`.
- Спорные, противоречивые или неполные случаи должны уходить в `need_human_review` или в вопросы человеку.
- Результат не является финальным решением без проверки человеком.

### 12. Рекомендуемый порядок работы разработчика

Команды ниже приведены для Windows PowerShell. На Linux/macOS используйте `python` или `./.venv/bin/python` вместо `.\.venv\Scripts\python.exe`.

1. Перед изменениями:

```powershell
.\.venv\Scripts\python.exe tender-assistant-skill/scripts/regression_check.py
```

2. Внести изменения.

3. После изменений:

```powershell
.\.venv\Scripts\python.exe tender-assistant-skill/scripts/regression_check.py
```

4. Проверить diff и status:

```bash
git diff
git status --short
```

### 13. Следующие планируемые шаги

- Улучшение качества `evidence`.
- Расширение критериев.
- Улучшение вопросов для заказчика.
- Улучшение DOCX-шаблона и покрытия DOCX-выгрузки.
