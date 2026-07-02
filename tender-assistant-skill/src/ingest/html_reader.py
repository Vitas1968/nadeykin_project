from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_SUPPORTED_EXTENSIONS = {".html", ".htm"}
_IGNORED_TAGS = {"script", "style", "noscript"}
_VOID_TAGS = {
    "br",
    "hr",
    "img",
    "meta",
    "link",
    "input",
    "area",
    "base",
    "col",
    "embed",
    "param",
    "source",
    "track",
    "wbr",
}
_BLOCK_LEVEL_TAGS = {
    "p",
    "div",
    "li",
    "section",
    "article",
    "header",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_WHITESPACE_RE = re.compile(r"\s+")
_META_CHARSET_RE = re.compile(br"<meta\b[^>]*charset\s*=\s*['\"]?\s*([A-Za-z0-9._:-]+)", re.IGNORECASE)


@dataclass(slots=True)
class BlockContext:
    tag: str
    parts: list[str]


class HtmlTenderParser(HTMLParser):
    def __init__(self, source_path: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_path = source_path
        self.blocks: list[dict[str, Any]] = []
        self.current_section: str | None = None
        self.paragraph_index = 0
        self.table_index = 0
        self.table_depth = 0
        self.current_table_index = 0
        self.current_table_row_index = 0
        self.in_row = False
        self.in_cell = False
        self.current_row_cells: list[str] = []
        self.current_cell_parts: list[str] | None = None
        self.ignore_depth = 0
        self.block_stack: list[BlockContext] = []
        self.fallback_parts: list[str] = []

    def handle_comment(self, data: str) -> None:  # noqa: D401 - intentionally ignored
        return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self.ignore_depth > 0:
            return
        if self.table_depth > 1:
            if self.in_cell and self.current_cell_parts is not None:
                self.current_cell_parts.append(data)
            return
        if self.table_depth == 1:
            if self.in_cell and self.current_cell_parts is not None:
                self.current_cell_parts.append(data)
            return
        self._append_text_outside_table(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            self.ignore_depth += 1
            return
        if self.ignore_depth > 0:
            return
        if tag in _VOID_TAGS:
            if tag == "br":
                _append_space_to_current_buffer(self)
            return
        if tag == "table":
            self._start_table()
            return
        if self.table_depth > 0:
            if self.table_depth == 1 and tag in {"tr", "td", "th"}:
                self._handle_table_start(tag)
            return
        if tag in _BLOCK_LEVEL_TAGS:
            self._flush_fallback()
            self.block_stack.append(BlockContext(tag=tag, parts=[]))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            if self.ignore_depth > 0:
                self.ignore_depth -= 1
            return
        if self.ignore_depth > 0:
            return
        if tag == "table":
            self._end_table()
            return
        if self.table_depth > 0:
            if self.table_depth == 1 and tag in {"td", "th"}:
                self._close_cell()
                return
            if self.table_depth == 1 and tag == "tr":
                self._end_row()
                return
            return
        if tag in _BLOCK_LEVEL_TAGS:
            self._close_block_context(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def close(self) -> None:
        super().close()
        self._finalize_eof()

    def _append_text_outside_table(self, text: str) -> None:
        if self.block_stack:
            self.block_stack[-1].parts.append(text)
        else:
            self.fallback_parts.append(text)

    def _emit_paragraph(self, raw_text: str, section: str | None) -> None:
        text = _normalize_text(raw_text)
        if not text:
            return
        self.paragraph_index += 1
        self.blocks.append(
            {
                "source_path": self.source_path,
                "source_type": "html",
                "block_id": f"p{self.paragraph_index:06d}",
                "block_type": "paragraph",
                "section": section,
                "text": text,
                "table_index": None,
                "row_index": None,
                "cell_values": None,
            }
        )

    def _flush_fallback(self) -> None:
        if not self.fallback_parts:
            return
        self._emit_paragraph("".join(self.fallback_parts), self.current_section)
        self.fallback_parts = []

    def _flush_open_block_contexts(self) -> None:
        for context in reversed(self.block_stack):
            self._emit_context(context)
            context.parts = []

    def _close_block_context(self, tag: str) -> None:
        matching_index = None
        for index in range(len(self.block_stack) - 1, -1, -1):
            if self.block_stack[index].tag == tag:
                matching_index = index
                break
        if matching_index is None:
            return
        while len(self.block_stack) - 1 > matching_index:
            context = self.block_stack.pop()
            self._emit_context(context)
        context = self.block_stack.pop()
        self._emit_context(context)

    def _start_table(self) -> None:
        if self.table_depth == 0:
            self._flush_open_block_contexts()
            self._flush_fallback()
            self.table_index += 1
            self.current_table_index = self.table_index
            self.current_table_row_index = 0
            self.current_row_cells = []
            self.current_cell_parts = None
            self.in_row = False
            self.in_cell = False
        self.table_depth += 1

    def _end_table(self) -> None:
        if self.table_depth == 0:
            return
        if self.table_depth == 1:
            self._finalize_top_level_table()
            self.current_table_index = 0
            self.current_table_row_index = 0
            self.current_row_cells = []
            self.current_cell_parts = None
            self.in_row = False
            self.in_cell = False
        self.table_depth -= 1

    def _handle_table_start(self, tag: str) -> None:
        if tag == "tr":
            self._start_row()
            return
        if tag in {"td", "th"}:
            if not self.in_row:
                self._start_row()
            elif self.in_cell:
                self._close_cell()
            self.in_cell = True
            self.current_cell_parts = []

    def _start_row(self) -> None:
        if self.in_row:
            self._close_cell()
            self._end_row()
        self.current_table_row_index += 1
        self.in_row = True
        self.in_cell = False
        self.current_row_cells = []
        self.current_cell_parts = None

    def _close_cell(self) -> None:
        if not self.in_cell or self.current_cell_parts is None:
            self.in_cell = False
            self.current_cell_parts = None
            return
        cell_text = _normalize_text("".join(self.current_cell_parts))
        if cell_text:
            self.current_row_cells.append(cell_text)
        self.in_cell = False
        self.current_cell_parts = None

    def _end_row(self) -> None:
        if not self.in_row:
            return
        if self.in_cell:
            self._close_cell()
        if self.current_row_cells:
            self.blocks.append(
                {
                    "source_path": self.source_path,
                    "source_type": "html",
                    "block_id": f"t{self.current_table_index:06d}_r{self.current_table_row_index:06d}",
                    "block_type": "table_row",
                    "section": self.current_section,
                    "text": " | ".join(self.current_row_cells),
                    "table_index": self.current_table_index,
                    "row_index": self.current_table_row_index,
                    "cell_values": list(self.current_row_cells),
                }
            )
        self.current_row_cells = []
        self.in_row = False
        self.in_cell = False
        self.current_cell_parts = None

    def _finalize_top_level_table(self) -> None:
        if self.in_cell:
            self._close_cell()
        if self.in_row:
            self._end_row()

    def _emit_context(self, context: BlockContext) -> None:
        text = _normalize_text("".join(context.parts))
        if not text:
            return
        if context.tag in _HEADING_TAGS:
            self.current_section = text
        self._emit_paragraph(text, self.current_section)

    def _finalize_eof(self) -> None:
        if self.table_depth > 0:
            if self.current_table_index > 0:
                self._finalize_top_level_table()
            self.table_depth = 0
            self.current_table_index = 0
            self.current_table_row_index = 0
            self.current_row_cells = []
            self.current_cell_parts = None
            self.in_row = False
            self.in_cell = False
        if self.block_stack:
            self._flush_open_block_contexts()
            self.block_stack = []
        if self.fallback_parts:
            self._flush_fallback()


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _ensure_html_path(path: str | Path) -> Path:
    html_path = Path(path)
    if html_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension for HTML reader: {html_path.suffix or '<none>'}")
    if not html_path.exists():
        raise FileNotFoundError(f"HTML file does not exist: {html_path}")
    return html_path


def _detect_charset(raw_bytes: bytes) -> str | None:
    head = raw_bytes[:8192]
    match = _META_CHARSET_RE.search(head)
    if match:
        charset = match.group(1).decode("ascii", errors="ignore").strip().strip("\"'/>;").lower()
        if charset:
            return charset
    return None


def _append_space_to_current_buffer(parser: HtmlTenderParser) -> None:
    if parser.table_depth > 1:
        return
    if parser.table_depth == 1:
        if parser.in_cell and parser.current_cell_parts is not None:
            parser.current_cell_parts.append(" ")
        return
    if parser.block_stack:
        parser.block_stack[-1].parts.append(" ")
    else:
        parser.fallback_parts.append(" ")


def _decode_html(raw_bytes: bytes, source_path: Path) -> str:
    candidates: list[str] = []
    detected_charset = _detect_charset(raw_bytes)
    for encoding in (detected_charset, "utf-8", "cp1251"):
        if encoding and encoding.lower() not in {candidate.lower() for candidate in candidates}:
            candidates.append(encoding)

    last_exc: Exception | None = None
    for encoding in candidates:
        try:
            return raw_bytes.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            last_exc = exc

    if last_exc is None:
        last_exc = UnicodeDecodeError("utf-8", b"", 0, 1, "unable to decode HTML content")
    raise RuntimeError(f"Unable to decode HTML file: {source_path}") from last_exc


def _parse_html(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    html_path = _ensure_html_path(path)
    source_path = str(html_path.resolve())
    raw_bytes = html_path.read_bytes()
    decoded_html = _decode_html(raw_bytes, html_path)

    parser = HtmlTenderParser(source_path)
    try:
        parser.feed(decoded_html)
        parser.close()
    except Exception as exc:
        raise RuntimeError(f"Unable to parse HTML file: {html_path}") from exc

    return parser.blocks, parser.table_index


def extract_html_blocks(path: str | Path) -> list[dict[str, Any]]:
    blocks, _ = _parse_html(path)
    return blocks


def read_html(path: str | Path) -> dict[str, Any]:
    blocks, table_count = _parse_html(path)
    source_path = blocks[0]["source_path"] if blocks else str(Path(path).resolve())
    return {
        "source_path": source_path,
        "source_type": "html",
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
    result = read_html(args.path)
    print("blocks:", result["stats"]["blocks"])
    print("paragraphs:", result["stats"]["paragraphs"])
    print("tables:", result["stats"]["tables"])
    print("table_rows:", result["stats"]["table_rows"])
    print(result["full_text"][:1000])
