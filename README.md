# Tender Assistant Skill

## 1. Назначение

`tender-assistant-skill` делает первичную deterministic-оценку тендерных документов.

Цель текущего MVP:

- найти подтверждения по критериям из `criteria.yaml`;
- оценить риски и статусы критериев;
- сформировать итоговый сценарий обработки тендера;
- подготовить краткую сводку, DOCX-сводку и вопросы для человека / заказчика.

Каждый вывод должен опираться на найденное `evidence`. Результат pipeline не является финальным юридическим или коммерческим решением: это предварительная машинная проверка для последующей оценки человеком.

## 2. Что делает pipeline

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

## 3. Основные входы

Основные входы:

- папка или файл с документами тендера, передаётся через `--input`;
- файл критериев, передаётся через `--criteria`;
- DOCX-шаблон сводки, передаётся через `--docx-template`.

Если `--criteria` не указан, `run.py` использует default:

`tender-assistant-skill/config/criteria.yaml`

Если `--docx-template` не указан, `run.py` использует default:

`sources_info/Шаблон сводки по тендеру v2.docx`

Default DOCX-шаблон резолвится относительно корня репозитория, а не только относительно текущей рабочей директории. Для явного относительного `--docx-template` pipeline сначала проверяет путь относительно текущей рабочей директории, затем относительно корня репозитория.

## 4. Основные выходы

`run.py` создаёт указанную через `--out` папку и пишет в неё:

- `tender_score.json` — полный результат scoring, включая правила, статистику и `scenario_result`;
- `questions_for_customer.md` — вопросы по критериям, которые требуют ручной проверки или уточнения;
- `tender_summary.md` — краткая markdown-сводка по тендеру, включая итоговый сценарий, статистику, критерии внимания и найденное `evidence`;
- `tender_summary.docx` — DOCX-сводка по шаблону `sources_info/Шаблон сводки по тендеру v2.docx`.

Если запуск выполнен с флагом `--no-docx`, файл `tender_summary.docx` не создаётся, остальные выходные файлы формируются как обычно.

## 5. Итоговые сценарии

Фактический набор сценариев из `scenario_classifier.py`:

- `not_relevant` — нерелевантный тендер;
- `relevant_direct` — релевантен для прямой обработки;
- `relevant_dealer` — релевантен для дилера / партнёра;
- `need_human_review` — требуется ручная проверка.

`run.py` записывает результат `classify_scenario()` в поле `scenario_result` внутри `tender_score.json`. `summary_writer.py` отображает `scenario_result` в разделе `## 2. Итоговый сценарий` файла `tender_summary.md`. DOCX-exporter использует тот же `result` уже после добавления `scenario_result`.

## 6. Быстрый запуск pipeline

Пример обычного запуска:

```bash
python tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/tender_1" --top-k 5 --min-score 0
```

В обычном режиме в output-папке будут созданы:

- `tender_score.json`;
- `questions_for_customer.md`;
- `tender_summary.md`;
- `tender_summary.docx`.

Пример запуска с явным DOCX-шаблоном:

```bash
python tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/tender_1" --top-k 5 --min-score 0 --docx-template "sources_info/Шаблон сводки по тендеру v2.docx"
```

Пример запуска без DOCX-выгрузки:

```bash
python tender-assistant-skill/run.py --input "sources_info/Тендер 1" --out "outputs/debug/tender_1_no_docx" --top-k 5 --min-score 0 --no-docx
```

Параметры `run.py`:

- `--input` — обязательный путь к файлу или папке с документами тендера;
- `--out` — обязательный путь к папке для выходных файлов;
- `--criteria` — путь к YAML/JSON-файлу критериев, default: `tender-assistant-skill/config/criteria.yaml`;
- `--top-k` — максимальное число найденных фрагментов на критерий, default: `5`;
- `--min-score` — минимальный score для найденного фрагмента, default: `0.0`;
- `--docx-template` — путь к DOCX-шаблону сводки, default: `sources_info/Шаблон сводки по тендеру v2.docx`;
- `--no-docx` — отключает DOCX-выгрузку. Если одновременно указан `--docx-template`, флаг `--no-docx` имеет приоритет, а template path игнорируется.

## 7. DOCX-выгрузка

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

## 8. Regression check

Команда запуска:

```bash
python tender-assistant-skill/scripts/regression_check.py
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

## 9. Snapshot-сценарии для тестовых тендеров

Фактические expected scenarios из `regression_check.py`:

- `Тендер 1` -> `relevant_dealer`;
- `Тендер 2` -> `relevant_dealer`;
- `Тендер 3` -> `need_human_review`.

Эти значения являются regression snapshots для текущих тестовых данных. Если бизнес-логика scoring меняется намеренно, expected-сценарии в `regression_check.py` нужно обновлять осознанно.

## 10. Ограничения текущего MVP

- Pipeline работает как deterministic-only MVP.
- LLM-слой в текущий pipeline не добавлен.
- Выводы зависят от `criteria.yaml` и найденных `evidence`.
- DOCX-выгрузка использует заранее подготовленный шаблон v2 с machine-readable placeholders.
- Regression поверхностно проверяет DOCX-output через `exists`, `size > 0` и stdout marker; глубокая DOCX-валидация выполняется внутри `docx_summary_writer.py`.
- Спорные, противоречивые или неполные случаи должны уходить в `need_human_review` или в вопросы человеку.
- Результат не является финальным решением без проверки человеком.

## 11. Рекомендуемый порядок работы разработчика

1. Перед изменениями:

```bash
python tender-assistant-skill/scripts/regression_check.py
```

2. Внести изменения.

3. После изменений:

```bash
python tender-assistant-skill/scripts/regression_check.py
```

4. Проверить diff и status:

```bash
git diff
git status --short
```

## 12. Следующие планируемые шаги

- Улучшение качества `evidence`.
- Расширение критериев.
- Улучшение вопросов для заказчика.
- Улучшение DOCX-шаблона и покрытия DOCX-выгрузки.
