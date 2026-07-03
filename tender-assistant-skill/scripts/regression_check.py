from __future__ import annotations

import json
import gc
import io
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True


def _reconfigure_stream(stream: Any) -> Any:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
        return stream
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        try:
            return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
        except (OSError, ValueError):
            return stream
    return stream


sys.stdout = _reconfigure_stream(sys.stdout)
sys.stderr = _reconfigure_stream(sys.stderr)


SCRIPT_PATH = Path(__file__).resolve()
SKILL_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[2]
WORK_DIR = REPO_ROOT / "outputs" / "debug" / "regression_check"

PYTHON_TIMEOUT = 30
REAL_TENDER_TIMEOUT = 180
CLEANUP_ATTEMPTS = 8
CLEANUP_INITIAL_DELAY = 0.2
CLEANUP_MAX_DELAY = 2.0

PRODUCTION_FILES = [
    "tender-assistant-skill/run.py",
    "tender-assistant-skill/src/output/summary_writer.py",
    "tender-assistant-skill/src/scoring/scenario_classifier.py",
]

ALLOWED_SCENARIOS = {
    "not_relevant",
    "relevant_direct",
    "relevant_dealer",
    "need_human_review",
}

# These expected scenarios are regression snapshots for current fixtures.
# If scoring business logic changes intentionally, update these expected values deliberately.
EXPECTED_TENDER_SCENARIOS = {
    "Тендер 1": "relevant_dealer",
    "Тендер 2": "relevant_dealer",
    "Тендер 3": "need_human_review",
}

ARTIFICIAL_FILES = [
    "tmp_score_with_scenario.json",
    "tmp_summary_with_scenario.md",
    "tmp_score_without_scenario.json",
    "tmp_summary_without_scenario.md",
    "tmp_score_partial_scenario.json",
    "tmp_summary_partial_scenario.md",
]


def rel_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def command_text(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


def make_python_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def is_python_command(args: list[str]) -> bool:
    if not args:
        return False
    try:
        return Path(args[0]).resolve() == Path(sys.executable).resolve()
    except OSError:
        return args[0] == sys.executable


def _decode_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_command(args: list[str], timeout: int) -> dict[str, Any]:
    python_command = is_python_command(args)
    result: dict[str, Any] = {
        "command": args,
        "command_text": command_text(args),
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "status": "FAIL",
        "python_env": "yes" if python_command else "n/a",
        "text_decoding": "utf-8/errors=replace",
    }
    try:
        completed = subprocess.run(
            args,
            cwd=REPO_ROOT,
            shell=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=make_python_env() if python_command else None,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        result["stdout"] = _decode_output(exc.stdout)
        result["stderr"] = _decode_output(exc.stderr) or f"timeout after {timeout} seconds"
        return result
    except OSError as exc:
        result["stderr"] = f"OSError: {exc}"
        return result

    result["exit_code"] = completed.returncode
    result["stdout"] = completed.stdout
    result["stderr"] = completed.stderr
    result["status"] = "OK" if completed.returncode == 0 else "FAIL"
    return result


def safe_write_json(path: Path, data: dict[str, Any]) -> tuple[bool, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
    except (OSError, TypeError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def safe_write_text(path: Path, text: str) -> tuple[bool, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(text)
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def safe_read_json(path: Path) -> tuple[Any | None, str]:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file), ""
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def safe_read_text(path: Path) -> tuple[str | None, str]:
    try:
        return path.read_text(encoding="utf-8"), ""
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def safe_exists(path: Path) -> tuple[bool, str]:
    try:
        return path.exists(), ""
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def read_gitignore_patterns() -> list[str]:
    gitignore = REPO_ROOT / ".gitignore"
    text, error = safe_read_text(gitignore)
    if error or text is None:
        return []
    patterns = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def check_gitignore(patterns: list[str]) -> dict[str, bool]:
    normalized_patterns = []
    for pattern in patterns:
        normalized = pattern.replace("\\", "/").lstrip("/")
        if normalized.startswith("!"):
            continue
        if normalized.endswith("/**"):
            normalized = normalized[:-3]
        normalized_patterns.append(normalized.rstrip("/"))

    outputs_ignored = "outputs" in normalized_patterns
    outputs_debug_ignored = outputs_ignored or "outputs/debug" in normalized_patterns
    pycache_ignored = "__pycache__" in normalized_patterns
    pyc_ignored = "*.pyc" in normalized_patterns or "*.py[cod]" in normalized_patterns
    return {
        "outputs": outputs_ignored,
        "outputs_debug": outputs_debug_ignored,
        "pycache": pycache_ignored,
        "pyc": pyc_ignored,
    }


def scan_pycache_state() -> tuple[set[str], set[str], str]:
    dirs: set[str] = set()
    files: set[str] = set()
    try:
        for path in SKILL_ROOT.rglob("__pycache__"):
            if path.is_dir():
                dirs.add(str(path.resolve()))
        for path in SKILL_ROOT.rglob("*.pyc"):
            if path.is_file():
                files.add(str(path.resolve()))
    except OSError as exc:
        return dirs, files, f"{type(exc).__name__}: {exc}"
    return dirs, files, ""


def artificial_score() -> dict[str, Any]:
    return {
        "input_path": "outputs/debug/artificial",
        "document_count": 1,
        "criteria_count": 2,
        "rules_count": 2,
        "stats": {
            "pass": 1,
            "fail": 0,
            "unknown": 1,
            "conflict": 0,
            "risk_low": 1,
            "risk_medium": 1,
            "risk_high": 0,
            "human_review_required": 1,
        },
        "rules": [
            {
                "id": "subject_okpd2_oil",
                "rule_id": "subject_okpd2_oil",
                "block": "Предмет закупки",
                "criterion": "Код ОКПД2 относится к маслам/смазочным материалам",
                "priority": "high",
                "status": "pass",
                "risk": "low",
                "human_review_required": False,
                "comment": "Критерий подтверждён.",
                "evidence": [{"snippet": "ОКПД2 относится к моторным маслам."}],
            },
            {
                "id": "delivery_period",
                "rule_id": "delivery_period",
                "block": "Срок поставки",
                "criterion": "Срок поставки определён",
                "priority": "high",
                "status": "unknown",
                "risk": "medium",
                "human_review_required": True,
                "comment": "Срок поставки не подтверждён.",
                "evidence": [],
            },
        ],
        "scenario_result": {
            "scenario": "need_human_review",
            "recommendation": "Передать на ручную проверку.",
            "confidence": "medium",
            "human_review_required": True,
            "blocking_criteria": [
                {
                    "rule_id": "delivery_period",
                    "criterion": "Срок поставки",
                    "status": "unknown",
                    "risk": "medium",
                }
            ],
            "reasons": [
                {
                    "rule_id": "delivery_period",
                    "message": "Не подтверждён high-priority критерий.",
                    "status": "unknown",
                    "risk": "medium",
                    "priority": "high",
                },
                {
                    "message": "Общая причина без rule_id.",
                },
            ],
            "stats": {},
        },
    }


def append_command_result(lines: list[str], result: dict[str, Any]) -> None:
    lines.append(f"- command: `{result['command_text']}`")
    lines.append(f"- exit code: {result['exit_code']}")
    lines.append(f"- status: {result['status']}")
    lines.append(f"- Python subprocess PYTHONDONTWRITEBYTECODE=1: {result['python_env']}")
    lines.append(f"- stdout/stderr decoding: {result['text_decoding']}")
    if result["stderr"]:
        lines.append("- stderr:")
        lines.append("```")
        lines.append(result["stderr"].rstrip())
        lines.append("```")


def run_syntax_check(lines: list[str], failures: list[str]) -> None:
    lines.extend(["## 2. syntax check", ""])
    lines.append("- mechanism: read source as UTF-8 and compile(..., 'exec')")
    lines.append("- .pyc creation: disabled; this check does not write bytecode")
    lines.append("- files:")
    if not PRODUCTION_FILES:
        lines.append("  - none")
        failures.append("syntax check file list is empty")
        lines.append("")
        return

    for file_path in PRODUCTION_FILES:
        path = REPO_ROOT / file_path
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            lines.append(f"  - `{file_path}`: FAIL ({type(exc).__name__}: {exc})")
            failures.append(f"syntax check failed: {file_path}")
        except ValueError as exc:
            lines.append(f"  - `{file_path}`: FAIL ({type(exc).__name__}: {exc})")
            failures.append(f"syntax check value error: {file_path}")
        except UnicodeDecodeError as exc:
            lines.append(f"  - `{file_path}`: FAIL ({type(exc).__name__}: {exc})")
            failures.append(f"syntax check decode failed: {file_path}")
        except OSError as exc:
            lines.append(f"  - `{file_path}`: FAIL ({type(exc).__name__}: {exc})")
            failures.append(f"syntax check read failed: {file_path}")
        else:
            lines.append(f"  - `{file_path}`: OK")
    lines.append("")


def run_import_check(lines: list[str], failures: list[str]) -> None:
    lines.extend(["## 3. runtime imports", ""])
    code = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, str(Path('tender-assistant-skill/src').resolve())); "
        "from scoring.scenario_classifier import classify_scenario; "
        "from output.summary_writer import render_summary; "
        "print('imports OK')"
    )
    result = run_command([sys.executable, "-c", code], PYTHON_TIMEOUT)
    append_command_result(lines, result)
    ok = result["status"] == "OK" and "imports OK" in result["stdout"]
    lines.append(f"- imports marker: {'OK' if ok else 'FAIL'}")
    if not ok:
        failures.append("runtime imports failed")
    lines.append("")


def run_help_check(lines: list[str], failures: list[str]) -> None:
    lines.extend(["## 4. run.py --help", ""])
    result = run_command([sys.executable, "tender-assistant-skill/run.py", "--help"], PYTHON_TIMEOUT)
    append_command_result(lines, result)
    help_text = result["stdout"].lower()
    ok = result["status"] == "OK" and ("usage" in help_text or "--input" in help_text)
    lines.append(f"- help output marker: {'OK' if ok else 'FAIL'}")
    if not ok:
        failures.append("run.py --help failed")
    lines.append("")


def check_markdown(
    path: Path,
    expected: list[str],
    forbidden: list[str] | None = None,
) -> tuple[bool, list[str], list[str], str]:
    text, error = safe_read_text(path)
    if error or text is None:
        return False, [], [], error
    missing = [item for item in expected if item not in text]
    present_forbidden = [item for item in (forbidden or []) if item in text]
    return not missing and not present_forbidden, missing, present_forbidden, ""


def run_one_summary_case(
    case_name: str,
    score_path: Path,
    summary_path: Path,
    score: dict[str, Any],
    expected: list[str],
    forbidden: list[str] | None,
    lines: list[str],
    failures: list[str],
) -> None:
    write_ok, write_error = safe_write_json(score_path, score)
    if not write_ok:
        lines.append(f"- {case_name}: FAIL")
        lines.append(f"- write error: {write_error}")
        failures.append(f"summary artificial failed: {case_name}")
        return

    result = run_command(
        [
            sys.executable,
            "tender-assistant-skill/src/output/summary_writer.py",
            rel_path(score_path),
            rel_path(summary_path),
        ],
        PYTHON_TIMEOUT,
    )
    lines.append(f"### {case_name}")
    append_command_result(lines, result)

    markdown_ok, missing, present_forbidden, markdown_error = check_markdown(
        summary_path,
        expected,
        forbidden,
    )
    ok = result["status"] == "OK" and markdown_ok
    lines.append(f"- markdown check: {'OK' if markdown_ok else 'FAIL'}")
    if markdown_error:
        lines.append(f"- markdown read error: {markdown_error}")
    if missing:
        lines.append("- missing expected strings:")
        for item in missing:
            lines.append(f"  - {item}")
    if present_forbidden:
        lines.append("- forbidden strings found:")
        for item in present_forbidden:
            lines.append(f"  - {item}")
    lines.append(f"- {case_name}: {'OK' if ok else 'FAIL'}")
    if not ok:
        failures.append(f"summary artificial failed: {case_name}")
    lines.append("")


def run_summary_checks(lines: list[str], failures: list[str]) -> None:
    lines.extend(["## 5. summary_writer artificial checks", ""])
    base = artificial_score()

    full_expected = [
        "## 2. Итоговый сценарий",
        "- Сценарий: need_human_review",
        "- Рекомендация: Передать на ручную проверку.",
        "- Уверенность: medium",
        "- Требуется ручная проверка: да",
        "Блокирующие критерии:",
        "priority: —",
        "Причины:",
        "- Общая причина без rule_id.",
        "## 3. Краткая статистика",
        "## 4. Критерии, требующие внимания",
        "## 5. Подтверждённые критерии",
        "## 6. Неподтверждённые низкоприоритетные критерии",
    ]
    run_one_summary_case(
        "full scenario_result",
        WORK_DIR / "tmp_score_with_scenario.json",
        WORK_DIR / "tmp_summary_with_scenario.md",
        base,
        full_expected,
        None,
        lines,
        failures,
    )

    without_scenario = dict(base)
    without_scenario.pop("scenario_result", None)
    run_one_summary_case(
        "without scenario_result",
        WORK_DIR / "tmp_score_without_scenario.json",
        WORK_DIR / "tmp_summary_without_scenario.md",
        without_scenario,
        [
            "## 2. Итоговый сценарий",
            "Итоговый сценарий не рассчитан.",
            "## 3. Краткая статистика",
        ],
        None,
        lines,
        failures,
    )

    partial_scenario = dict(base)
    partial_scenario["scenario_result"] = {"scenario": "relevant_direct"}
    run_one_summary_case(
        "partial scenario_result",
        WORK_DIR / "tmp_score_partial_scenario.json",
        WORK_DIR / "tmp_summary_partial_scenario.md",
        partial_scenario,
        [
            "## 2. Итоговый сценарий",
            "- Сценарий: relevant_direct",
            "- Рекомендация: —",
            "- Уверенность: —",
            "- Требуется ручная проверка: не указано",
            "Блокирующие критерии не выявлены.",
        ],
        ["Причины:"],
        lines,
        failures,
    )


def run_real_tender_checks(lines: list[str], failures: list[str]) -> None:
    lines.extend(["## 6. real tender checks", ""])
    tender_paths = {
        name: REPO_ROOT / "sources_info" / name for name in EXPECTED_TENDER_SCENARIOS
    }
    missing_tender_paths = [path for path in tender_paths.values() if not path.is_dir()]
    if missing_tender_paths:
        lines.append("SKIP: real tender checks, source folders not found")
        lines.append("- missing source folders:")
        for path in missing_tender_paths:
            lines.append(f"  - {rel_path(path)}")
        lines.append("")
        return

    for index, (name, source_path) in enumerate(tender_paths.items(), start=1):
        out_dir = WORK_DIR / f"tender_{index}_scenario"
        result = run_command(
            [
                sys.executable,
                "tender-assistant-skill/run.py",
                "--input",
                rel_path(source_path),
                "--out",
                rel_path(out_dir),
                "--top-k",
                "5",
                "--min-score",
                "0",
            ],
            REAL_TENDER_TIMEOUT,
        )
        lines.append(f"### {name}")
        append_command_result(lines, result)

        score_path = out_dir / "tender_score.json"
        summary_path = out_dir / "tender_summary.md"
        questions_path = out_dir / "questions_for_customer.md"
        score_exists, score_exists_error = safe_exists(score_path)
        summary_exists, summary_exists_error = safe_exists(summary_path)
        questions_exists, questions_exists_error = safe_exists(questions_path)

        files_ok = score_exists and summary_exists and questions_exists
        lines.append(
            "- files created: "
            f"tender_score.json={'yes' if score_exists else 'no'}, "
            f"tender_summary.md={'yes' if summary_exists else 'no'}, "
            f"questions_for_customer.md={'yes' if questions_exists else 'no'}"
        )
        for path_error in [score_exists_error, summary_exists_error, questions_exists_error]:
            if path_error:
                lines.append(f"- file existence error: {path_error}")

        score_data, score_error = safe_read_json(score_path)
        scenario = None
        scenario_ok = False
        scenario_present = False
        if score_error:
            lines.append(f"- tender_score.json read: FAIL ({score_error})")
        elif isinstance(score_data, dict):
            scenario_result = score_data.get("scenario_result")
            if isinstance(scenario_result, dict):
                scenario_present = True
                scenario = scenario_result.get("scenario")
                scenario_ok = scenario in ALLOWED_SCENARIOS
        else:
            lines.append("- tender_score.json read: FAIL (top-level JSON is not an object)")

        summary_ok, missing, _, summary_error = check_markdown(
            summary_path,
            ["## 2. Итоговый сценарий", "## 3. Краткая статистика"],
        )
        if summary_error:
            lines.append(f"- tender_summary.md read: FAIL ({summary_error})")
        if missing:
            lines.append("- tender_summary.md missing expected strings:")
            for item in missing:
                lines.append(f"  - {item}")

        expected = EXPECTED_TENDER_SCENARIOS[name]
        expected_ok = scenario == expected
        lines.append(f"- scenario: {scenario}")
        lines.append(f"- expected scenario: {expected}")
        if not expected_ok:
            lines.append(f"- scenario mismatch score path: {rel_path(score_path)}")

        ok = (
            result["status"] == "OK"
            and files_ok
            and scenario_present
            and scenario_ok
            and summary_ok
            and expected_ok
        )
        lines.append(f"- {name}: {'OK' if ok else 'FAIL'}")
        if not ok:
            failures.append(f"real tender failed: {name}")
        lines.append("")


def make_writable(path: Path) -> None:
    try:
        if os.name == "nt":
            os.chmod(path, stat.S_IWRITE)
        else:
            current_mode = path.stat().st_mode
            os.chmod(path, current_mode | stat.S_IWUSR)
    except OSError:
        pass


def _rmtree_onerror(func: Any, path: str, exc_info: Any) -> None:
    make_writable(Path(path))
    func(path)


def _rmtree_onexc(func: Any, path: str, exc: BaseException) -> None:
    make_writable(Path(path))
    func(path)


def remove_tree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_rmtree_onexc)
    else:
        shutil.rmtree(path, onerror=_rmtree_onerror)


def remove_once(path: Path) -> None:
    make_writable(path)
    if path.is_dir() and not path.is_symlink():
        remove_tree(path)
    else:
        path.unlink()


def safe_remove_path(path: Path) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "path": rel_path(path),
        "status": "absent",
        "attempts": 0,
        "retried": False,
        "error": "",
    }
    for attempt in range(1, CLEANUP_ATTEMPTS + 1):
        detail["attempts"] = attempt
        try:
            if not path.exists():
                detail["status"] = "absent" if attempt == 1 else "removed"
                return detail
            remove_once(path)
            detail["status"] = "removed"
            return detail
        except OSError as exc:
            detail["status"] = "error"
            detail["error"] = f"{type(exc).__name__}: {exc}"
            if attempt >= CLEANUP_ATTEMPTS:
                return detail
            detail["retried"] = True
            gc.collect()
            time.sleep(min(CLEANUP_INITIAL_DELAY * (2 ** (attempt - 1)), CLEANUP_MAX_DELAY))
    return detail


def cleanup_outputs(
    gitignore_info: dict[str, bool],
    initial_pycache_dirs: set[str],
    initial_pyc_files: set[str],
    lines: list[str],
    failures: list[str],
) -> None:
    lines.extend(["## 7. cleanup", ""])
    removed: list[str] = []
    absent: list[str] = []
    retry_paths: list[str] = []
    cleanup_warnings: list[str] = []
    cleanup_errors: list[str] = []

    for filename in ARTIFICIAL_FILES:
        path = WORK_DIR / filename
        detail = safe_remove_path(path)
        if detail["status"] == "removed":
            removed.append(detail["path"])
        elif detail["status"] == "absent":
            absent.append(detail["path"])
        else:
            cleanup_errors.append(f"{detail['path']}: {detail['error']}")
        if detail["retried"]:
            retry_paths.append(detail["path"])

    try:
        tender_result_paths = sorted(WORK_DIR.glob("tender_*")) if WORK_DIR.exists() else []
    except OSError as exc:
        tender_result_paths = []
        cleanup_errors.append(f"{rel_path(WORK_DIR)} tender_* scan: {type(exc).__name__}: {exc}")

    for path in tender_result_paths:
        detail = safe_remove_path(path)
        if detail["status"] == "removed":
            removed.append(detail["path"])
        elif detail["status"] == "absent":
            absent.append(detail["path"])
        else:
            cleanup_errors.append(f"{detail['path']}: {detail['error']}")
        if detail["retried"]:
            retry_paths.append(detail["path"])

    pycache_removed: list[str] = []
    if not gitignore_info["pycache"] or not gitignore_info["pyc"]:
        current_dirs, current_files, scan_error = scan_pycache_state()
        if scan_error:
            cleanup_errors.append(f"pycache scan: {scan_error}")
        for file_name in sorted(current_files - initial_pyc_files):
            path = Path(file_name)
            detail = safe_remove_path(path)
            if detail["status"] == "removed":
                pycache_removed.append(detail["path"])
            elif detail["status"] == "error":
                cleanup_errors.append(f"{detail['path']}: {detail['error']}")
            if detail["retried"]:
                retry_paths.append(detail["path"])
        for dir_name in sorted(current_dirs - initial_pycache_dirs, reverse=True):
            path = Path(dir_name)
            detail = safe_remove_path(path)
            if detail["status"] == "removed":
                pycache_removed.append(detail["path"])
            elif detail["status"] == "error":
                cleanup_errors.append(f"{detail['path']}: {detail['error']}")
            if detail["retried"]:
                retry_paths.append(detail["path"])
    else:
        lines.append("- __pycache__/.pyc cleanup: skipped, covered by .gitignore")

    report_path = WORK_DIR / "report.md"
    if not gitignore_info["outputs_debug"] and report_path.exists():
        detail = safe_remove_path(report_path)
        if detail["status"] == "removed":
            removed.append(detail["path"])
        elif detail["status"] == "absent":
            absent.append(detail["path"])
        else:
            cleanup_errors.append(f"{detail['path']}: {detail['error']}")
        if detail["retried"]:
            retry_paths.append(detail["path"])

    lines.append("- removed temporary/result paths:")
    if removed:
        for item in removed:
            lines.append(f"  - {item}")
    else:
        lines.append("  - none")

    lines.append("- absent temporary/result paths:")
    if absent:
        for item in absent:
            lines.append(f"  - {item}")
    else:
        lines.append("  - none")

    lines.append("- cleanup retry paths:")
    if retry_paths:
        for item in sorted(set(retry_paths)):
            lines.append(f"  - {item}")
    else:
        lines.append("  - none")

    lines.append("- removed new __pycache__/.pyc paths:")
    if pycache_removed:
        for item in pycache_removed:
            lines.append(f"  - {item}")
    else:
        lines.append("  - не найдено новых __pycache__/.pyc")

    remaining = []
    if WORK_DIR.exists():
        try:
            remaining = sorted(rel_path(path) for path in WORK_DIR.iterdir())
        except OSError as exc:
            cleanup_errors.append(f"{rel_path(WORK_DIR)}: {type(exc).__name__}: {exc}")
    lines.append("- remaining in outputs/debug/regression_check:")
    if remaining:
        for item in remaining:
            lines.append(f"  - {item}")
    else:
        lines.append("  - none")

    if cleanup_errors and gitignore_info["outputs_debug"]:
        remaining_errors = []
        for item in cleanup_errors:
            if item.startswith("outputs/debug/"):
                cleanup_warnings.append(item)
            else:
                remaining_errors.append(item)
        cleanup_errors = remaining_errors

    lines.append("- cleanup warnings:")
    if cleanup_warnings:
        for item in cleanup_warnings:
            lines.append(f"  - {item}")
    else:
        lines.append("  - none")

    if cleanup_errors:
        lines.append("- cleanup errors:")
        for item in cleanup_errors:
            lines.append(f"  - {item}")
        failures.append("cleanup failed")
    lines.append("")


def run_git_checks(lines: list[str], failures: list[str]) -> None:
    lines.extend(["## 8. git checks", ""])
    diff_result = run_command(["git", "diff", "--", *PRODUCTION_FILES], PYTHON_TIMEOUT)
    status_result = run_command(["git", "status", "--short"], PYTHON_TIMEOUT)

    production_diff_empty = diff_result["status"] == "OK" and not diff_result["stdout"].strip()
    status_text = status_result["stdout"]
    normalized_status = status_text.replace("\\", "/")
    no_outputs_debug = "outputs/debug" not in normalized_status
    no_pycache = "__pycache__" not in normalized_status and ".pyc" not in normalized_status

    append_command_result(lines, diff_result)
    lines.append(f"- production diff empty: {'OK' if production_diff_empty else 'FAIL'}")
    lines.append("")
    append_command_result(lines, status_result)
    lines.append(f"- git status has no outputs/debug: {'OK' if no_outputs_debug else 'FAIL'}")
    lines.append(f"- git status has no __pycache__ / .pyc: {'OK' if no_pycache else 'FAIL'}")
    lines.append("- full git status --short:")
    lines.append("```")
    lines.append(status_text.rstrip() if status_text.strip() else "(empty)")
    lines.append("```")

    if not production_diff_empty:
        failures.append("production diff is not empty")
    if status_result["status"] != "OK":
        failures.append("git status failed")
    if not no_outputs_debug:
        failures.append("git status contains outputs/debug")
    if not no_pycache:
        failures.append("git status contains __pycache__ or .pyc")
    lines.append("")


def main() -> int:
    failures: list[str] = []
    lines: list[str] = ["# regression_check report", ""]

    gitignore_patterns = read_gitignore_patterns()
    gitignore_info = check_gitignore(gitignore_patterns)
    initial_pycache_dirs, initial_pyc_files, pycache_scan_error = scan_pycache_state()
    branch_result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], PYTHON_TIMEOUT)
    initial_status = run_command(["git", "status", "--short"], PYTHON_TIMEOUT)

    if pycache_scan_error:
        failures.append(f"initial pycache scan failed: {pycache_scan_error}")

    lines.extend(
        [
            "## 1. Environment",
            "",
            f"- repo root: `{REPO_ROOT}`",
            f"- Python executable: `{sys.executable}`",
            f"- Python version: `{sys.version.replace(chr(10), ' ')}`",
            f"- branch: `{branch_result['stdout'].strip() if branch_result['status'] == 'OK' else 'unknown'}`",
            f"- sys.dont_write_bytecode: {'yes' if sys.dont_write_bytecode else 'no'}",
            "- console stdout/stderr encoding: utf-8/errors=replace",
            "- Python subprocess env: PYTHONDONTWRITEBYTECODE=1",
            "- subprocess stdout/stderr decoding: encoding=utf-8, errors=replace",
            "- markdown report encoding: utf-8",
            f"- outputs ignored: {'yes' if gitignore_info['outputs'] else 'no'}",
            f"- outputs/debug ignored: {'yes' if gitignore_info['outputs_debug'] else 'no'}",
            f"- __pycache__ ignored: {'yes' if gitignore_info['pycache'] else 'no'}",
            f"- *.pyc ignored: {'yes' if gitignore_info['pyc'] else 'no'}",
            "- initial git status:",
            "```",
            initial_status["stdout"].rstrip() if initial_status["stdout"].strip() else "(empty)",
            "```",
            "",
        ]
    )

    run_syntax_check(lines, failures)
    run_import_check(lines, failures)
    run_help_check(lines, failures)
    run_summary_checks(lines, failures)
    run_real_tender_checks(lines, failures)
    cleanup_outputs(gitignore_info, initial_pycache_dirs, initial_pyc_files, lines, failures)
    run_git_checks(lines, failures)

    lines.extend(["## 9. final result", ""])
    if failures:
        lines.append("CHECKS FAILED")
        lines.append("")
        lines.append("Failures:")
        for item in failures:
            lines.append(f"- {item}")
        exit_code = 1
    else:
        lines.append("ALL CHECKS PASSED")
        exit_code = 0

    report_text = "\n".join(lines).rstrip() + "\n"
    print(report_text)

    if gitignore_info["outputs_debug"]:
        write_ok, write_error = safe_write_text(WORK_DIR / "report.md", report_text)
        if not write_ok:
            print(f"WARNING: failed to write report.md: {write_error}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
