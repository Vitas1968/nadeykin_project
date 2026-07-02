from __future__ import annotations

import argparse
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

_SUPPORTED_EXTENSIONS = {".xlsx"}
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class RowData:
    values: list[str]
    refs: list[str]
    excel_row_index: int


def _normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _ensure_xlsx_path(path: str | Path) -> Path:
    xlsx_path = Path(path)
    if xlsx_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension for XLSX reader: {xlsx_path.suffix or '<none>'}")
    if not xlsx_path.exists():
        raise FileNotFoundError(f"XLSX file does not exist: {xlsx_path}")
    return xlsx_path


def _format_float(value: float) -> str:
    if value.is_integer():
        formatted = str(int(value))
    else:
        formatted = format(value, "f").rstrip("0").rstrip(".")
    if formatted == "-0":
        formatted = "0"
    return formatted


def _normalize_cell_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = _normalize_text(value)
        return text or None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _format_float(value)
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dt.time):
        return value.strftime("%H:%M:%S")
    text = _normalize_text(str(value))
    return text or None


def _sheet_is_visible(sheet) -> bool:
    return getattr(sheet, "sheet_state", "visible") == "visible"


def _iter_row_data(sheet) -> list[RowData]:
    rows: list[RowData] = []
    for excel_row_index, row in enumerate(sheet.iter_rows(values_only=False), start=1):
        cell_values: list[str] = []
        cell_refs: list[str] = []
        for cell in row:
            value = _normalize_cell_value(cell.value)
            if value is None:
                continue
            cell_values.append(value)
            cell_refs.append(cell.coordinate)
        if cell_values:
            rows.append(RowData(values=cell_values, refs=cell_refs, excel_row_index=excel_row_index))
    return rows


def _build_row_block(
    *,
    source_path: str,
    sheet_name: str,
    sheet_index: int,
    row_index: int,
    excel_row_index: int,
    values: list[str],
    refs: list[str],
    section: str | None,
) -> dict[str, Any]:
    return {
        "source_path": source_path,
        "source_type": "xlsx",
        "block_id": f"s{sheet_index:06d}_r{row_index:06d}",
        "block_type": "table_row",
        "section": section,
        "text": " | ".join(values),
        "table_index": sheet_index,
        "row_index": row_index,
        "cell_values": values,
        "sheet_name": sheet_name,
        "sheet_index": sheet_index,
        "excel_row_index": excel_row_index,
        "cell_refs": refs,
    }


def _load_workbook(path: Path):
    try:
        return load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # pragma: no cover - defensive wrapper around openpyxl
        raise RuntimeError(f"Unable to open XLSX file: {path}") from exc


def _read_xlsx_content(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    xlsx_path = _ensure_xlsx_path(path)
    workbook = _load_workbook(xlsx_path)
    source_path = str(xlsx_path.resolve())

    blocks: list[dict[str, Any]] = []
    visible_sheet_count = 0

    try:
        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]
            if not _sheet_is_visible(sheet):
                continue

            visible_sheet_count += 1
            section: str | None = None
            row_index = 0

            for row_data in _iter_row_data(sheet):
                row_index += 1
                if len(row_data.values) == 1 and len(row_data.values[0]) <= 120:
                    section = row_data.values[0]
                blocks.append(
                    _build_row_block(
                        source_path=source_path,
                        sheet_name=sheet_name,
                        sheet_index=visible_sheet_count,
                        row_index=row_index,
                        excel_row_index=row_data.excel_row_index,
                        values=row_data.values,
                        refs=row_data.refs,
                        section=section,
                    )
                )
    except Exception as exc:  # pragma: no cover - defensive wrapper around openpyxl/worksheet iteration
        raise RuntimeError(f"Unable to read XLSX file: {xlsx_path}") from exc
    finally:
        workbook.close()

    return blocks, visible_sheet_count


def extract_xlsx_blocks(path: str | Path) -> list[dict[str, Any]]:
    blocks, _ = _read_xlsx_content(path)
    return blocks


def read_xlsx(path: str | Path) -> dict[str, Any]:
    blocks, visible_sheets = _read_xlsx_content(path)
    source_path = blocks[0]["source_path"] if blocks else str(Path(path).resolve())
    return {
        "source_path": source_path,
        "source_type": "xlsx",
        "blocks": blocks,
        "full_text": "\n".join(block["text"] for block in blocks if block["text"]),
        "stats": {
            "sheets": visible_sheets,
            "rows": len(blocks),
            "blocks": len(blocks),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    result = read_xlsx(args.path)
    print("blocks:", result["stats"]["blocks"])
    print("sheets:", result["stats"]["sheets"])
    print("rows:", result["stats"]["rows"])
    print(result["full_text"][:1000])
