from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from pypdf import PasswordType, PdfReader

_SUPPORTED_EXTENSIONS = {".pdf"}
_WHITESPACE_RE = re.compile(r"\s+")
_ONLY_NUMBER_RE = re.compile(r"^\d+$")
_SERVICE_LINE_RE = re.compile(
    r"^(?:стр\.?|страница|лист|page)\s+\d+(?:\s*(?:из|of)\s*\d+)?$",
    re.IGNORECASE,
)
_SECTION_NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.\s|\d+(?:\.\d+)+\s|раздел\s+\d+\b|приложение\s+\d+\b|приложение\s*№\s*\d+\b)", re.IGNORECASE)


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _normalize_line(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.replace("\t", " ")).strip()


def _ensure_pdf_path(path: str | Path) -> Path:
    pdf_path = Path(path)
    if pdf_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension for PDF reader: {pdf_path.suffix or '<none>'}")
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    return pdf_path


def _is_service_line(text: str) -> bool:
    stripped = text.strip()
    return bool(_ONLY_NUMBER_RE.fullmatch(stripped) or _SERVICE_LINE_RE.fullmatch(stripped))


def _is_section_line(text: str) -> bool:
    if len(text) > 120 or _is_service_line(text):
        return False
    if any(ch.isalpha() for ch in text) and text.upper() == text:
        return True
    return bool(_SECTION_NUMBER_RE.match(text))


def _split_paragraphs(raw_text: str) -> list[str]:
    normalized_lines = [_normalize_line(line) for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    paragraphs: list[str] = []
    current_lines: list[str] = []

    for line in normalized_lines:
        if not line:
            if current_lines:
                paragraph = _normalize_text(" ".join(current_lines))
                if paragraph:
                    paragraphs.append(paragraph)
                current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        paragraph = _normalize_text(" ".join(current_lines))
        if paragraph:
            paragraphs.append(paragraph)

    return paragraphs


def _build_paragraph_block(
    *,
    source_path: str,
    paragraph_index: int,
    page_number: int,
    section: str | None,
    text: str,
) -> dict[str, Any]:
    return {
        "source_path": source_path,
        "source_type": "pdf",
        "block_id": f"p{paragraph_index:06d}",
        "block_type": "paragraph",
        "section": section,
        "text": text,
        "table_index": None,
        "row_index": None,
        "cell_values": None,
        "page_number": page_number,
    }


def _open_pdf_reader(path: Path) -> PdfReader:
    try:
        reader = PdfReader(path)
    except Exception as exc:  # pragma: no cover - defensive wrapper around pypdf
        raise RuntimeError(f"Unable to open PDF file: {path}") from exc

    if reader.is_encrypted:
        try:
            decrypt_result = reader.decrypt("")
        except Exception as exc:  # pragma: no cover - defensive wrapper around pypdf
            raise RuntimeError(f"Unable to decrypt PDF file with empty password: {path}") from exc
        if decrypt_result == PasswordType.NOT_DECRYPTED:
            raise RuntimeError(f"Unable to decrypt PDF file with empty password: {path}")

    return reader


def _read_pdf_content(path: str | Path) -> tuple[list[dict[str, Any]], int, int]:
    pdf_path = _ensure_pdf_path(path)
    reader = _open_pdf_reader(pdf_path)
    source_path = str(pdf_path.resolve())

    blocks: list[dict[str, Any]] = []
    paragraph_index = 0
    empty_pages = 0
    current_section: str | None = None

    try:
        page_count = len(reader.pages)
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                raw_text = page.extract_text()
            except Exception as exc:  # pragma: no cover - defensive wrapper around pypdf page extraction
                raise RuntimeError(f"Unable to extract text from PDF page {page_number}: {pdf_path}") from exc

            if raw_text is None:
                empty_pages += 1
                continue

            paragraphs = _split_paragraphs(raw_text)
            page_blocks: list[dict[str, Any]] = []
            for paragraph_text in paragraphs:
                if _is_service_line(paragraph_text):
                    continue
                if _is_section_line(paragraph_text):
                    current_section = paragraph_text
                paragraph_index += 1
                page_blocks.append(
                    _build_paragraph_block(
                        source_path=source_path,
                        paragraph_index=paragraph_index,
                        page_number=page_number,
                        section=current_section,
                        text=paragraph_text,
                    )
                )
            if not page_blocks:
                empty_pages += 1
                continue
            blocks.extend(page_blocks)
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Unable to read PDF file: {pdf_path}") from exc

    return blocks, page_count, empty_pages


def extract_pdf_blocks(path: str | Path) -> list[dict[str, Any]]:
    blocks, _, _ = _read_pdf_content(path)
    return blocks


def read_pdf(path: str | Path) -> dict[str, Any]:
    blocks, pages, empty_pages = _read_pdf_content(path)
    source_path = blocks[0]["source_path"] if blocks else str(Path(path).resolve())
    return {
        "source_path": source_path,
        "source_type": "pdf",
        "blocks": blocks,
        "full_text": "\n".join(block["text"] for block in blocks if block["text"]),
        "stats": {
            "pages": pages,
            "empty_pages": empty_pages,
            "paragraphs": len(blocks),
            "blocks": len(blocks),
        },
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    result = read_pdf(args.path)
    print("blocks:", result["stats"]["blocks"])
    print("pages:", result["stats"]["pages"])
    print("empty_pages:", result["stats"]["empty_pages"])
    print("paragraphs:", result["stats"]["paragraphs"])
    print(result["full_text"][:1000])
