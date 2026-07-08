#!/usr/bin/env python3
"""
decode_dmc.py — Decode the DataMatrix barcode from a macro photo (column AG).

This is the DETERMINISTIC ground truth for two of the three checks:
  * AJ "На Photo URL есть фото DMC"      -> did ANY DataMatrix decode? yes/no
  * AK "DMC код совпадает с кодом на пачке" -> does decoded == reference (AE)?

No LLM is involved here. A barcode either decodes to exact bytes or it does not.
That is the whole point — we never ask a model to "read" a 2D code, because it
would hallucinate. We use a real decoder (zxing-cpp) and report only what it
actually returns.

Engine choice
-------------
Primary: zxing-cpp (`zxingcpp`). It installs as a self-contained wheel with NO
system libraries required, which matters on locked-down / air-gapped corporate
hosts where you can't apt-install libdmtx. It supports DataMatrix natively.

Optional fallback: pylibdmtx, IF the system has libdmtx0 available. It catches a
few codes zxing misses. It is tried only when present; its absence is not an
error. (On Debian/Ubuntu: `apt-get install libdmtx0`.)

Robustness for real-world macro photos
--------------------------------------
Field photos are blurry, tilted, glare-y, and variably sized. A single decode
attempt on the raw image misses a lot. We try a small ladder of cheap image
transforms and stop at the first success:
  1. raw grayscale
  2. upscale 2x (helps tiny codes)
  3. Otsu threshold (binarize)
  4. CLAHE contrast boost + threshold
  5. light Gaussian blur then threshold (kills sensor noise)
Each is fed to zxing with TryHarder/TryRotate enabled.

Caching
-------
Downloaded images are cached on disk keyed by a hash of the URL, so re-runs and
retries do not re-download. The decode result itself is also cacheable by the
orchestrator via JSONL checkpointing (see run_batch.py).

CLI
---
    python decode_dmc.py --url "<AG photo url>"
    python decode_dmc.py --file path/to/image.jpeg
    python decode_dmc.py --url "<url>" --cache-dir /tmp/dmc_cache --debug
    python decode_dmc.py --self-test          # generate a code, decode it back

Library
-------
    from decode_dmc import decode_image_bytes, decode_url
    decode_url(url, cache_dir=...) -> dict {decoded, engine, ok, error, attempts}
"""
import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.request

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

import zxingcpp

# optional fallback
try:
    from pylibdmtx import pylibdmtx as _pylibdmtx
    _HAVE_PYLIBDMTX = True
except Exception:
    _HAVE_PYLIBDMTX = False


DEFAULT_UA = "Mozilla/5.0 (compatible; dmc-foil-checker/1.0)"


# ----------------------------------------------------------------------------
# download (with disk cache)
# ----------------------------------------------------------------------------

def _cache_path(cache_dir, url):
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return os.path.join(cache_dir, h + ".img")


def fetch_bytes(url, cache_dir=None, timeout=20, retries=2, verify_ssl=True):
    """Download image bytes, caching to disk. Returns bytes or raises."""
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cp = _cache_path(cache_dir, url)
        if os.path.exists(cp) and os.path.getsize(cp) > 0:
            with open(cp, "rb") as f:
                return f.read()

    ctx = None
    if not verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                data = r.read()
            if cache_dir and data:
                with open(_cache_path(cache_dir, url), "wb") as f:
                    f.write(data)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            # Don't sleep after the final attempt — that's pure dead time before
            # we raise. On an unreachable host this saved sleep is ~4.5s/fetch,
            # and with two fetches per row (AG + AF fallback) it dominated the
            # ~20s/row seen on a batch where every download failed.
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    if last is None:  # retries<1 → loop never ran; don't `raise None`
        raise ValueError("fetch_bytes: retries must be >= 1")
    raise last


# ----------------------------------------------------------------------------
# image -> grayscale ndarray, plus a ladder of preprocessing variants
# ----------------------------------------------------------------------------

def _bytes_to_gray(data):
    if cv2 is None:
        raise RuntimeError("opencv (cv2) is required; pip install opencv-python-headless")
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("could not decode image bytes (corrupt or unsupported format)")
    return img


def _enhanced_variants(region, prefix):
    """Upscaled + strong-contrast variants for one region (whole image or a tile).
    Targets the hard residue: small AND low-contrast laser-etched codes (light dots
    on a dark pack). Each region is upscaled 2x/3x and pushed through Otsu, strong
    CLAHE+Otsu, unsharp+Otsu and adaptive threshold — the combo that recovered 31 of
    53 otherwise-undecodable field photos in testing."""
    yield f"{prefix}_raw", region
    for f in (2, 3):
        u = cv2.resize(region, (region.shape[1] * f, region.shape[0] * f),
                       interpolation=cv2.INTER_CUBIC)
        yield f"{prefix}_up{f}", u
        _, o = cv2.threshold(u, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        yield f"{prefix}_up{f}_otsu", o
        eq = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(8, 8)).apply(u)
        _, ce = cv2.threshold(eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        yield f"{prefix}_up{f}_clahe", ce
        sharp = cv2.addWeighted(u, 1.6, cv2.GaussianBlur(u, (0, 0), 3), -0.6, 0)
        _, so = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        yield f"{prefix}_up{f}_sharp", so
        yield f"{prefix}_up{f}_adapt", cv2.adaptiveThreshold(
            u, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 5)


def _variants(gray):
    """Yield (name, ndarray) preprocessing variants, cheapest first. Decoding
    stops at the first hit, so the expensive tiling tail only runs on the hard
    images that everything above missed (~a few % of real photos)."""
    yield "raw_gray", gray

    h, w = gray.shape[:2]
    # ALWAYS try a 2x upscale. Field DataMatrix codes are often small inside a
    # 1920px frame; at 2x zxing locks on far more often. (In testing this alone
    # recovered half of the otherwise-missed codes.)
    up = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
    yield "upscale_2x", up

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "otsu", otsu

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    _, eq_th = cv2.threshold(eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "clahe_otsu", eq_th

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, blur_th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "blur_otsu", blur_th

    _, up_otsu = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "upscale_otsu", up_otsu

    # Deep tail: the code is often small AND low-contrast, off-centre in a busy
    # scene. Run the whole image plus overlapping tiles through the strong
    # upscale+contrast battery (_enhanced_variants). Only reached when everything
    # above missed (the hard ~few %); costs ~1s on those images.
    regions = [("full", gray)]
    nx, ny, ov = 3, 2, 0.30
    tw, th = max(1, w // nx), max(1, h // ny)
    sx, sy = max(1, int(tw * (1 - ov))), max(1, int(th * (1 - ov)))
    yi = 0
    while yi < h:
        xi = 0
        while xi < w:
            tile = gray[yi:min(yi + th, h), xi:min(xi + tw, w)]
            if tile.size and min(tile.shape[:2]) >= 24:
                regions.append((f"t{yi}_{xi}", tile))
            xi += sx
        yi += sy
    for prefix, region in regions:
        yield from _enhanced_variants(region, prefix)


# ----------------------------------------------------------------------------
# decoders
# ----------------------------------------------------------------------------

def _zxing_read(img_ndarray):
    """Return decoded text via zxing-cpp restricted to DataMatrix, or None."""
    try:
        results = zxingcpp.read_barcodes(
            img_ndarray,
            formats=zxingcpp.BarcodeFormat.DataMatrix,
            try_rotate=True,
            try_downscale=True,
        )
    except TypeError:
        # older/newer signature: fall back to ReaderOptions or bare call
        try:
            opts = zxingcpp.ReaderOptions()
            opts.formats = zxingcpp.BarcodeFormat.DataMatrix
            opts.try_rotate = True
            results = zxingcpp.read_barcodes(img_ndarray, opts)
        except Exception:
            results = zxingcpp.read_barcodes(img_ndarray)
    for r in results:
        if r.text:
            return r.text
    return None


def _pylibdmtx_read(img_ndarray):
    if not _HAVE_PYLIBDMTX:
        return None
    try:
        res = _pylibdmtx.decode(img_ndarray, timeout=4000, max_count=1)
        if res:
            return res[0].data.decode("utf-8", "replace")
    except Exception:
        return None
    return None


def decode_image_bytes(data, debug=False):
    """
    Try the preprocessing ladder with zxing, then pylibdmtx fallback.
    Returns dict: {decoded, engine, ok, attempts, error}

    Memory: variants are generated lazily (the ladder is a generator) and each
    is released after it's tried, so peak RAM is O(1) in the number of variants
    — a small constant of full-frame arrays, not the whole ladder. (Worst case is
    the upscale region: gray + the 2x `up` + its Otsu live together, ~2 transforms
    of the upscaled size; the tiling tail uses small tiles.) Bounded per worker.
    """
    attempts = []
    try:
        gray = _bytes_to_gray(data)
    except Exception as e:  # noqa: BLE001
        return {"decoded": None, "engine": None, "ok": False,
                "attempts": [], "error": f"image_decode_error: {e}"}

    try:
        for name, variant in _variants(gray):
            txt = _zxing_read(variant)
            attempts.append({"variant": name, "engine": "zxing", "hit": bool(txt)})
            if variant is not gray:
                del variant  # release the transform immediately
            if txt:
                if debug:
                    sys.stderr.write(f"[decode] hit on {name} via zxing\n")
                return {"decoded": txt, "engine": f"zxing:{name}", "ok": True,
                        "attempts": attempts, "error": None}

        # fallback engine, only if available
        if _HAVE_PYLIBDMTX:
            for name, variant in _variants(gray):
                txt = _pylibdmtx_read(variant)
                attempts.append({"variant": name, "engine": "pylibdmtx", "hit": bool(txt)})
                if variant is not gray:
                    del variant
                if txt:
                    if debug:
                        sys.stderr.write(f"[decode] hit on {name} via pylibdmtx\n")
                    return {"decoded": txt, "engine": f"pylibdmtx:{name}", "ok": True,
                            "attempts": attempts, "error": None}

        return {"decoded": None, "engine": None, "ok": False,
                "attempts": attempts, "error": "no_barcode_found"}
    finally:
        del gray


def decode_url(url, cache_dir=None, debug=False, verify_ssl=True,
               timeout=20, retries=2):
    if not url:
        return {"decoded": None, "engine": None, "ok": False,
                "attempts": [], "error": "empty_url"}
    try:
        data = fetch_bytes(url, cache_dir=cache_dir, timeout=timeout,
                           retries=retries, verify_ssl=verify_ssl)
    except Exception as e:  # noqa: BLE001
        return {"decoded": None, "engine": None, "ok": False,
                "attempts": [], "error": f"download_error: {e}"}
    return decode_image_bytes(data, debug=debug)


# ----------------------------------------------------------------------------
# self-test: synthesize a DataMatrix and decode it back through the ladder
# ----------------------------------------------------------------------------

def _self_test():
    payload = "00000046288929l_?hz=RACoA0IGr"
    # render a DataMatrix to an ndarray using zxing's writer
    try:
        img = zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.DataMatrix)
        png = zxingcpp.write_barcode_to_image(img, size_hint=300)
        arr = np.array(png)
    except Exception:
        # deprecated path
        img = zxingcpp.write_barcode(zxingcpp.BarcodeFormat.DataMatrix, payload,
                                     width=300, height=300)
        arr = np.array(img)
    # encode to PNG bytes so we exercise the real bytes->gray path
    ok, buf = cv2.imencode(".png", arr)
    res = decode_image_bytes(buf.tobytes(), debug=True)
    passed = res["ok"] and res["decoded"] == payload
    print("decoded:", repr(res["decoded"]))
    print("engine :", res["engine"])
    print("zxing fallback (pylibdmtx) available:", _HAVE_PYLIBDMTX)
    print("self-test:", "PASSED" if passed else "FAILED")
    return passed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--url", help="Photo URL of the DataMatrix (column AG)")
    g.add_argument("--file", help="Local image file to decode")
    g.add_argument("--self-test", action="store_true", help="Run built-in test")
    ap.add_argument("--cache-dir", default=None, help="Disk cache dir for downloads")
    ap.add_argument("--no-verify-ssl", action="store_true",
                    help="Disable SSL verification (internal hosts with self-signed certs)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if _self_test() else 1)

    if args.file:
        with open(args.file, "rb") as f:
            res = decode_image_bytes(f.read(), debug=args.debug)
    elif args.url:
        res = decode_url(args.url, cache_dir=args.cache_dir, debug=args.debug,
                         verify_ssl=not args.no_verify_ssl)
    else:
        ap.error("provide --url, --file, or --self-test")

    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["ok"] else 2)


if __name__ == "__main__":
    main()
