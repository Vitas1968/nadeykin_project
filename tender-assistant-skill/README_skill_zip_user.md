# Пользовательская инструкция по запуску `tender-assistant-skill`

Этот файл нужно читать **до распаковки архива** `tender-assistant-skill.zip`.

`README_skill_zip_user.md` — инструкция для пользователя.  
`RESULTS_INTERPRETATION.md` — инструкция по интерпретации результатов анализа.  
`SKILL.md` и `AGENT_PROMPT.md` внутри архива — служебные инструкции skill-а и агента.

---

## 1. Назначение

`tender-assistant-skill` обрабатывает папку с документами тендера и формирует результаты анализа.

На выходе создаются файлы:

```text
questions_for_customer.md
tender_score.json
tender_summary.md
```

Как интерпретировать эти файлы, описано в `RESULTS_INTERPRETATION.md`.

Текущий основной режим запуска — **без DOCX-экспорта**:

```powershell
--no-docx
```

DOCX-экспорт и DOCX-шаблон требуют отдельной проверки.

Все настройки проводятся в PowerShell

---

## 2. Обязательные требования для запуска с LLM

Текущая конфигурация skill-а рассчитана на запуск с локальной LLM через **Ollama**.

Перед запуском анализа на компьютере должны быть установлены и доступны:

```text
Ollama
модель qwen2.5:14b
```

Без работающей Ollama и модели `qwen2.5:14b` LLM-проверка не выполнится.  
В результате в `tender_score.json` могут появиться статусы `unavailable`, `error` или timeout по LLM.

Проверь, что Ollama установлена:

```powershell
ollama --version
```

Проверь, что локальный сервер Ollama отвечает:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

Проверь список моделей:

```powershell
ollama list
```

В списке должна быть модель:

```text
qwen2.5:14b
```

Если модели нет, скачай её:

```powershell
ollama pull qwen2.5:14b
```

Если команда проверки сервера не отвечает, открой Ollama из Start Menu и повтори проверку.

В `.env.example` уже указаны настройки для Ollama:

```env
TENDER_LLM_ENABLED=true
TENDER_LLM_PROVIDER=ollama
TENDER_LLM_BASE_URL=http://localhost:11434/v1
TENDER_LLM_MODEL=qwen2.5:14b
TENDER_LLM_API_KEY=ollama
```

---

## 3. Целевая структура папок

Перед распаковкой архива нужно создать рабочую папку и внутреннюю структуру.

Рабочая папка:

```text
D:\skill_zip_test
```

Ожидаемая структура:

```text
D:\skill_zip_test\
  README_skill_zip_user.md
  tender-assistant-skill.zip
  input\
  out\
  skill\
```

Назначение:

```text
README_skill_zip_user.md     — эта инструкция
tender-assistant-skill.zip   — архив skill-а
input\                       — сюда кладутся папки с тендерами
out\                         — сюда записываются результаты обработки
skill\                       — сюда распаковывается архив tender-assistant-skill.zip
```

Создать структуру можно одной командной группой в PowerShell:

```powershell
$Root = "D:\skill_zip_test"

New-Item -ItemType Directory -Force $Root | Out-Null
New-Item -ItemType Directory -Force "$Root\input" | Out-Null
New-Item -ItemType Directory -Force "$Root\out" | Out-Null
New-Item -ItemType Directory -Force "$Root\skill" | Out-Null
```

Если архив и README лежат в папке `Downloads`, их можно скопировать в рабочую папку так:

```powershell
Copy-Item "$env:USERPROFILE\Downloads\tender-assistant-skill.zip" "D:\skill_zip_test\tender-assistant-skill.zip" -Force
Copy-Item "$env:USERPROFILE\Downloads\README_skill_zip_user.md" "D:\skill_zip_test\README_skill_zip_user.md" -Force
```

Если README уже находится внутри архива, после распаковки он также появится в папке:

```text
D:\skill_zip_test\skill\README_skill_zip_user.md
```

Это нормально. Основная рабочая инструкция может лежать рядом с архивом:

```text
D:\skill_zip_test\README_skill_zip_user.md
```

Проверить созданную структуру:

```powershell
Get-ChildItem "D:\skill_zip_test" -Force | Select-Object Name
```

Ожидаемо:

```text
README_skill_zip_user.md
tender-assistant-skill.zip
input
out
skill
```

Папки с тендерами нужно класть внутрь `input`:

```text
D:\skill_zip_test\input\Тендер 1\
D:\skill_zip_test\input\Тендер 2\
D:\skill_zip_test\input\Тендер 3\
```

---

## 4. Распаковка архива

Архив нужно распаковать **в папку `skill`**, а не прямо в корень `D:\skill_zip_test`.

Правильно:

```text
D:\skill_zip_test\skill\run.py
D:\skill_zip_test\skill\requirements.txt
D:\skill_zip_test\skill\.env.example
D:\skill_zip_test\skill\src\
D:\skill_zip_test\skill\config\
```

Неправильно:

```text
D:\skill_zip_test\run.py
D:\skill_zip_test\requirements.txt
D:\skill_zip_test\src\
```

Команда распаковки:

```powershell
Expand-Archive `
  "D:\skill_zip_test\tender-assistant-skill.zip" `
  -DestinationPath "D:\skill_zip_test\skill" `
  -Force
```

Проверь, что архив распаковался в `skill`:

```powershell
Get-ChildItem "D:\skill_zip_test\skill" -Force | Select-Object Name
```

Ожидаемо внутри `D:\skill_zip_test\skill`:

```text
README_skill_zip_user.md
RESULTS_INTERPRETATION.md
SKILL.md
AGENT_PROMPT.md
requirements.txt
.env.example
run.py
config
prompts
src
docs
```

---

## 5. Создание отдельного Python-окружения

Перейди в тестовую папку:

```powershell
cd D:\skill_zip_test
```

Создай отдельное окружение:

```powershell
py -3.13 -m venv .venv
```

Активируй окружение:

```powershell
.\.venv\Scripts\Activate.ps1
```

Проверь, что используется Python из этой папки:

```powershell
python -c "import sys; print(sys.executable)"
```

Ожидаемый путь:

```text
D:\skill_zip_test\.venv\Scripts\python.exe
```

---

## 6. Установка зависимостей

Перейди в распакованный skill:

```powershell
cd D:\skill_zip_test\skill
```

Установи зависимости:

```powershell
python -m pip install -r requirements.txt
```

Проверь основные импорты:

```powershell
python -c "import pandas, openpyxl, docx, pypdf, yaml; print('deps ok')"
```

Ожидаемый вывод:

```text
deps ok
```

---

## 7. Настройка `.env`

После распаковки архива в папке `skill` уже есть файл:

```text
.env.example
```

Это готовый шаблон настроек для локального Ollama и модели `qwen2.5:14b`.

Выполните команды:

```powershell
cd D:\skill_zip_test\skill
Copy-Item .env.example .env
```

После этого вручную задавать переменные `$env:TENDER_LLM_*` не нужно.  
`run.py` автоматически загружает настройки из `.env`.

Готовые значения в `.env.example`:

```env
TENDER_LLM_ENABLED=true
TENDER_LLM_SELECTIVE_ENABLED=true
TENDER_LLM_RUN_ON_PASS=false
TENDER_LLM_PROVIDER=ollama
TENDER_LLM_BASE_URL=http://localhost:11434/v1
TENDER_LLM_MODEL=qwen2.5:14b
TENDER_LLM_API_KEY=ollama
TENDER_LLM_TIMEOUT_SECONDS=300
TENDER_LLM_MAX_TOKENS=192
TENDER_LLM_MAX_EVIDENCE_ITEMS=1
TENDER_LLM_MAX_EVIDENCE_CHARS=600
```

Внешние переменные окружения, заданные в PowerShell или системой, имеют приоритет над `.env`.

`PYTHONPATH` вручную задавать не нужно.

---

## 8. Проверка Ollama и модели перед запуском с LLM

Проверь, что Ollama отвечает:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

Проверь список моделей:

```powershell
ollama list
```

В списке должна быть модель:

```text
qwen2.5:14b
```

---

## 9. Запуск одного тендера

Пример для папки:

```text
D:\skill_zip_test\input\Тендер 1
```

Команда:

```powershell
cd D:\skill_zip_test\skill

python run.py `
  --input "D:\skill_zip_test\input\Тендер 1" `
  --out "D:\skill_zip_test\out\Тендер 1" `
  --no-docx
```

Ожидаемые файлы результата:

```text
D:\skill_zip_test\out\Тендер 1\questions_for_customer.md
D:\skill_zip_test\out\Тендер 1\tender_score.json
D:\skill_zip_test\out\Тендер 1\tender_summary.md
```

---

## 10. Запуск нескольких тендеров

Пример batch-запуска для трёх папок:

```powershell
cd D:\skill_zip_test\skill

foreach ($Tender in @("Тендер 1", "Тендер 2", "Тендер 3")) {
  python run.py `
    --input "D:\skill_zip_test\input\$Tender" `
    --out "D:\skill_zip_test\out\$Tender" `
    --no-docx
}
```

---

## 11. Проверка результатов

Проверить созданные файлы:

```powershell
Get-ChildItem "D:\skill_zip_test\out" -Recurse -File | Select-Object FullName
```

Минимально ожидается по 3 файла на каждый тендер:

```text
questions_for_customer.md
tender_score.json
tender_summary.md
```

Не запускай `.md` и `.json` файлы как команды PowerShell.  
Их нужно открывать в редакторе или просматривать через `Get-Content`.

Пример:

```powershell
Get-Content "D:\skill_zip_test\out\Тендер 1\tender_summary.md" -Encoding UTF8
```

Дополнительная инструкция по интерпретации результатов находится в файле:

```text
D:\skill_zip_test\skill\RESULTS_INTERPRETATION.md
```

Открой его, если нужно понять:
- как читать `tender_summary.md`;
- как интерпретировать `questions_for_customer.md`;
- как проверять `tender_score.json`;
- что означают `scenario`, `status`, `risk`, `human_review_required` и `llm_verdict`.

---

## 12. Проверка LLM selective в `tender_score.json`

В текущем формате LLM-результаты лежат здесь:

```text

rules[].llm_verdict.invocation_status

```

Проверочный скрипт:

```powershell

@'
from pathlib import Path
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

root = Path(r"D:\skill_zip_test\out")
score_files = sorted(root.rglob("tender_score.json"))

print("score files:", len(score_files))

for score_path in score_files:
    data = json.loads(score_path.read_text(encoding="utf-8"))

    counts = {
        "ok": 0,
        "skipped": 0,
        "unavailable": 0,
        "error": 0,
        "invalid_json": 0,
    }

    procurement_method_verdict = None

    for rule in data.get("rules", []):
        verdict = rule.get("llm_verdict")
        if not verdict:
            continue

        status = verdict.get("invocation_status")
        counts[status] = counts.get(status, 0) + 1

        if rule.get("id") == "procurement_method":
            procurement_method_verdict = verdict

    scenario = data.get("scenario_result", {})

    print()
    print("folder:", score_path.parent)
    print("scenario:", scenario.get("scenario"))
    print("human_review_required:", scenario.get("human_review_required"))
    print("llm_counts:", counts)
    print("procurement_method:", procurement_method_verdict)
'@ | python
```

Для контрольных тестовых тендеров ожидаемый результат:

```text
Тендер 1: skipped=4, unavailable=0
Тендер 2: skipped=4, unavailable=0
Тендер 3: ok=1, skipped=3, unavailable=0
```

---

## 13. Что делать при timeout или `unavailable`

Если в логе есть timeout:

```text
LLM request failed ... TimeoutError
```

или в JSON есть:

```text
unavailable > 0
```

проверь в `.env`:

```env
TENDER_LLM_TIMEOUT_SECONDS=300
```

Для медленной машины можно временно увеличить timeout:

```env
TENDER_LLM_TIMEOUT_SECONDS=420
```

После изменения `.env` перезапусти нужный тендер.

---

## 14. Что не делать

Не распаковывай архив прямо в корень:

```text
D:\skill_zip_test
```

Не задавай вручную:

```powershell
$env:PYTHONPATH="src"
```

Не запускай `.md` и `.json` как команды PowerShell.

Не редактируй файлы внутри `skill`, если не понимаешь, зачем это нужно.

---

## 15. Короткий сценарий запуска

```powershell
$Root = "D:\skill_zip_test"

New-Item -ItemType Directory -Force $Root | Out-Null
New-Item -ItemType Directory -Force "$Root\input" | Out-Null
New-Item -ItemType Directory -Force "$Root\out" | Out-Null
New-Item -ItemType Directory -Force "$Root\skill" | Out-Null

cd D:\skill_zip_test

Expand-Archive `
  "D:\skill_zip_test\tender-assistant-skill.zip" `
  -DestinationPath "D:\skill_zip_test\skill" `
  -Force

py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1

cd D:\skill_zip_test\skill
python -m pip install -r requirements.txt
Copy-Item .env.example .env

ollama --version
Invoke-RestMethod http://localhost:11434/api/tags
ollama list

python run.py `
  --input "D:\skill_zip_test\input\Тендер 1" `
  --out "D:\skill_zip_test\out\Тендер 1" `
  --no-docx
```
