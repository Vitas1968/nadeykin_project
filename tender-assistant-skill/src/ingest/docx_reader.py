from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

_WHITESPACE_RE = re.compile(r"\s+")
_DOCX_EXTENSION = ".docx"


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _ensure_docx_path(path: str | Path) -> Path:
    docx_path = Path(path)
    if docx_path.suffix.lower() != _DOCX_EXTENSION:
        raise ValueError(f"Unsupported file extension for DOCX reader: {docx_path.suffix or '<none>'}")
    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX file does not exist: {docx_path}")
    return docx_path


def _load_document(path: Path):
    try:
        return Document(path)
    except Exception as exc:  # pragma: no cover - defensive wrapper around python-docx
        raise RuntimeError(f"Unable to open DOCX file: {path}") from exc


def _is_heading(paragraph: Paragraph) -> bool:
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    return style_name.startswith("Heading") or "Заголовок" in style_name


def _iter_body_blocks(document) -> list[tuple[str, Any]]:
    blocks: list[tuple[str, Any]] = []
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            blocks.append(("paragraph", Paragraph(child, document)))
        elif child.tag == qn("w:tbl"):
            blocks.append(("table", Table(child, document)))
    return blocks


def _extract_cell_text(cell) -> str:
    parts = []
    for child in cell._tc.iterchildren():
        if child.tag == qn("w:p"):
            paragraph_text = _normalize_text(Paragraph(child, cell).text)
            if paragraph_text:
                parts.append(paragraph_text)
        elif child.tag == qn("w:tbl"):
            continue
    return _normalize_text(" ".join(parts))


def _collect_row_cell_values(row) -> list[str]:
    cell_values: list[str] = []
    seen_tc_ids: set[int] = set()
    for cell in row.cells:
        tc_id = id(cell._tc)
        if tc_id in seen_tc_ids:
            continue
        seen_tc_ids.add(tc_id)
        cell_text = _extract_cell_text(cell)
        if cell_text:
            cell_values.append(cell_text)
    return cell_values


def _read_docx_content(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    docx_path = _ensure_docx_path(path)
    document = _load_document(docx_path)
    source_path = str(docx_path.resolve())

    blocks: list[dict[str, Any]] = []
    current_section: str | None = None
    paragraph_index = 0
    table_index = 0

    for kind, item in _iter_body_blocks(document):
        if kind == "paragraph":
            paragraph = item
            text = _normalize_text(paragraph.text)
            if not text:
                continue
            if _is_heading(paragraph):
                current_section = text
            paragraph_index += 1
            blocks.append(
                {
                    "source_path": source_path,
                    "source_type": "docx",
                    "block_id": f"p{paragraph_index:06d}",
                    "block_type": "paragraph",
                    "section": current_section,
                    "text": text,
                    "table_index": None,
                    "row_index": None,
                    "cell_values": None,
                }
            )
            continue

        table = item
        table_index += 1
        blocks.extend(_extract_table_rows(table, source_path, table_index, current_section))

    return blocks, table_index


def _extract_table_rows(table: Table, source_path: str, table_index: int, current_section: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(table.rows, start=1):
        cell_values = _collect_row_cell_values(row)
        if not cell_values:
            continue
        rows.append(
            {
                "source_path": source_path,
                "source_type": "docx",
                "block_id": f"t{table_index:06d}_r{row_index:06d}",
                "block_type": "table_row",
                "section": current_section,
                "text": " | ".join(cell_values),
                "table_index": table_index,
                "row_index": row_index,
                "cell_values": cell_values,
            }
        )
    return rows


def extract_docx_blocks(path: str | Path) -> list[dict[str, Any]]:
    blocks, _ = _read_docx_content(path)
    return blocks


def read_docx(path: str | Path) -> dict[str, Any]:
    blocks, table_count = _read_docx_content(path)
    normalized_source_path = blocks[0]["source_path"] if blocks else str(Path(path).resolve())

    return {
        "source_path": normalized_source_path,
        "source_type": "docx",
        "blocks": blocks,
        "full_text": "\n".join(block["text"] for block in blocks if block["text"]),
        "stats": {
            "paragraphs": sum(1 for block in blocks if block["block_type"] == "paragraph"),
            "tables": table_count,
            "table_rows": sum(1 for block in blocks if block["block_type"] == "table_row"),
            "blocks": len(blocks),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    result = read_docx(args.path)
    print("blocks:", result["stats"]["blocks"])
    print("paragraphs:", result["stats"]["paragraphs"])
    print("tables:", result["stats"]["tables"])
    print("table_rows:", result["stats"]["table_rows"])
    print(result["full_text"][:1000])
