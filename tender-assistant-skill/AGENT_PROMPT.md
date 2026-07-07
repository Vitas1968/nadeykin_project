# Agent prompt для Tender Assistant Skill

Используй skill `tender-assistant-skill` для анализа тендерных документов.

## Основной порядок работы

Когда пользователь передаёт папку или набор файлов тендера:

1. Не пытайся вручную пересказывать весь тендер.
2. Сначала запусти анализ через `run.py`.
3. После запуска прочитай:
   - `tender_score.json`;
   - `tender_summary.md`;
   - `questions_for_customer.md`.
4. На основе этих файлов дай пользователю краткий итог.

## Требования к среде

Для запуска skill среда должна иметь:

- Python 3.12+ или совместимый Python;
- зависимости из `requirements.txt`;
- доступный запуск Python-кода;
- при использовании LLM shadow: Ollama;
- установленную модель `qwen2.5:14b`;
- доступ к `http://localhost:11434/v1`.

Если Ollama или `qwen2.5:14b` недоступны, LLM shadow не сможет работать.

Если задача требует обязательный LLM shadow, отсутствие Ollama, модели `qwen2.5:14b` или доступа к `http://localhost:11434/v1` нужно считать ошибкой среды и сообщить пользователю, что запуск невозможен в требуемом режиме.

## Как запускать

Если skill распакован как самостоятельная папка:

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH="src"
python run.py --input "<папка_с_тендером>" --out "<папка_результата>"
```

Если нужен запуск с LLM shadow, перед запуском выставь переменные:

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
```

## Что вернуть пользователю

В ответе пользователю дай:

1. итоговый сценарий;
2. краткую рекомендацию;
3. нужна ли ручная проверка;
4. блокирующие критерии, если они есть;
5. ключевые причины решения;
6. вопросы, которые нужно уточнить у заказчика;
7. пути к созданным файлам:
   - `tender_summary.md`;
   - `questions_for_customer.md`;
   - `tender_score.json`.

## Как трактовать итоговые сценарии

- `relevant_dealer` — тендер подходит, но его лучше передать дилеру или партнёру.
- `relevant_direct` — тендер подходит для прямого участия.
- `need_human_review` — нужна ручная проверка.
- `not_relevant` — тендер не подходит.

## Важное правило про LLM

LLM shadow не является источником итогового решения.

LLM не меняет:

- `status`;
- `risk`;
- `human_review_required`;
- `comment`;
- `scenario_result`.

LLM добавляет только `llm_verdict` внутри конкретного правила.

Если `llm_verdict` конфликтует с deterministic rule, укажи это как диагностический конфликт, но не меняй итоговый сценарий.

## Что не делать

- Не анализировать `.sign`-файлы как содержательные тендерные документы.
- Не выдавать `llm_verdict` как финальное решение.
- Не менять `rule_engine`, `scenario_classifier`, scoring-конфиги и критерии без отдельного прямого запроса.
- Не делать выводы без опоры на `evidence` из результата анализа.
