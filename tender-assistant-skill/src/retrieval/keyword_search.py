from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - optional dependency for YAML criteria files
    yaml = None

try:
    from normalize.tender_document import read_tender_path
except ModuleNotFoundError:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from normalize.tender_document import read_tender_path

_SUPPORTED_EXTENSIONS = {".yaml", ".yml", ".json"}
_SEARCH_TOKEN_RE = re.compile(r"[a-zа-я0-9]+(?:[.\-/][a-zа-я0-9]+)*")
_QUERY_TOKEN_STOPWORDS = {
    "а",
    "без",
    "в",
    "во",
    "для",
    "до",
    "за",
    "и",
    "или",
    "из",
    "к",
    "ко",
    "на",
    "не",
    "о",
    "об",
    "от",
    "по",
    "при",
    "с",
    "со",
    "у",
    "дата",
    "даты",
    "дате",
    "дату",
    "дней",
    "день",
    "дня",
    "рабочих",
    "календарных",
    "подписания",
}
_QUERY_TOKEN_SHORT_WHITELIST = {
    "ип",
    "ту",
}
_DASH_TRANSLATION = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        ",": " ",
        ";": " ",
        ":": " ",
        "(": " ",
        ")": " ",
        "[": " ",
        "]": " ",
        "{": " ",
        "}": " ",
        '"': " ",
        "'": " ",
        "«": " ",
        "»": " ",
        "„": " ",
        "“": " ",
        "”": " ",
        "!": " ",
        "?": " ",
        "№": " ",
    }
)
_SEARCH_SOURCE_FIELDS = ("keywords", "terms", "search_terms")


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_search(text: str) -> str:
    """
    Нормализует текст для поиска.
    """

    normalized = str(text).lower().replace("ё", "е")
    normalized = normalized.translate(_DASH_TRANSLATION)
    normalized = normalized.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    normalized = normalized.translate(_PUNCTUATION_TRANSLATION)
    return _normalize_whitespace(normalized)


def tokenize_search_text(text: str) -> list[str]:
    """
    Возвращает токены для поиска.
    """

    normalized_text = normalize_for_search(text)
    return [match.group(0) for match in _SEARCH_TOKEN_RE.finditer(normalized_text)]


def _is_useful_query_token(normalized_token: str) -> bool:
    if not normalized_token:
        return False
    if normalized_token in _QUERY_TOKEN_STOPWORDS:
        return False
    if normalized_token.isdigit():
        return False
    if len(normalized_token) < 3 and normalized_token not in _QUERY_TOKEN_SHORT_WHITELIST:
        return False
    return True


def build_search_terms(query: str | None = None, keywords: list[str] | None = None) -> list[dict[str, str]]:
    """
    Возвращает список search terms.
    """

    terms: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_term(raw: str, normalized: str, kind: str) -> None:
        if not normalized:
            return
        signature = (kind, normalized)
        if signature in seen:
            return
        seen.add(signature)
        terms.append({"raw": raw, "normalized": normalized, "kind": kind})

    if query is not None:
        normalized_query = normalize_for_search(query)
        if normalized_query:
            add_term(query, normalized_query, "phrase")
            for token in tokenize_search_text(query):
                if _is_useful_query_token(token):
                    add_term(token, token, "token")

    if keywords:
        for keyword in keywords:
            normalized_keyword = normalize_for_search(keyword)
            if not normalized_keyword:
                continue
            kind = "phrase" if " " in normalized_keyword else "token"
            add_term(keyword, normalized_keyword, kind)

    return terms


def _find_phrase_position(text: str, phrase: str) -> int:
    match = re.search(rf"(?<![a-zа-я0-9]){re.escape(phrase)}(?![a-zа-я0-9])", text)
    return match.start() if match else -1


def _find_token_position(text: str, token: str) -> int:
    match = re.search(rf"(?<![a-zа-я0-9]){re.escape(token)}(?![a-zа-я0-9])", text)
    return match.start() if match else -1


def _find_substring_position(text: str, term: str) -> int:
    return text.find(term)


def _build_snippet(text: str, position: int, needle_length: int, max_chars: int = 240) -> str:
    if not text:
        return ""
    if position < 0:
        snippet = _normalize_whitespace(text)
        return snippet if len(snippet) <= max_chars else f"{snippet[: max_chars - 3].rstrip()}..."

    half_window = max(40, max_chars // 2)
    start = max(0, position - half_window)
    end = min(len(text), position + needle_length + half_window)
    snippet = _normalize_whitespace(text[start:end])
    if len(snippet) <= max_chars:
        return snippet
    if len(snippet) <= 3:
        return snippet
    return f"{snippet[: max_chars - 3].rstrip()}..."


def make_snippet(text: str, terms: list[dict], max_chars: int = 320) -> str:
    """
    Делает короткий фрагмент вокруг первого совпадения.
    """

    if max_chars < 1:
        return ""

    original_text = str(text)
    normalized_text = normalize_for_search(original_text)
    if not normalized_text:
        return ""

    phrase_terms: list[str] = []
    token_terms: list[str] = []
    for term in terms or []:
        if not isinstance(term, dict):
            continue
        normalized_term = str(term.get("normalized") or "").strip()
        if not normalized_term:
            continue
        kind = str(term.get("kind") or "").strip()
        if kind == "phrase":
            phrase_terms.append(normalized_term)
        elif kind == "token":
            token_terms.append(normalized_term)

    for normalized_term in phrase_terms:
        position = _find_phrase_position(normalized_text, normalized_term)
        if position >= 0:
            return _build_snippet(normalized_text, position, len(normalized_term), max_chars=max_chars)

    for normalized_term in token_terms:
        position = _find_token_position(normalized_text, normalized_term)
        if position < 0:
            position = _find_substring_position(normalized_text, normalized_term)
        if position >= 0:
            return _build_snippet(normalized_text, position, len(normalized_term), max_chars=max_chars)

    fallback_text = _normalize_whitespace(original_text.replace("\r\n", " ").replace("\r", " ").replace("\t", " "))
    if len(fallback_text) <= max_chars:
        return fallback_text
    return f"{fallback_text[: max_chars - 3].rstrip()}..."


def _score_block(block: dict[str, Any], terms: list[dict[str, str]]) -> dict[str, Any] | None:
    """
    Возвращает match dict или None.
    """

    raw_text = block.get("text")
    if not raw_text:
        return None

    normalized_text = normalize_for_search(str(raw_text))
    if not normalized_text:
        return None

    text_tokens = tokenize_search_text(str(raw_text))
    text_token_set = set(text_tokens)
    section_text = normalize_for_search(str(block.get("section") or ""))
    section_tokens = set(tokenize_search_text(str(block.get("section") or "")))
    file_name_text = normalize_for_search(str(block.get("file_name") or ""))
    file_name_tokens = set(tokenize_search_text(str(block.get("file_name") or "")))

    text_score = 0.0
    bonus_score = 0.0
    matched_terms: list[str] = []
    match_reasons: list[str] = []

    def remember_match(raw_term: str | None, reason: str) -> None:
        if raw_term is not None and raw_term not in matched_terms:
            matched_terms.append(raw_term)
        match_reasons.append(reason)

    for term in terms:
        term_kind = term["kind"]
        normalized_term = term["normalized"]
        raw_term = term["raw"]

        if term_kind == "phrase":
            position = _find_phrase_position(normalized_text, normalized_term)
            if position < 0:
                continue
            text_score += 5.0
            remember_match(raw_term, "phrase:text")
            if section_text and normalized_term in section_text:
                bonus_score += 1.0
                match_reasons.append("phrase:section")
            if file_name_text and normalized_term in file_name_text:
                bonus_score += 0.5
                match_reasons.append("phrase:file_name")
            continue

        if normalized_term in text_token_set:
            position = _find_token_position(normalized_text, normalized_term)
            text_score += 2.0
            remember_match(raw_term, "token:text")
            if normalized_term in section_tokens:
                bonus_score += 0.5
                match_reasons.append("token:section")
            if normalized_term in file_name_tokens:
                bonus_score += 0.5
                match_reasons.append("token:file_name")
            continue

        if len(normalized_term) >= 3:
            position = _find_substring_position(normalized_text, normalized_term)
            if position < 0:
                continue
            text_score += 1.0
            remember_match(raw_term, "substring:text")
            if normalized_term in section_tokens:
                bonus_score += 0.5
                match_reasons.append("token:section")
            if normalized_term in file_name_tokens:
                bonus_score += 0.5
                match_reasons.append("token:file_name")

    if text_score == 0.0:
        return None

    snippet = make_snippet(str(raw_text), terms, max_chars=320)
    return {
        "score": float(text_score + bonus_score),
        "matched_terms": matched_terms,
        "match_reasons": match_reasons,
        "snippet": snippet,
        "block_ref": {
            "global_block_id": block.get("global_block_id"),
            "global_block_index": block.get("global_block_index"),
            "document_id": block.get("document_id"),
            "document_index": block.get("document_index"),
            "block_id": block.get("block_id"),
            "source_type": block.get("source_type"),
            "relative_path": block.get("relative_path"),
            "file_name": block.get("file_name"),
            "section": block.get("section"),
        },
        "block": dict(block),
    }


def search_blocks(
    blocks: list[dict],
    *,
    query: str | None = None,
    keywords: list[str] | None = None,
    top_k: int = 20,
    min_score: float = 1.0,
) -> dict:
    """
    Ищет релевантные blocks по query/keywords.
    """

    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if min_score < 0:
        raise ValueError("min_score must be >= 0")

    search_terms = build_search_terms(query=query, keywords=keywords)
    if not search_terms:
        raise ValueError("Provide query or keywords")

    matches: list[dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        match = _score_block(block, search_terms)
        if match is not None and match["score"] >= min_score:
            matches.append(match)

    def _sort_key(match: dict[str, Any]) -> tuple[float, float, float, str, str]:
        block_ref = match.get("block_ref") or {}
        global_block_index = block_ref.get("global_block_index")
        document_index = block_ref.get("document_index")
        file_name = block_ref.get("file_name")
        block_id = block_ref.get("block_id")
        return (
            -float(match.get("score", 0.0)),
            float(global_block_index) if isinstance(global_block_index, int) else float("inf"),
            float(document_index) if isinstance(document_index, int) else float("inf"),
            str(file_name) if file_name is not None else "",
            str(block_id) if block_id is not None else "",
        )

    matches.sort(key=_sort_key)
    matches_total = len(matches)
    returned_matches = matches[:top_k]

    return {
        "query": query,
        "keywords": [str(keyword) for keyword in (keywords or [])],
        "terms": search_terms,
        "matches": returned_matches,
        "stats": {
            "blocks_searched": len(blocks or []),
            "matches_total": matches_total,
            "matches_returned": len(returned_matches),
            "top_k": top_k,
            "min_score": float(min_score),
        },
    }


def _get_document_count(stats: Any) -> int | None:
    if isinstance(stats, dict) and "documents" in stats:
        value = stats.get("documents")
        return value if isinstance(value, int) else None
    return None


def search_tender_result(
    tender_result: dict,
    *,
    query: str | None = None,
    keywords: list[str] | None = None,
    top_k: int = 20,
    min_score: float = 1.0,
) -> dict:
    """
    Принимает результат read_tender_path() и ищет по tender_result["blocks"].
    """

    blocks = tender_result.get("blocks") or []
    search_result = search_blocks(blocks, query=query, keywords=keywords, top_k=top_k, min_score=min_score)
    search_result["input_path"] = tender_result.get("input_path")
    search_result["document_count"] = _get_document_count(tender_result.get("stats"))
    return search_result


def load_criteria(path: str | Path) -> list[dict]:
    """
    Загружает YAML/JSON criteria file.
    """

    criteria_path = Path(path)
    if not criteria_path.exists():
        raise FileNotFoundError(f"Criteria file does not exist: {criteria_path}")
    suffix = criteria_path.suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported criteria file extension: {criteria_path.suffix or '<none>'}")

    content = criteria_path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return []

    if suffix == ".json":
        data = json.loads(content)
    else:
        if yaml is None:
            raise RuntimeError("PyYAML is required to read non-empty YAML criteria files")
        data = yaml.safe_load(content)

    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if "criteria" in data:
            criteria = data.get("criteria")
            if criteria is None:
                return []
            if not isinstance(criteria, list):
                raise ValueError("criteria must be a list or null")
            return criteria

        criterion_keys = {"id", "criterion", "keywords", "query", "title", "name", "description"}
        if any(key in data for key in criterion_keys):
            return [data]
        raise ValueError("Unsupported criteria file format")

    raise ValueError("Unsupported criteria file format")


def _normalize_keywords_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        result: list[str] = []
        for part in value.split(","):
            normalized_part = normalize_for_search(part)
            if normalized_part:
                result.append(normalized_part)
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, (dict, list)):
                raise ValueError("keywords entries must be primitive values")
            normalized_item = normalize_for_search(str(item))
            if normalized_item:
                result.append(normalized_item)
        return result
    raise ValueError("keywords must be a list, string, or null")


def normalize_criterion(raw_criterion: dict, index: int) -> dict:
    """
    Приводит criterion к единому виду.
    """

    if not isinstance(raw_criterion, dict):
        raise ValueError("criterion must be a dict")

    def first_text(keys: tuple[str, ...]) -> str | None:
        for key in keys:
            if key not in raw_criterion:
                continue
            value = raw_criterion.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    criterion_id = first_text(("id", "criterion_id", "code")) or f"criterion_{index:03d}"
    criterion_text = first_text(("criterion", "title", "name", "description")) or ""
    query = first_text(("query",)) or (criterion_text or None)
    keywords_value = None
    for key in _SEARCH_SOURCE_FIELDS:
        if key in raw_criterion:
            keywords_value = raw_criterion.get(key)
            break

    normalized_keywords = _normalize_keywords_value(keywords_value)
    priority = first_text(("priority",))
    block = first_text(("block",))

    return {
        "criterion_id": criterion_id,
        "criterion": criterion_text,
        "query": query,
        "keywords": normalized_keywords,
        "priority": priority,
        "block": block,
        "raw": dict(raw_criterion),
    }


def search_by_criteria(
    tender_result: dict,
    criteria: list[dict],
    *,
    top_k_per_criterion: int = 10,
    min_score: float = 1.0,
) -> dict:
    """
    Ищет evidence blocks для каждого критерия.
    """

    if top_k_per_criterion < 1:
        raise ValueError("top_k_per_criterion must be >= 1")
    if min_score < 0:
        raise ValueError("min_score must be >= 0")

    normalized_criteria = [normalize_criterion(raw_criterion, index + 1) for index, raw_criterion in enumerate(criteria or [])]
    if not normalized_criteria:
        return {
            "input_path": tender_result.get("input_path"),
            "criteria_count": 0,
            "results": [],
            "stats": {
                "criteria": 0,
                "criteria_with_matches": 0,
                "matches_returned": 0,
            },
        }

    results: list[dict[str, Any]] = []
    criteria_with_matches = 0
    matches_returned_total = 0

    for normalized_criterion in normalized_criteria:
        query = normalized_criterion["query"]
        keywords = normalized_criterion["keywords"]
        if not query and not keywords:
            criterion_result = {
                "criterion_id": normalized_criterion["criterion_id"],
                "criterion": normalized_criterion["criterion"],
                "query": query,
                "keywords": keywords,
                "priority": normalized_criterion["priority"],
                "block": normalized_criterion["block"],
                "matches": [],
                "matches_total": 0,
                "matches_returned": 0,
            }
        else:
            search_result = search_tender_result(
                tender_result,
                query=query,
                keywords=keywords,
                top_k=top_k_per_criterion,
                min_score=min_score,
            )
            criterion_result = {
                "criterion_id": normalized_criterion["criterion_id"],
                "criterion": normalized_criterion["criterion"],
                "query": query,
                "keywords": keywords,
                "priority": normalized_criterion["priority"],
                "block": normalized_criterion["block"],
                "matches": search_result["matches"],
                "matches_total": search_result["stats"]["matches_total"],
                "matches_returned": search_result["stats"]["matches_returned"],
            }

        if criterion_result["matches_returned"] > 0:
            criteria_with_matches += 1
        matches_returned_total += criterion_result["matches_returned"]
        results.append(criterion_result)

    return {
        "input_path": tender_result.get("input_path"),
        "criteria_count": len(normalized_criteria),
        "results": results,
        "stats": {
            "criteria": len(normalized_criteria),
            "criteria_with_matches": criteria_with_matches,
            "matches_returned": matches_returned_total,
        },
    }


def search_tender_path(
    path: str | Path,
    *,
    query: str | None = None,
    keywords: list[str] | None = None,
    criteria_path: str | Path | None = None,
    top_k: int = 20,
    min_score: float = 1.0,
) -> dict:
    """
    Читает тендер через read_tender_path() и запускает search.
    """

    tender_result = read_tender_path(path)
    document_count = _get_document_count(tender_result.get("stats"))

    if criteria_path is not None:
        criteria = load_criteria(criteria_path)
        criteria_result = search_by_criteria(
            tender_result,
            criteria,
            top_k_per_criterion=top_k,
            min_score=min_score,
        )
        criteria_result["input_path"] = tender_result.get("input_path")
        criteria_result["document_count"] = document_count
        return criteria_result

    search_result = search_tender_result(
        tender_result,
        query=query,
        keywords=keywords,
        top_k=top_k,
        min_score=min_score,
    )
    search_result["input_path"] = tender_result.get("input_path")
    search_result["document_count"] = document_count
    return search_result


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--query")
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--criteria")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-score", type=float, default=1.0)
    args = parser.parse_args()

    if not args.criteria and not args.query and not args.keyword:
        parser.error("Provide --query, --keyword, or --criteria")

    result = search_tender_path(
        args.path,
        query=args.query,
        keywords=args.keyword,
        criteria_path=args.criteria,
        top_k=args.top_k,
        min_score=args.min_score,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
