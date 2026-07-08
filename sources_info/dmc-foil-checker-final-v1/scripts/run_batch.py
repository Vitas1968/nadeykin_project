#!/usr/bin/env python3
"""
run_batch.py — Orchestrate both checks over many rows, safely and resumably.

Pipeline per row (read from the JSONL produced by extract_rows.py):
  1. decode_dmc on photo_dmc (AG)  -> deterministic
        -> if nothing decodes, FALL BACK to the AF pack photo (same pack, другой
           ракурс) and try to decode the DataMatrix there.
        -> decode_source records which photo won: "AG" | "AF" | None.
        -> raw facts stored: decoded, AK_code_matches (decoded == AE?).
  2. check_foil on photo_pack (AF) -> multimodal LLM (optional, --foil)
        -> AI_foil_removed (True/False/None) with review flag.

  The AF pack photo is downloaded at most ONCE per row: the bytes fetched for the
  DMC fallback are reused for the foil check (and vice-versa).

This script stores RAW facts only. The final business cells (AI/AJ/AK with the
"1 = критерий не соблюдается" convention, plus the итоговая оценка AN) are
derived from these facts by evaluate.py at write time — one place, testable.

Why this script is built the way it is (41k rows, ~82k image downloads)
-----------------------------------------------------------------------
* CHECKPOINTING / IDEMPOTENCY. Results are appended to results.jsonl keyed by
  row number. On start we read what's already done and SKIP it. A crash at row
  30,000 costs nothing — rerun and it continues. This is the same idempotent
  design discipline used for long-running agent sessions.

* CONCURRENCY. Network is the bottleneck, not CPU. ONE thread pool (--workers,
  default 12) overlaps downloads + decodes (+ the foil LLM calls when --foil).
  There is no separate foil pool — keep --workers small (e.g. 2) when --foil
  hits a rate-limited local proxy; raise it (32+) for DMC-only download work.

* DISK CACHE is OPT-IN: OFF by default (no --cache-dir). Pass --cache-dir DIR
  only to debug a small sample — caching the full photo set burns tens of GB.
  Reruns don't re-fetch completed rows anyway (checkpointing skips them).

* COST CONTROL. The deterministic decode runs on everything cheaply. The LLM
  foil check is OPT-IN (--foil) and can be limited (--foil-limit) so you can
  validate on a sample before spending on all 41k. Run decode first on the full
  set; add --foil when you're ready.

Typical usage
-------------
  # 1) extract
  python extract_rows.py FMC.xlsx -o rows.jsonl

  # 2) sample run, both checks, 200 rows
  python run_batch.py rows.jsonl --limit 200 --foil --out results.jsonl

  # 3) full deterministic DMC pass (no LLM, high workers), then add foil later
  python run_batch.py rows.jsonl --out results.jsonl --workers 32
  python run_batch.py rows.jsonl --out results.jsonl --foil --workers 2

Output: results.jsonl, one record per row:
  {row, dmc_ref, af_present, decoded, decode_engine, decode_source, decode_error,
   AJ_photo_has_dmc, AK_code_matches,
   AI_foil_removed, foil_confidence, foil_reason, foil_review_needed, foil_error,
   check_type}
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from decode_dmc import decode_url, decode_image_bytes, fetch_bytes
from normalize_dmc import codes_match
from check_foil import check_foil_bytes


_print_lock = threading.Lock()
_write_lock = threading.Lock()


def load_done(out_path, require_foil=False):
    """Return set of row numbers already done in results.jsonl.

    With require_foil=True (a --foil run), a row counts as done ONLY if it has a
    foil result (foil_checked True). This lets a fast DMC-only pass (--workers 32,
    no --foil) fill all rows in minutes, then a later --foil loop top up just the
    foil for those rows WITHOUT being skipped — the foil pass re-queues DMC-only
    rows, appends complete records, and write_results keeps the last per row."""
    done = set()
    if not os.path.exists(out_path):
        return done
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if require_foil and not rec.get("foil_checked"):
                continue  # DMC-only row — not "done" for a foil pass
            done.add(rec["row"])
    return done


def process_row(rec, args):
    """Run the enabled checks for one row. Returns the result dict."""
    row = rec["row"]
    dmc_ref = rec.get("dmc_ref")
    photo_dmc = rec.get("photo_dmc")
    photo_pack = rec.get("photo_pack")

    out = {
        "row": row,
        "dmc_ref": dmc_ref,
        "af_present": bool(photo_pack),
        "decoded": None,
        "decode_engine": None,
        "decode_source": None,        # "AG" | "AF" | None
        "decode_error": None,
        "AJ_photo_has_dmc": None,
        "AK_code_matches": None,
        "AI_foil_removed": None,
        "foil_checked": False,
        "foil_confidence": None,
        "foil_reason": None,
        "foil_review_needed": None,
        "foil_error": None,
        "check_type": rec.get("check_type"),
        "t_row_s": None,
        "t_foil_s": None,
    }

    t0_row = time.monotonic()
    verify_ssl = not args.no_verify_ssl

    # AF (pack photo) bytes are fetched at most once and shared by the DMC
    # fallback decode and the foil check.
    af_bytes = None
    af_fetch_error = None

    def get_af_bytes():
        nonlocal af_bytes, af_fetch_error
        if af_bytes is None and af_fetch_error is None and photo_pack:
            try:
                af_bytes = fetch_bytes(photo_pack, cache_dir=args.cache_dir,
                                       verify_ssl=verify_ssl)
            except Exception as e:  # noqa: BLE001
                af_fetch_error = str(e)
        return af_bytes

    # ---- deterministic DMC decode: AG first ----
    dres = decode_url(photo_dmc, cache_dir=args.cache_dir, verify_ssl=verify_ssl)
    decode_source = "AG" if dres["decoded"] else None
    decode_error = dres["error"]

    # ---- fallback: try to decode the DMC off the AF pack photo ----
    if not dres["decoded"] and photo_pack:
        b = get_af_bytes()
        if b:
            d2 = decode_image_bytes(b)
            if d2["decoded"]:
                dres = d2
                decode_source = "AF"
            else:
                # surface both failures so a low decode-rate is debuggable
                decode_error = f"AG:{decode_error or 'no_barcode_found'}; AF:{d2.get('error')}"
        elif af_fetch_error:
            decode_error = f"AG:{decode_error or 'no_barcode_found'}; AF_download:{af_fetch_error}"

    out["decoded"] = dres["decoded"]
    out["decode_engine"] = dres["engine"]
    out["decode_source"] = decode_source
    out["decode_error"] = decode_error
    out["AJ_photo_has_dmc"] = bool(dres["decoded"])
    if dres["decoded"]:
        out["AK_code_matches"] = codes_match(dmc_ref, dres["decoded"],
                                              ignore_case=args.ignore_case)
    else:
        # No decode anywhere => cannot confirm match. Left None (not False) so
        # evaluate can keep "нет DMC" (AJ) distinct from "не совпадает" (AK).
        out["AK_code_matches"] = None

    # ---- foil check (AI), optional ----
    if args.foil:
        t0_foil = time.monotonic()
        if not photo_pack:
            fres = {"foil_removed": None, "confidence": 0.0, "reason": "",
                    "review_needed": True, "error": "empty_url"}
        else:
            b = get_af_bytes()
            if b is None:
                fres = {"foil_removed": None, "confidence": 0.0, "reason": "",
                        "review_needed": True,
                        "error": f"download_error: {af_fetch_error}"}
            else:
                mime = "image/png" if b[:4] == b"\x89PNG" else "image/jpeg"
                fres = check_foil_bytes(
                    b, model=args.model, base_url=args.base_url,
                    api_key=args.api_key, min_confidence=args.min_confidence,
                    mime=mime, verify_ssl=verify_ssl,
                    max_image_side=args.max_image_side,
                    image_quality=args.image_quality,
                    reasoning_effort=args.reasoning_effort,
                )
        out["t_foil_s"] = round(time.monotonic() - t0_foil, 2)
        out["foil_checked"] = True
        out["AI_foil_removed"] = fres.get("foil_removed")
        out["foil_confidence"] = fres.get("confidence")
        out["foil_reason"] = fres.get("reason")
        out["foil_review_needed"] = fres.get("review_needed")
        out["foil_error"] = fres.get("error")

    out["t_row_s"] = round(time.monotonic() - t0_row, 2)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rows", help="rows.jsonl from extract_rows.py")
    ap.add_argument("--out", default="results.jsonl", help="Append-mode results JSONL")
    ap.add_argument("--cache-dir", default=None,
                    help="Optional image download cache dir. OFF by default: "
                         "images live in RAM only for the duration of each row, "
                         "so the run uses ~0 extra disk. Enable only for debugging "
                         "small samples — on the full set it would consume tens of GB.")
    ap.add_argument("--workers", type=int, default=12,
                    help="Thread pool size for decode pass")
    ap.add_argument("--window-factor", type=int, default=2,
                    help="Max futures in flight = workers * this. Keeps RAM flat "
                         "regardless of dataset size (default 2).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N not-yet-done rows")
    ap.add_argument("--ignore-case", action="store_true",
                    help="Case-insensitive code comparison")
    ap.add_argument("--no-verify-ssl", action="store_true",
                    help="Disable SSL verification for internal hosts")
    # foil / LLM
    ap.add_argument("--foil", action="store_true",
                    help="Also run the multimodal foil check (AI). Costs LLM calls.")
    ap.add_argument("--foil-limit", type=int, default=None,
                    help="Run foil check on at most N rows (decode still runs on all selected)")
    ap.add_argument("--model", default=os.environ.get("LITELLM_MODEL", "dots.mocr"),
                    help="Foil vision model (default: dots.mocr — what the default proxy "
                         "key serves; override via --model or LITELLM_MODEL, e.g. gemini-2.5-flash)")
    ap.add_argument("--base-url", default=os.environ.get("LITELLM_BASE_URL", "http://87.242.111.7:32200/v1"))
    ap.add_argument("--api-key", default=os.environ.get("LITELLM_API_KEY", "sk-SGZ4XJt7Bf_FZ5ytXAfYBA"))
    ap.add_argument("--min-confidence", type=float, default=0.75)
    ap.add_argument("--max-image-side", type=int, default=1600,
                    help="Downscale foil-photo long side to this many px before sending "
                         "(no crop). 0 = send original untouched. Default 1600.")
    ap.add_argument("--image-quality", type=int, default=85,
                    help="JPEG quality for the downscaled foil photo (default 85)")
    ap.add_argument("--reasoning-effort", default=None,
                    choices=["none", "low", "medium", "high"],
                    help="Thinking effort — GEMINI ONLY. 'none' on gemini-2.5-flash is "
                         "~6x cheaper at ≈same accuracy. Do NOT pass with the local "
                         "proxy (dots.mocr) — it returns HTTP 400. Omit by default.")
    ap.add_argument("--progress-every", type=int, default=100)
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="Wall-clock budget: stop submitting new rows after this many "
                         "seconds, finish in-flight, flush and exit. Results are "
                         "checkpointed, so re-running the SAME command resumes. Use this "
                         "to stay under a shell/tool timeout WITHOUT backgrounding — call "
                         "in a foreground loop until results == rows.")
    args = ap.parse_args()

    if args.foil and (not args.model or not args.base_url):
        ap.error("--foil needs --model and --base-url (or LITELLM_MODEL/LITELLM_BASE_URL)")

    # load work + skip done
    all_rows = []
    with open(args.rows, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_rows.append(json.loads(line))
    done = load_done(args.out, require_foil=args.foil)
    todo = [r for r in all_rows if r["row"] not in done]
    if args.limit:
        todo = todo[:args.limit]

    sys.stderr.write(
        f"[run_batch] total={len(all_rows)} done={len(done)} "
        f"todo={len(todo)} foil={'on' if args.foil else 'off'}\n"
    )
    if not todo:
        sys.stderr.write("[run_batch] nothing to do.\n")
        return

    # foil budget: the first N rows of the FULL input (file order) get the LLM
    # call — NOT the first N of `todo`. This makes --foil-limit resume-stable:
    # `todo` shrinks on each --max-seconds resume, so `todo[:n]` would pick a
    # DIFFERENT set each pass and run paid foil on up to K×N rows. Anchoring on
    # all_rows[:n] keeps the foil set fixed; already-done rows are skipped anyway.
    foil_allow = set()
    if args.foil:
        n = args.foil_limit if args.foil_limit is not None else len(all_rows)
        foil_allow = {r["row"] for r in all_rows[:n]}

    out_f = open(args.out, "a", encoding="utf-8")
    processed = 0
    errors = 0
    t_start = time.monotonic()
    foil_times = []  # per-row foil latencies for stats

    def write(rec):
        with _write_lock:
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()

    def task(rec):
        # respect per-row foil budget
        local_args = argparse.Namespace(**vars(args))
        if rec["row"] not in foil_allow:
            local_args.foil = False
        return process_row(rec, local_args)

    def _fmt_eta(remaining, elapsed, done):
        if done == 0:
            return "ETA=?"
        rate = done / elapsed
        eta_s = remaining / rate
        if eta_s < 60:
            return f"ETA={eta_s:.0f}s"
        return f"ETA={eta_s/60:.1f}m"

    # Bounded sliding window: keep at most (workers * window_factor) futures
    # in flight at any moment, instead of submitting all rows up front. This
    # keeps RAM flat regardless of dataset size — 200 rows or 2,000,000 rows
    # use the same memory, because we never hold more than a window's worth of
    # pending Futures (and the few images their worker threads are decoding).
    # The submit-as-you-drain pattern is what makes this O(window) not O(rows).
    max_inflight = max(args.workers * args.window_factor, args.workers)
    row_iter = iter(todo)
    budget_over = False

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            inflight = {}  # future -> row

            # prime the window
            for _ in range(max_inflight):
                try:
                    r = next(row_iter)
                except StopIteration:
                    break
                inflight[ex.submit(task, r)] = r

            while inflight:
                # wait for the next finished future, then immediately top up
                done_set, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in done_set:
                    r = inflight.pop(fut)
                    try:
                        rec = fut.result()
                        if rec.get("t_foil_s") is not None:
                            foil_times.append(rec["t_foil_s"])
                    except Exception as e:  # noqa: BLE001
                        # full-shape record so downstream (evaluate/summarize) sees
                        # the same keys as a normal row, not a sparse crash stub
                        rec = {"row": r["row"], "dmc_ref": r.get("dmc_ref"),
                               "af_present": bool(r.get("photo_pack")),
                               "decoded": None, "decode_source": None,
                               "decode_error": f"task_crash: {e}",
                               "AJ_photo_has_dmc": None, "AK_code_matches": None,
                               "AI_foil_removed": None, "foil_checked": False,
                               "check_type": r.get("check_type")}
                        errors += 1
                    write(rec)
                    processed += 1
                    if processed % args.progress_every == 0:
                        elapsed = time.monotonic() - t_start
                        rate = processed / elapsed
                        remaining = len(todo) - processed
                        eta = _fmt_eta(remaining, elapsed, processed)
                        foil_avg = (
                            f", foil_avg={sum(foil_times)/len(foil_times):.1f}s"
                            if foil_times else ""
                        )
                        with _print_lock:
                            sys.stderr.write(
                                f"[run_batch] {processed}/{len(todo)} done "
                                f"({rate:.2f}r/s, elapsed={elapsed:.0f}s, {eta}"
                                f", errors={errors}, inflight={len(inflight)}"
                                f"{foil_avg})\n"
                            )
                    # wall-clock budget: stop submitting new rows, drain in-flight
                    if (args.max_seconds and not budget_over
                            and time.monotonic() - t_start >= args.max_seconds):
                        budget_over = True
                        with _print_lock:
                            sys.stderr.write(
                                f"[run_batch] бюджет {args.max_seconds:.0f}s исчерпан "
                                f"({processed}/{len(todo)}) — доделываю in-flight и выхожу; "
                                f"перезапусти ТУ ЖЕ команду, чекпоинтинг продолжит\n")
                    # refill the slot this future just vacated (unless budget is over)
                    if not budget_over:
                        try:
                            nr = next(row_iter)
                            inflight[ex.submit(task, nr)] = nr
                        except StopIteration:
                            pass
    finally:
        out_f.close()

    elapsed = time.monotonic() - t_start
    rate = processed / elapsed if elapsed > 0 else 0
    foil_avg = f", foil_avg={sum(foil_times)/len(foil_times):.1f}s/row" if foil_times else ""
    foil_total = f", foil_total={sum(foil_times):.0f}s" if foil_times else ""
    sys.stderr.write(
        f"[run_batch] finished: {processed} rows in {elapsed:.1f}s "
        f"({rate:.2f}r/s{foil_avg}{foil_total}), errors={errors}\n"
    )
    sys.stderr.write(f"[run_batch] results -> {args.out}\n")


if __name__ == "__main__":
    main()
