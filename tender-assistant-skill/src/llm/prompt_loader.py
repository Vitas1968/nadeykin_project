from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROMPT_RELATIVE_PATH = Path("prompts") / "classify_criterion.md"
_PLACEHOLDER_RE = re.compile(
    r"\{\{(?:rule_id|criterion|deterministic_status|evidence_json|provider|model)\}\}"
)


class PromptLoadError(Exception):
    pass


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_classify_criterion_prompt() -> str:
    prompt_path = _skill_root() / PROMPT_RELATIVE_PATH
    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptLoadError(f"Unable to load prompt file: {PROMPT_RELATIVE_PATH}") from exc


def render_classify_criterion_prompt(
    *,
    rule_id: str,
    criterion: str,
    deterministic_status: str,
    evidence: list[dict[str, Any]],
    provider: str,
    model: str,
) -> str:
    prompt = load_classify_criterion_prompt()
    evidence_json = json.dumps(evidence, ensure_ascii=False, indent=2)
    replacements = {
        "{{rule_id}}": rule_id,
        "{{criterion}}": criterion,
        "{{deterministic_status}}": deterministic_status,
        "{{evidence_json}}": evidence_json,
        "{{provider}}": provider,
        "{{model}}": model,
    }

    return _PLACEHOLDER_RE.sub(lambda match: replacements[match.group(0)], prompt)
