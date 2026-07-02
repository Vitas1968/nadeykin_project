#!/usr/bin/env python3
"""
normalize_dmc.py — Make two DMC strings comparable before deciding match/no-match.

The problem this solves
-----------------------
The reference code in the spreadsheet (column AE) is stored as a flat string of
printable characters, e.g.:

    00000046288929l_?hz=RACoA0IGr        (always 29 chars, starts 00000046)

But a barcode DECODER reading the DataMatrix off a photo may hand back the same
logical code wearing different clothes:

  * GS1 application-identifier separators (FNC1 / ASCII 29 / the literal "<GS>")
    inserted between fields,
  * a leading ]d2 / ]D2 symbology identifier,
  * surrounding whitespace or a trailing newline,
  * sometimes the GS rendered as the visible characters chr(29) or "\\x1d".

If we compared raw strings we'd get false "MISMATCH" results on codes that are
actually identical. So both sides get pushed through the SAME normalizer, and
only then compared. This is the deterministic ground-truth step — no model
judgement is involved in deciding whether two codes are equal.

What normalization does
------------------------
1. Strip a leading symbology identifier (]d2, ]Q3, etc.).
2. Remove GS / FNC1 control bytes (ASCII 29) and common textual renderings of
   them ("<GS>", "\\x1d", "\\u001d").
3. Strip ALL whitespace (leading, trailing, internal — these never appear in a
   valid Chestny ZNAK code).
4. Return the cleaned string. Comparison is case-SENSITIVE by default because
   the serial portion is case-significant (l vs L matter); use --ignore-case to
   override if a downstream export proves otherwise.

It does NOT try to "fix" a genuinely different code. If after cleaning the two
strings differ, that's a real mismatch and must be reported as such.

CLI
---
    echo '<code>' | python normalize_dmc.py            # normalize one code from stdin
    python normalize_dmc.py --compare REF DECODED       # exit 0 if match, 1 if not
    python normalize_dmc.py --self-test                 # run built-in checks

As a library
------------
    from normalize_dmc import normalize, codes_match
    normalize(raw) -> str
    codes_match(ref, decoded) -> bool
"""
import argparse
import re
import sys

# Leading GS1 symbology identifier like ]d2, ]Q3, ]C1 ...
_SYMBOLOGY_ID = re.compile(r"^\][A-Za-z]\d")

# Textual renderings of the GS / group separator that decoders sometimes emit.
_GS_TEXT = ("<GS>", "\\x1d", "\\u001d", "{GS}", "<FNC1>")


def normalize(raw, ignore_case=False):
    if raw is None:
        return ""
    s = str(raw)

    # 1. leading symbology identifier
    s = _SYMBOLOGY_ID.sub("", s)

    # 2a. real GS / FNC1 control byte (ASCII 29) and a few nearby control chars
    s = s.replace(chr(29), "").replace(chr(0x1E), "").replace(chr(0x04), "")

    # 2b. textual renderings of GS
    for token in _GS_TEXT:
        s = s.replace(token, "")

    # 3. all whitespace
    s = re.sub(r"\s+", "", s)

    if ignore_case:
        s = s.upper()
    return s


def codes_match(ref, decoded, ignore_case=False):
    """True iff the two codes are equal after normalization. Empty decoded never matches."""
    nd = normalize(decoded, ignore_case)
    if not nd:
        return False
    return normalize(ref, ignore_case) == nd


# Optional structural sanity check for Chestny ZNAK tobacco codes seen in this
# dataset (29 printable chars, GTIN-ish 00000046 prefix). This is advisory only
# — used to flag "the reference itself looks wrong", never to reject a match.
_EXPECTED_LEN = 29
_EXPECTED_PREFIX = "00000046"


def looks_like_reference(code):
    n = normalize(code)
    return len(n) == _EXPECTED_LEN and n.startswith(_EXPECTED_PREFIX)


def _self_test():
    cases = [
        # (ref, decoded, should_match)
        ("00000046288929l_?hz=RACoA0IGr",
         "00000046288929l_?hz=RACoA0IGr", True),
        # decoder added a symbology id + GS
        ("00000046288929l_?hz=RACoA0IGr",
         "]d200000046288929l_?hz=RACoA0IGr", True),
        ("00000046288929l_?hz=RACoA0IGr",
         "00000046288929" + chr(29) + "l_?hz=RACoA0IGr", True),
        # trailing newline / spaces
        ("00000046288929l_?hz=RACoA0IGr",
         "00000046288929l_?hz=RACoA0IGr\n", True),
        ("00000046288929l_?hz=RACoA0IGr",
         "  00000046288929l_?hz=RACoA0IGr  ", True),
        # textual <GS>
        ("00000046288929l_?hz=RACoA0IGr",
         "00000046288929<GS>l_?hz=RACoA0IGr", True),
        # genuinely different
        ("00000046288929l_?hz=RACoA0IGr",
         "00000046288646t-NO.B5AC=UmY9d", False),
        # empty decode never matches
        ("00000046288929l_?hz=RACoA0IGr", "", False),
        ("00000046288929l_?hz=RACoA0IGr", None, False),
        # case sensitivity matters by default (l vs L)
        ("00000046288929l_?hz=RACoA0IGr",
         "00000046288929L_?hz=RACoA0IGr", False),
    ]
    ok = True
    for ref, dec, exp in cases:
        got = codes_match(ref, dec)
        flag = "OK " if got == exp else "FAIL"
        if got != exp:
            ok = False
        shown = (dec[:40] + "…") if dec and len(dec) > 40 else repr(dec)
        print(f"  [{flag}] expect={exp} got={got}  decoded={shown}")
    print("self-test:", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--compare", nargs=2, metavar=("REF", "DECODED"),
                    help="Compare two codes; exit 0 if match else 1")
    ap.add_argument("--ignore-case", action="store_true",
                    help="Case-insensitive comparison (off by default)")
    ap.add_argument("--self-test", action="store_true", help="Run built-in tests")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if _self_test() else 1)

    if args.compare:
        ref, dec = args.compare
        match = codes_match(ref, dec, args.ignore_case)
        print("MATCH" if match else "MISMATCH")
        print("  ref     :", repr(normalize(ref, args.ignore_case)))
        print("  decoded :", repr(normalize(dec, args.ignore_case)))
        sys.exit(0 if match else 1)

    # default: normalize stdin
    data = sys.stdin.read().strip()
    print(normalize(data, args.ignore_case))


if __name__ == "__main__":
    main()
