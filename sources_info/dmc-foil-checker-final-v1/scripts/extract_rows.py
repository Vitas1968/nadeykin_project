#!/usr/bin/env python3
"""
extract_rows.py — Stream rows out of a large .xlsx WITHOUT loading it via openpyxl.

Why this exists:
  The target workbook (Detail sheet, ~41k rows, ~124k shared strings, heavy
  conditional formatting) crashes openpyxl's normal loader with an OOM kill.
  We parse the raw XML inside the .xlsx zip instead. This is the same
  "parse before reasoning" discipline used elsewhere: pull a clean, minimal
  JSONL out of the messy source first, then let everything downstream work
  on that.

What it extracts per row (only the columns the checks need):
  - row        : the spreadsheet row number (1-based, matches Excel)
  - dmc_ref    : AE  "DMC Code"        — the EXPECTED code (already on file)
  - photo_pack : AF  "Photo URL"       — full-pack photo (used for foil check)
  - photo_dmc  : AG  "Photo URL DMC"   — macro photo of the DataMatrix (decoded)
  - check_type : AH  "Тип проверки"    — e.g. "Проверка DMC"

AF / AG are stored as HYPERLINK("<url>","Ссылка") formulas, so the displayed
value is "Ссылка" and the real URL lives in the formula. We pull it from the
formula text.

The column letters are configurable via --col-* flags in case the layout
shifts between exports. Defaults match the 14_FMC.xlsx layout.

Usage:
  python extract_rows.py INPUT.xlsx -o rows.jsonl
  python extract_rows.py INPUT.xlsx -o rows.jsonl --sheet Detail
  python extract_rows.py INPUT.xlsx -o rows.jsonl --only-check-type "Проверка DMC"
  python extract_rows.py INPUT.xlsx -o rows.jsonl --limit 200

Output: JSONL, one JSON object per data row, to --out (default stdout).
"""
import argparse
import html
import json
import re
import sys
import zipfile

# ---- column letter <-> index helpers -------------------------------------

def col_to_idx(letters: str) -> int:
    """AE -> 31 (1-based)."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


# ---- locate the right sheet xml inside the zip ----------------------------

def find_sheet_path(z: zipfile.ZipFile, sheet_name: str) -> str:
    wb = z.read("xl/workbook.xml").decode("utf-8", "ignore")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "ignore")
    relmap = {}
    for rel in re.finditer(r'<Relationship\b([^>]+)>', rels):
        attrs = rel.group(1)
        id_m = re.search(r'\bId="([^"]+)"', attrs)
        tgt_m = re.search(r'\bTarget="([^"]+)"', attrs)
        if id_m and tgt_m:
            relmap[id_m.group(1)] = tgt_m.group(1)
    for m in re.finditer(r'<sheet[^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', wb):
        name, rid = m.group(1), m.group(2)
        if name == sheet_name:
            target = relmap.get(rid, "")
            if not target:
                break
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            return target
    raise SystemExit(f"Sheet {sheet_name!r} not found. "
                     f"Available: {re.findall(r'name=\"([^\"]+)\"', wb)}")


# ---- shared strings -------------------------------------------------------

def load_shared_strings(z: zipfile.ZipFile):
    """Return a list indexed by shared-string id. Handles rich-text runs."""
    try:
        raw = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
    except KeyError:
        return []
    out = []
    # Match paired <si>…</si> AND self-closing <si/>. Missing the latter would
    # shift every later index by one (off-by-one across the whole string table).
    for m in re.finditer(r"<si>(.*?)</si>|<si\s*/>", raw, re.S):
        si = m.group(1)
        if si is None:  # self-closing <si/> → empty string, keeps indices aligned
            out.append("")
            continue
        text = "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
        out.append(html.unescape(text))
    return out


# ---- per-cell value extraction --------------------------------------------

_HYPERLINK_RE = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.S)


def cell_value(cell_xml: str, attrs: str, sst):
    """
    Decode one <c>...</c> body into a Python string (or None).
    - t="s"   -> shared string lookup
    - t="str" -> formula result string; if formula is HYPERLINK(), return URL
    - inline / number -> raw <v> text
    """
    # formula present?
    fm = re.search(r"<f[^>]*>(.*?)</f>", cell_xml, re.S)
    if fm:
        link = _HYPERLINK_RE.search(fm.group(1))
        if link:
            return html.unescape(link.group(1))
    if 't="s"' in attrs:
        vm = re.search(r"<v>(\d+)</v>", cell_xml)
        if vm:
            idx = int(vm.group(1))
            if 0 <= idx < len(sst):
                return sst[idx]
        return None
    # inline string <is><t>...</t></is>
    im = re.search(r"<is>.*?<t[^>]*>(.*?)</t>.*?</is>", cell_xml, re.S)
    if im:
        return html.unescape(im.group(1))
    vm = re.search(r"<v>(.*?)</v>", cell_xml, re.S)
    if vm:
        return html.unescape(vm.group(1))
    return None


def parse_cell_ref(ref: str):
    """'AE231' -> ('AE', 231)"""
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (None, None)


# ---- main streaming loop --------------------------------------------------

def iter_rows(sheet_xml: str, sst, wanted_cols):
    """
    Yield dicts {colletter: value, '_row': rownum} for each <row>.
    wanted_cols: set of column letters to keep.

    NOTE: this variant takes the whole sheet XML as a string. For very large
    sheets prefer iter_rows_streaming(), which reads the sheet in chunks and
    keeps memory flat. Kept for compatibility / small inputs.
    """
    for rm in re.finditer(r'<row[^>]*?r="(\d+)"[^>]*?>(.*?)</row>', sheet_xml, re.S):
        rownum = int(rm.group(1))
        body = rm.group(2)
        yield _parse_row_body(rownum, body, sst, wanted_cols)


def _parse_row_body(rownum, body, sst, wanted_cols):
    """Parse one <row> body into a {col: value, '_row': n} dict."""
    row = {"_row": rownum}
    # Match BOTH self-closing empty cells (<c r=".." s=".."/>) and
    # paired cells (<c ..>inner</c>). The key bug to avoid: a greedy/lazy
    # (.*?)</c> after a self-closing cell will swallow following cells.
    for cm in re.finditer(
        r'<c\s+r="([A-Z]+\d+)"(?:([^>]*)/>|([^>]*)>(.*?)</c>)',
        body, re.S,
    ):
        ref = cm.group(1)
        col, _ = parse_cell_ref(ref)
        if col not in wanted_cols:
            continue
        if cm.group(2) is not None:
            row[col] = None  # self-closing => empty
        else:
            row[col] = cell_value(cm.group(4), cm.group(3), sst)
    return row


def iter_rows_streaming(zf, sheet_path, sst, wanted_cols, chunk_size=1 << 20):
    """
    Stream <row> elements out of the sheet XML WITHOUT loading the whole file.

    Why: on the reference workbook the decompressed sheet XML is tens of MB; on
    a 2x bigger export it'd be more. Reading it all into one string (and then
    running a regex over it) spikes memory. Here we read the zip member in ~1 MB
    chunks, keep a small buffer, and emit each complete <row>...</row> as soon as
    its closing tag arrives, discarding it from the buffer. Memory stays ~O(one
    row + one chunk), independent of sheet size.

    sst (shared strings) is still held in RAM, but that's bounded by the string
    table size, not by the number of data rows.
    """
    with zf.open(sheet_path) as fh:
        buf = ""
        # decode incrementally; xlsx XML is UTF-8
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            buf += chunk.decode("utf-8", "ignore")
            # emit every complete <row>...</row> currently in the buffer
            while True:
                start = buf.find("<row")
                if start == -1:
                    # keep only a small tail (in case "<ro" split across chunks)
                    if len(buf) > 16:
                        buf = buf[-16:]
                    break
                gt = buf.find(">", start)
                if gt == -1:
                    # opening tag split across chunks; wait for more
                    buf = buf[start:]
                    break
                if buf[gt - 1] == "/":
                    # self-closing empty row <row r=".."/> — MUST handle before
                    # searching for </row>, else we'd swallow the NEXT row's </row>
                    # and shift its data onto this empty row's number.
                    m = re.match(r'<row[^>]*?r="(\d+)"', buf[start:gt + 1])
                    buf = buf[gt + 1:]
                    if m:
                        yield _parse_row_body(int(m.group(1)), "", sst, wanted_cols)
                    continue
                end = buf.find("</row>", gt)
                if end == -1:
                    # incomplete row; drop everything before it, wait for more
                    buf = buf[start:]
                    break
                end_full = end + len("</row>")
                row_xml = buf[start:end_full]
                buf = buf[end_full:]
                m = re.match(r'<row[^>]*?r="(\d+)"', row_xml)
                if not m:
                    continue
                rownum = int(m.group(1))
                bodym = re.search(r"<row[^>]*?>(.*)</row>", row_xml, re.S)
                body = bodym.group(1) if bodym else ""
                yield _parse_row_body(rownum, body, sst, wanted_cols)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", help="Path to the .xlsx file")
    ap.add_argument("-o", "--out", default="-", help="Output JSONL path ('-' = stdout)")
    ap.add_argument("--sheet", default="Detail", help="Worksheet name (default: Detail)")
    ap.add_argument("--col-ref", default="AE", help="Column with expected DMC code")
    ap.add_argument("--col-photo-pack", default="AF", help="Column with full-pack photo URL")
    ap.add_argument("--col-photo-dmc", default="AG", help="Column with DMC macro photo URL")
    ap.add_argument("--col-check-type", default="AH", help="Column with check type")
    ap.add_argument("--header-row", type=int, default=1, help="Header row number to skip")
    ap.add_argument("--only-check-type", default=None,
                    help="Keep only rows whose check-type equals this string")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N data rows")
    ap.add_argument("--keep-empty", action="store_true",
                    help="Keep rows where dmc_ref AND photo_pack AND photo_dmc are all "
                         "empty. By default such rows are skipped — большие .xlsx часто "
                         "хранят тысячи пустых отформатированных строк (dimension не "
                         "ужимается при обрезке), и без этого они раздувают rows.jsonl.")
    args = ap.parse_args()

    cols = {
        "ref": args.col_ref.upper(),
        "pack": args.col_photo_pack.upper(),
        "dmc": args.col_photo_dmc.upper(),
        "ctype": args.col_check_type.upper(),
    }
    wanted = set(cols.values())

    z = zipfile.ZipFile(args.xlsx)
    sheet_path = find_sheet_path(z, args.sheet)
    sst = load_shared_strings(z)

    out = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8")
    written = 0
    skipped_empty = 0
    nonnull = {"dmc_ref": 0, "photo_pack": 0, "photo_dmc": 0}
    try:
        for row in iter_rows_streaming(z, sheet_path, sst, wanted):
            if row["_row"] <= args.header_row:
                continue
            ctype = row.get(cols["ctype"])
            if args.only_check_type is not None and ctype != args.only_check_type:
                continue
            rec = {
                "row": row["_row"],
                "dmc_ref": row.get(cols["ref"]),
                "photo_pack": row.get(cols["pack"]),
                "photo_dmc": row.get(cols["dmc"]),
                "check_type": ctype,
            }
            # Skip blank rows (no ref AND no photos): a truncated/big export keeps
            # thousands of empty formatted rows that would otherwise bloat output
            # and the downstream batch. --keep-empty disables this.
            if not args.keep_empty and not (rec["dmc_ref"] or rec["photo_pack"] or rec["photo_dmc"]):
                skipped_empty += 1
                continue
            for k in nonnull:
                if rec[k]:
                    nonnull[k] += 1
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
            if args.limit and written >= args.limit:
                break
    finally:
        if out is not sys.stdout:
            out.close()
    skip_note = f" (пропущено {skipped_empty} пустых строк)" if skipped_empty else ""
    sys.stderr.write(f"[extract_rows] wrote {written} rows from sheet {args.sheet!r}{skip_note}\n")

    # Sanity: a column that is empty for (almost) every row is the strongest
    # signal that the column letters / sheet are wrong for this export. Catch it
    # NOW, before a long downstream LLM run, instead of returning silent nulls.
    if written:
        col_letter = {"dmc_ref": cols["ref"], "photo_pack": cols["pack"],
                      "photo_dmc": cols["dmc"]}
        col_flag = {"dmc_ref": "--col-ref", "photo_pack": "--col-photo-pack",
                    "photo_dmc": "--col-photo-dmc"}
        for k, c in nonnull.items():
            sys.stderr.write(f"[extract_rows]   {k} ({col_letter[k]}): {c}/{written} непустых\n")
            if c <= written * 0.1:
                sys.stderr.write(
                    f"[extract_rows] WARNING: колонка {k} ({col_letter[k]}) пуста у "
                    f"{written - c}/{written} строк — вероятно, не та буква колонки "
                    f"или не тот лист. Сверь заголовок и при необходимости передай "
                    f"{col_flag[k]} / --sheet.\n"
                )


if __name__ == "__main__":
    main()
