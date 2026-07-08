# Tender Assistant Skill

## Назначение

Этот skill анализирует документы тендера и формирует предварительную машинную оценку:

- подходит ли тендер для участия;
- нужен ли ручной просмотр;
- какие критерии подтверждены;
- какие риски или блокирующие признаки найдены;
- какие вопросы нужно уточнить у заказчика.

Skill не заменяет юриста, менеджера по закупкам или коммерческое решение. Он делает первичный анализ документов и готовит структурированный результат для дальнейшей проверки человеком.

## Требования к среде

Для запуска skill среда должна иметь:

- Python 3.12+ или совместимый Python;
- зависимости из `requirements.txt`;
- доступный запуск Python-кода;
- при использовании LLM shadow: Ollama;
- установленную модель `qwen2.5:14b`;
- доступ к `http://localhost:11434/v1`.

Если Ollama или `qwen2.5:14b` недоступны, LLM shadow не сможет работать.

Если сценарий запуска требует обязательный LLM shadow, отсутствие Ollama, модели `qwen2.5:14b` или доступа к `http://localhost:11434/v1` нужно считать блокирующей ошибкой среды.

## Входные данные

На вход подаётся папка с тендерными документами или отдельный файл.

Поддерживаемые форматы:

- `.docx`;
- `.xlsx`;
- `.pdf`;
- `.html`;
- `.htm`.

Файлы `.sign` не анализируются как содержательные документы.

## Установка зависимостей

Если skill распакован как самостоятельная папка, из корня skill-папки выполнить:

```powershell
python -m pip install -r requirements.txt
```

Если skill находится внутри репозитория, можно использовать корневой `requirements.txt` репозитория.

## Запуск без LLM shadow

Из корня skill-папки:

```powershell
$env:PYTHONPATH="src"
python run.py --input "<папка_с_тендером>" --out "<папка_результата>"
```

Запуск без DOCX-выгрузки:

```powershell
$env:PYTHONPATH="src"
python run.py --input "<папка_с_тендером>" --out "<папка_результата>" --no-docx
```

## Запуск с LLM shadow

Перед запуском должны быть доступны Ollama, модель `qwen2.5:14b` и endpoint `http://localhost:11434/v1`.

Пример переменных окружения PowerShell:

```powershell
$env:TENDER_LLM_ENABLED="true"
$env:TENDER_LLM_SELECTIVE_ENABLED="true"
$env:TENDER_LLM_RUN_ON_PASS="false"
$env:TENDER_LLM_PROVIDER="ollama"
$env:TENDER_LLM_BASE_URL="http://localhost:11434/v1"
$env:TENDER_LLM_MODEL="qwen2.5:14b"
$env:TENDER_LLM_API_KEY="ollama"
$env:TENDER_LLM_TIMEOUT_SECONDS="180"
$env:TENDER_LLM_MAX_TOKENS="192"
$env:TENDER_LLM_MAX_EVIDENCE_ITEMS="1"
$env:TENDER_LLM_MAX_EVIDENCE_CHARS="600"
$env:PYTHONPATH="src"
```

Запуск:

```powershell
python run.py --input "<папка_с_тендером>" --out "<папка_результата>"
```

## Результаты работы

Skill создаёт в папке результата:

- `tender_score.json` — полный технический результат проверки;
- `tender_summary.md` — краткая сводка для человека;
- `questions_for_customer.md` — вопросы к заказчику или для ручной проверки;
- `tender_summary.docx` — Word-сводка, если DOCX-выгрузка включена и шаблон доступен.

Сначала читать `tender_summary.md`, затем `questions_for_customer.md`. Файл `tender_score.json` нужен для технической проверки и интеграции.

## Итоговые сценарии

`scenario_result` — итоговый сценарий по тендеру:

- `relevant_dealer` — тендер подходит, но его лучше передать дилеру или партнёру;
- `relevant_direct` — тендер подходит для прямого участия;
- `need_human_review` — нужна ручная проверка;
- `not_relevant` — тендер не подходит.

## Как читать правила

Каждое правило содержит:

- `status` — результат правила:
  - `pass` — правило пройдено;
  - `fail` — правило не пройдено;
  - `unknown` — данных недостаточно;
  - `conflict` — найдены противоречивые данные;
- `risk` — уровень риска: `low`, `medium`, `high`;
- `human_review_required` — нужна ли ручная проверка;
- `comment` — пояснение;
- `evidence` — найденные фрагменты документов, на которых основан вывод.

## Роль LLM shadow

LLM shadow — это теневой режим проверки языковой моделью. LLM может дать дополнительное мнение по конкретному правилу, но не принимает итоговое решение.

LLM не меняет:

- `status`;
- `risk`;
- `human_review_required`;
- `comment`;
- `scenario_result`.

LLM добавляет только:

```json
"llm_verdict": {}
```

Итоговое решение принимает deterministic pipeline, то есть основной слой обычных правил без нейросети:

- `rule_engine`;
- `scenario_classifier`.

## Что возвращать пользователю после анализа

После запуска skill нужно вернуть пользователю:

1. итоговый сценарий;
2. краткую рекомендацию;
3. нужна ли ручная проверка;
4. блокирующие критерии, если они есть;
5. основные причины решения;
6. вопросы из `questions_for_customer.md`;
7. путь к `tender_summary.md`;
8. путь к `questions_for_customer.md`;
9. путь к `tender_score.json`.

Не выдавать `llm_verdict` как финальное решение. Если `llm_verdict` конфликтует с deterministic-правилом, указать это как диагностический конфликт, но не менять итоговый сценарий.
