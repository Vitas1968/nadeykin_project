#!/usr/bin/env python3
"""
evaluate.py — Single source of truth that turns the raw per-row facts produced by
run_batch.py into the BUSINESS cell values the audit spreadsheet expects.

Value convention (per the audit spec — note this is NOT the old Да/Нет):
  AI / AJ / AK  ->  "1" = критерий НЕ соблюдается (проблема);  "" (пусто) = соблюдается
  AN            ->  "1" = валидный  |  "0" = не валидный

Columns (headers unchanged, polarity flipped so that 1 == problem):
  AI "Фольга снята с пачки"               -> "1" если фольга НЕ снята
  AJ "На Photo URL есть фото DMC"          -> "1" если DMC не распознан (нет DMC)
  AK "DMC код совпадает с кодом на пачке"  -> "1" если распознанный DMC ≠ эталон AE
  AN  итоговая оценка                      -> "0" если хоть один из AI/AJ/AK == "1",
                                              либо AF пустой, либо AE пустой; иначе "1"

DMC recognition is decided upstream in run_batch.py: decode the AG macro photo
first; if nothing decodes, fall back to the AF pack photo (same pack, другой
ракурс); if neither decodes -> "нет DMC". `decode_source` records which photo won.

Foil-unknown policy (model unsure / error -> foil_removed is None):
  "problem" (default): AI="1" and the row is not valid (AN=0). Conservative for
      an audit — we never pass a pack whose foil we could not confirm removed.
  "ok": AI="" — unknown foil does not by itself fail the row.
  Either way the row is flagged for human review and the foil_status detail column
  distinguishes "не снята" (confident) from "не определено" (unknown).
"""
from normalize_dmc import normalize

ONE = "1"
EMPTY = ""


def _present(v):
    """True if a value is a non-empty, non-whitespace string/number."""
    return v is not None and str(v).strip() != ""


def evaluate_row(rec, foil_unknown="problem"):
    """Map one run_batch result record to {AI,AJ,AK,AN,...diagnostics}.

    Expected rec fields (all optional / tolerant of missing):
      dmc_ref            expected code on file (column AE)
      decoded            recognized DMC text or None
      decode_source      'AG' | 'AF' | None  (which photo decoded)
      AK_code_matches    bool | None  (decoded == AE after normalization)
      AI_foil_removed    bool | None  (True=снята, False=не снята, None=не определено)
      foil_confidence    float | None
      foil_review_needed bool
      af_present         bool         (AF pack-photo URL present)
    """
    dmc_ref = rec.get("dmc_ref")
    decoded = rec.get("decoded")
    decode_source = rec.get("decode_source")          # 'AG' | 'AF' | None
    ak_match = rec.get("AK_code_matches")             # bool | None
    foil_removed = rec.get("AI_foil_removed")         # bool | None

    ae_present = _present(dmc_ref) and bool(normalize(dmc_ref))
    af_present = bool(rec.get("af_present"))
    dmc_found = _present(decoded)

    reasons = []

    # --- AJ: "нет DMC" ------------------------------------------------------
    if dmc_found:
        AJ = EMPTY
    else:
        AJ = ONE
        reasons.append("DMC не найден (ни на AG, ни на AF)")

    # --- AK: "DMC не совпадает" --------------------------------------------
    # Only a real, recognized-but-different code is a mismatch. "Нет DMC" is AJ,
    # not AK; "нет эталона" is handled by the AE rule on AN, not as a mismatch.
    if not dmc_found or not ae_present:
        AK = EMPTY
    elif ak_match is True:
        AK = EMPTY
    elif ak_match is False:
        AK = ONE
        reasons.append("DMC не совпадает с эталоном AE")
    else:
        AK = EMPTY

    # --- AI: "фольга не снята" ---------------------------------------------
    if foil_removed is True:
        AI = EMPTY
        foil_status = "снята"
    elif foil_removed is False:
        AI = ONE
        foil_status = "не снята"
        reasons.append("фольга не снята")
    else:
        # foil_removed is None — split WHY: a data-plumbing failure (no AF url /
        # download failed / model error) must not look the same as a genuine
        # "model is unsure", otherwise a broken pipeline reads as a bad batch.
        ferr = (rec.get("foil_error") or "")
        if not rec.get("foil_checked"):
            foil_status = "не проверялась"
        elif ferr.startswith("empty_url"):
            foil_status = "нет фото (AF пуст)"
        elif ferr.startswith("download_error"):
            foil_status = "ошибка загрузки фото"
        elif ferr.startswith("litellm_error") or ferr == "bad_schema":
            foil_status = "ошибка модели"
        else:
            foil_status = "не определено (модель)"
        if foil_unknown == "problem":
            AI = ONE
            reasons.append(f"фольга: {foil_status}")
        else:
            AI = EMPTY

    # --- AN: итоговая оценка ------------------------------------------------
    an_reasons = []
    if not af_present:
        an_reasons.append("в AF нет ссылки")
    if not ae_present:
        an_reasons.append("AE пусто")
    if ONE in (AI, AJ, AK):
        an_reasons.append("есть невыполненный критерий AI–AK")
    AN = "0" if an_reasons else "1"

    review_needed = bool(rec.get("foil_review_needed")) or AK == ONE or AJ == ONE

    return {
        "AI": AI, "AJ": AJ, "AK": AK, "AN": AN,
        "dmc_found": dmc_found,
        "decode_source": decode_source or "",
        "decoded": decoded or "",
        "dmc_ref": dmc_ref or "",
        "foil_status": foil_status,
        "foil_confidence": rec.get("foil_confidence"),
        "ae_present": ae_present,
        "af_present": af_present,
        "reasons": reasons,
        "an_reasons": an_reasons,
        "review_needed": review_needed,
    }


# ---------------------------------------------------------------------------
# self-test — covers every branch of the spec
# ---------------------------------------------------------------------------

def _self_test():
    REF = "00000046288929l_?hz=RACoA0IGr"
    cases = [
        # name, rec, foil_unknown, expected (AI, AJ, AK, AN)
        ("all good (AG)",
         {"dmc_ref": REF, "decoded": REF, "decode_source": "AG",
          "AK_code_matches": True, "AI_foil_removed": True, "af_present": True},
         "problem", ("", "", "", "1")),
        ("all good via AF fallback",
         {"dmc_ref": REF, "decoded": REF, "decode_source": "AF",
          "AK_code_matches": True, "AI_foil_removed": True, "af_present": True},
         "problem", ("", "", "", "1")),
        ("DMC mismatch -> AK=1",
         {"dmc_ref": REF, "decoded": "00000046288646t-NO.B5AC=UmY9d",
          "decode_source": "AG", "AK_code_matches": False,
          "AI_foil_removed": True, "af_present": True},
         "problem", ("", "", "1", "0")),
        ("no DMC -> AJ=1, AK empty",
         {"dmc_ref": REF, "decoded": None, "decode_source": None,
          "AK_code_matches": None, "AI_foil_removed": True, "af_present": True},
         "problem", ("", "1", "", "0")),
        ("foil not removed -> AI=1",
         {"dmc_ref": REF, "decoded": REF, "decode_source": "AG",
          "AK_code_matches": True, "AI_foil_removed": False, "af_present": True},
         "problem", ("1", "", "", "0")),
        ("foil unknown, policy=problem -> AI=1",
         {"dmc_ref": REF, "decoded": REF, "decode_source": "AG",
          "AK_code_matches": True, "AI_foil_removed": None,
          "foil_review_needed": True, "af_present": True},
         "problem", ("1", "", "", "0")),
        ("foil unknown, policy=ok -> AI empty, AN=1",
         {"dmc_ref": REF, "decoded": REF, "decode_source": "AG",
          "AK_code_matches": True, "AI_foil_removed": None,
          "foil_review_needed": True, "af_present": True},
         "ok", ("", "", "", "1")),
        ("AF empty -> AN=0",
         {"dmc_ref": REF, "decoded": REF, "decode_source": "AG",
          "AK_code_matches": True, "AI_foil_removed": True, "af_present": False},
         "ok", ("", "", "", "0")),
        ("AE empty -> AN=0, AK empty even if decoded",
         {"dmc_ref": "", "decoded": REF, "decode_source": "AG",
          "AK_code_matches": False, "AI_foil_removed": True, "af_present": True},
         "ok", ("", "", "", "0")),
        ("everything wrong",
         {"dmc_ref": "", "decoded": None, "decode_source": None,
          "AK_code_matches": None, "AI_foil_removed": False, "af_present": False},
         "problem", ("1", "1", "", "0")),
    ]
    ok = True
    for name, rec, policy, exp in cases:
        r = evaluate_row(rec, foil_unknown=policy)
        got = (r["AI"], r["AJ"], r["AK"], r["AN"])
        flag = "OK " if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"  [{flag}] {name}: AI/AJ/AK/AN = {got}  (expected {exp})")
    print("self-test:", "PASSED" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if _self_test() else 1)
