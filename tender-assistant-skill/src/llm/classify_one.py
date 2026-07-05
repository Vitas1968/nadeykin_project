import argparse
import json
import sys
from pathlib import Path
from typing import Any

from llm.classifier import classify_criterion


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            continue


def _write_stdout(text: str) -> None:
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    except UnicodeEncodeError:
        pass

    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def _write_stderr(text: str) -> None:
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
        return
    except UnicodeEncodeError:
        pass

    sys.stderr.buffer.write(text.encode("utf-8"))
    sys.stderr.buffer.flush()


def _load_rule(path: Path) -> dict[str, Any]:
    try:
        raw_rule = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"Rule JSON file not found: {path}") from exc
    except OSError as exc:
        raise ValueError(f"Cannot read rule JSON file: {path}") from exc

    try:
        rule = json.loads(raw_rule)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in rule file: {exc}") from exc

    if not isinstance(rule, dict):
        raise ValueError("Rule JSON top-level value must be an object.")
    return rule


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()

    parser = argparse.ArgumentParser(
        description="Classify one rule-like JSON with the LLM criterion classifier."
    )
    parser.add_argument(
        "--rule-json",
        required=True,
        type=Path,
        help="Path to a JSON file with one rule-like object.",
    )
    args = parser.parse_args(argv)

    try:
        rule = _load_rule(args.rule_json)
    except ValueError as exc:
        _write_stderr(f"Input error: {exc}\n")
        return 2

    try:
        llm_verdict = classify_criterion(rule)
        if not isinstance(llm_verdict, dict):
            _write_stderr("Contract error: classify_criterion returned non-dict result.\n")
            return 1

        payload = json.dumps(llm_verdict, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as exc:
        _write_stderr(f"Runtime error: {exc}\n")
        return 1

    try:
        _write_stdout(f"{payload}\n")
    except Exception as exc:
        _write_stderr(f"Output error: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
