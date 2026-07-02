from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

_SUPPORTED_EXTENSIONS = {".docx", ".html", ".htm", ".xlsx", ".pdf"}
_SUPPORTED_SOURCE_TYPES = ("docx", "html", "xlsx", "pdf")

try:
    from ingest.docx_reader import read_docx
    from ingest.html_reader import read_html
    from ingest.pdf_reader import read_pdf
    from ingest.xlsx_reader import read_xlsx
except ModuleNotFoundError:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from ingest.docx_reader import read_docx
    from ingest.html_reader import read_html
    from ingest.pdf_reader import read_pdf
    from ingest.xlsx_reader import read_xlsx

_READER_BY_SOURCE_TYPE: dict[str, Callable[[str | Path], dict[str, Any]]] = {
    "docx": read_docx,
    "html": read_html,
    "xlsx": read_xlsx,
    "pdf": read_pdf,
}


def _is_temporary_office_file(path: str | Path) -> bool:
    """
    True, если Path(path).name.startswith("~$").
    Не проверяет существование файла.
    """

    return Path(path).name.startswith("~$")


def is_supported_file(path: str | Path) -> bool:
    """
    True для .docx/.html/.htm/.xlsx/.pdf.
    Проверка case-insensitive.
    """

    file_path = Path(path)
    if _is_temporary_office_file(file_path):
        return False
    return file_path.suffix.lower() in _SUPPORTED_EXTENSIONS


def get_source_type(path: str | Path) -> str:
    """
    Возвращает source_type для поддерживаемого файла.
    Для temporary Office files и неподдерживаемых расширений выбрасывает ValueError.
    """

    file_path = Path(path)
    if _is_temporary_office_file(file_path):
        raise ValueError(f"Temporary Office files are not supported: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".docx":
        return "docx"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".xlsx":
        return "xlsx"
    if suffix == ".pdf":
        return "pdf"

    raise ValueError(f"Unsupported file extension for tender reader: {file_path.suffix or '<none>'}")


def iter_tender_files(path: str | Path) -> list[Path]:
    """
    Если path — файл: вернуть [path].
    Если path — папка: рекурсивно вернуть список файлов в стабильном порядке.
    Если path не существует: FileNotFoundError.
    Если path существует, но это не файл и не папка: ValueError.
    """

    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Input path does not exist: {root}")
    if root.is_file():
        return [root]
    if not root.is_dir():
        raise ValueError(f"Input path is neither a file nor a directory: {root}")

    files = [candidate for candidate in root.rglob("*") if candidate.is_file()]
    def _sort_key(candidate: Path) -> tuple[str, str]:
        relative_path = candidate.relative_to(root).as_posix()
        return relative_path.lower(), relative_path

    files.sort(key=_sort_key)
    return files


def _read_reader_payload(path: Path) -> dict[str, Any]:
    source_type = get_source_type(path)
    reader = _READER_BY_SOURCE_TYPE[source_type]
    reader_result = reader(path)
    return {
        "source_path": str(path.resolve()),
        "source_type": source_type,
        "file_name": path.name,
        "blocks": [dict(block) for block in reader_result.get("blocks", [])],
        "full_text": reader_result.get("full_text", ""),
        "stats": dict(reader_result.get("stats", {})),
    }


def read_tender_file(path: str | Path) -> dict[str, Any]:
    """
    Читает один поддерживаемый файл и возвращает dict reader-а,
    дополненный только контекстно-независимой metadata.
    """

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {file_path}")
    if _is_temporary_office_file(file_path):
        raise ValueError(f"Temporary Office files are not supported: {file_path}")
    return _read_reader_payload(file_path)


def _build_relative_path(root: Path, file_path: Path) -> str:
    return file_path.relative_to(root).as_posix()


def _build_skipped_file_item(*, root: Path, file_path: Path, reason: str) -> dict[str, Any]:
    return {
        "path": str(file_path.resolve()),
        "relative_path": _build_relative_path(root, file_path),
        "reason": reason,
        "extension": file_path.suffix.lower(),
    }


def _build_failed_file_item(*, root: Path, file_path: Path, source_type: str, exc: Exception) -> dict[str, Any]:
    return {
        "path": str(file_path.resolve()),
        "relative_path": _build_relative_path(root, file_path),
        "source_type": source_type,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }


def _enrich_document_payload(
    payload: dict[str, Any],
    *,
    document_id: str,
    document_index: int,
    relative_path: str | None,
    global_block_index_start: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = dict(payload)
    document["document_id"] = document_id
    document["document_index"] = document_index
    document["relative_path"] = relative_path

    enriched_blocks: list[dict[str, Any]] = []
    for local_block_offset, block in enumerate(payload.get("blocks", [])):
        global_block_index = global_block_index_start + local_block_offset
        enriched_block = dict(block)
        enriched_block["document_id"] = document_id
        enriched_block["document_index"] = document_index
        enriched_block["global_block_id"] = f"b{global_block_index:06d}"
        enriched_block["global_block_index"] = global_block_index
        enriched_block["relative_path"] = relative_path
        enriched_block["file_name"] = payload["file_name"]
        enriched_blocks.append(enriched_block)

    document["blocks"] = enriched_blocks
    return document, enriched_blocks


def read_tender_path(path: str | Path) -> dict[str, Any]:
    """
    Читает один файл или папку с тендерными документами.
    """

    input_path = Path(path)
    files = iter_tender_files(input_path)
    is_folder = input_path.is_dir()
    input_path_text = str(path)

    if not is_folder:
        single_file = files[0]
        if _is_temporary_office_file(single_file):
            raise ValueError(f"Temporary Office files are not supported: {single_file}")
        if not is_supported_file(single_file):
            raise ValueError(f"Unsupported file extension for tender reader: {single_file.suffix or '<none>'}")

        file_payload = read_tender_file(single_file)
        document, blocks = _enrich_document_payload(
            file_payload,
            document_id="d000001",
            document_index=1,
            relative_path=None,
            global_block_index_start=1,
        )
        return {
            "input_path": input_path_text,
            "documents": [document],
            "blocks": blocks,
            "full_text": document["full_text"],
            "stats": {
                "documents": 1,
                "blocks": len(blocks),
                "by_type": {source_type: 1 if source_type == document["source_type"] else 0 for source_type in _SUPPORTED_SOURCE_TYPES},
                "skipped": 0,
                "failed": 0,
            },
            "skipped_files": [],
            "failed_files": [],
        }

    documents: list[dict[str, Any]] = []
    all_blocks: list[dict[str, Any]] = []
    skipped_files: list[dict[str, Any]] = []
    failed_files: list[dict[str, Any]] = []
    document_index = 0
    global_block_index = 0
    by_type = {source_type: 0 for source_type in _SUPPORTED_SOURCE_TYPES}

    for file_path in files:
        if _is_temporary_office_file(file_path):
            skipped_files.append(_build_skipped_file_item(root=input_path, file_path=file_path, reason="temporary_office_file"))
            continue
        if not is_supported_file(file_path):
            skipped_files.append(_build_skipped_file_item(root=input_path, file_path=file_path, reason="unsupported_extension"))
            continue

        source_type = get_source_type(file_path)
        try:
            file_payload = read_tender_file(file_path)
        except Exception as exc:
            failed_files.append(_build_failed_file_item(root=input_path, file_path=file_path, source_type=source_type, exc=exc))
            continue

        document_index += 1
        document_id = f"d{document_index:06d}"
        relative_path = _build_relative_path(input_path, file_path)
        document, enriched_blocks = _enrich_document_payload(
            file_payload,
            document_id=document_id,
            document_index=document_index,
            relative_path=relative_path,
            global_block_index_start=global_block_index + 1,
        )
        documents.append(document)
        all_blocks.extend(enriched_blocks)
        global_block_index += len(enriched_blocks)
        by_type[file_payload["source_type"]] += 1

    return {
        "input_path": input_path_text,
        "documents": documents,
        "blocks": all_blocks,
        "full_text": "\n\n".join(document["full_text"] for document in documents if document["full_text"]),
        "stats": {
            "documents": len(documents),
            "blocks": len(all_blocks),
            "by_type": by_type,
            "skipped": len(skipped_files),
            "failed": len(failed_files),
        },
        "skipped_files": skipped_files,
        "failed_files": failed_files,
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--json", action="store_true", help="Print compact JSON result")
    args = parser.parse_args()

    result = read_tender_path(args.path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("documents:", result["stats"]["documents"])
        print("blocks:", result["stats"]["blocks"])
        print("skipped:", result["stats"]["skipped"])
        print("failed:", result["stats"]["failed"])
        print("by_type:", result["stats"]["by_type"])
        print(result["full_text"][:1000])
