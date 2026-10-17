"""Classic CV metrics. Pure numpy + OpenCV, no model downloads.

Everything here runs on a normalised thumbnail (long edge = NORM_EDGE) so that
scores are at least comparable *within* a library, plus a per-megapixel
normalisation so the original resolution is still represented.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

from . import config

NORM_EDGE = 1024


# ------------------------------------------------------------------ helpers

def to_gray(img: Image.Image, edge: int = NORM_EDGE) -> np.ndarray:
    """Greyscale at a normalised long edge.

    Convert to L *before* resizing: resizing three channels to then throw two
    away costs roughly 3x what it needs to.
    """
    g = img if img.mode == "L" else img.convert("L")
    w, h = g.size
    if max(w, h) > edge:
        s = edge / float(max(w, h))
        g = g.resize((max(1, int(round(w * s))), max(1, int(round(h * s)))),
                     Image.Resampling.BILINEAR)
    return np.asarray(g, dtype=np.uint8)


def _lap_var(gray: np.ndarray) -> float:
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    return float(lap.var())


def _tenengrad(gray: np.ndarray) -> float:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(gx * gx + gy * gy))


def _hf_ratio(gray: np.ndarray) -> float:
    """Fraction of spectral energy above 1/8 of Nyquist."""
    g = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_AREA).astype(np.float32)
    g -= g.mean()
    win = np.outer(np.hanning(256), np.hanning(256)).astype(np.float32)
    F = np.abs(np.fft.fftshift(np.fft.fft2(g * win)))
    h, w = F.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.ogrid[:h, :w]
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    rmax = min(cy, cx)
    cut = rmax * 0.5
    total = F.sum() + 1e-9
    return float(F[r > cut].sum() / total)


def _noise_sigma(gray: np.ndarray) -> float:
    """Robust noise estimate from horizontal first differences (Donoho-Johnstone style)."""
    if gray.size < 4096:
        return 0.0
    d = np.diff(gray.astype(np.float32), axis=1)
    mad = np.median(np.abs(d - np.median(d)))
    return float(1.4826 * mad / math.sqrt(2.0))


def _tilt_deg(gray: np.ndarray) -> tuple[float, float]:
    """Dominant near-horizontal edge angle, plus how concentrated it is.

    Hough line segments alone produce far too many false positives on real
    landscapes -- mountains and rocks yield long diagonals, and *some* line
    always looks tilted. So instead of asking "is there a tilted line?" we ask
    "how much of the image's edge energy agrees on one angle?". A real horizon
    concentrates it; scenery does not.

    Returns (angle_deg, concentration 0..1). Concentration is used as the gate.
    """
    h, w = gray.shape
    if h < 48 or w < 48:
        return 0.0, 0.0
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    thr = float(np.percentile(mag, 92))
    sel = mag >= max(thr, 1e-6)
    n_sel = int(sel.sum())
    if n_sel < 0.002 * mag.size or n_sel < 200:
        return 0.0, 0.0

    ang = np.degrees(np.arctan2(gy[sel], gx[sel]))
    # fold to [-45, 45]: a line at 170 deg is the same line as -10 deg
    ang = np.where(ang > 45.0, ang - 90.0, np.where(ang < -45.0, ang + 90.0, ang))
    weights = mag[sel]

    hist, edges = np.histogram(ang, bins=180, range=(-45.0, 45.0), weights=weights)
    total = float(hist.sum())
    if total <= 0:
        return 0.0, 0.0
    k = int(np.argmax(hist))
    centre = float((edges[k] + edges[k + 1]) / 2.0)
    lo = int(np.searchsorted(edges, centre - 1.5))
    hi = int(np.searchsorted(edges, centre + 1.5))
    support = float(hist[lo:hi].sum() / total)
    return centre, support


def _blockiness(gray: np.ndarray) -> float:
    """JPEG 8x8 block-edge energy vs interior energy. >1 means visible blocking."""
    g = gray.astype(np.float32)
    if g.shape[0] < 24 or g.shape[1] < 24:
        return 0.0
    dh = np.abs(np.diff(g, axis=1))
    dv = np.abs(np.diff(g, axis=0))
    hb = dh[:, 7::8].mean() if dh.shape[1] > 8 else 0.0
    hi = np.delete(dh, np.s_[7::8], axis=1).mean() if dh.shape[1] > 9 else 0.0
    vb = dv[7::8, :].mean() if dv.shape[0] > 8 else 0.0
    vi = np.delete(dv, np.s_[7::8], axis=0).mean() if dv.shape[0] > 9 else 0.0
    interior = (hi + vi) / 2.0 + 1e-6
    boundary = (hb + vb) / 2.0
    return float(boundary / interior)


# ------------------------------------------------------------------ public

def region_metrics(gray: np.ndarray) -> dict:
    """Metrics for a crop (used for face regions)."""
    if gray.size < 100:
        return {}
    hist = np.bincount(gray.reshape(-1), minlength=256).astype(np.float64)
    tot = hist.sum()
    cdf = np.cumsum(hist)
    p1 = int(np.searchsorted(cdf, tot * 0.01))
    p99 = int(np.searchsorted(cdf, tot * 0.99))
    return {
        "mean_luma": float(gray.mean()),
        "pct_high": float((gray >= config.PCT_HIGH_LEVEL).mean() * 100.0),
        "pct_low": float((gray <= config.PCT_LOW_LEVEL).mean() * 100.0),
        "dynamic_range": float(p99 - p1),
        "rms_contrast": float(gray.std()),
        "lap_var": _lap_var(gray),
    }


def global_metrics(gray: np.ndarray, full_w: int, full_h: int) -> dict:
    hist = np.bincount(gray.reshape(-1), minlength=256).astype(np.float64)
    tot = hist.sum()
    cdf = np.cumsum(hist)
    p1 = int(np.searchsorted(cdf, tot * 0.01))
    p99 = int(np.searchsorted(cdf, tot * 0.99))

    lv = _lap_var(gray)
    mp = max(0.01, (full_w * full_h) / 1_000_000.0)
    tilt, tilt_sup = _tilt_deg(gray)

    return {
        "mean_luma": float(gray.mean()),
        "pct_high": float((gray >= config.PCT_HIGH_LEVEL).mean() * 100.0),
        "pct_low": float((gray <= config.PCT_LOW_LEVEL).mean() * 100.0),
        "dynamic_range": float(p99 - p1),
        "rms_contrast": float(gray.std()),
        "lap_var": float(lv),
        "lap_var_mp": float(lv * mp),
        "tenengrad": _tenengrad(gray),
        "hf_ratio": _hf_ratio(gray),
        "noise": _noise_sigma(gray),
        "tilt_deg": float(tilt),
        "tilt_support": float(tilt_sup),
        "blockiness": _blockiness(gray),
    }


def color_cast(img: Image.Image) -> dict:
    """Grey-world colour cast, measured on mid-tones only.

    A sunset really is orange, so this is never judged on its own: pass 2
    compares every photo against the median of its own shoot and only flags the
    ones that stand out from their siblings. Mid-tones are used because blown
    highlights and crushed shadows carry no reliable colour information.

    Values are ratios against green, so 1.0 means neutral. Warm light gives
    cast_r > 1, cool light cast_b > 1.
    """
    small = img.convert("RGB")
    small.thumbnail((256, 256))
    a = np.asarray(small, dtype=np.float32)
    lum = a[:, :, 0] * 0.299 + a[:, :, 1] * 0.587 + a[:, :, 2] * 0.114
    mask = (lum > 40) & (lum < 220)
    if int(mask.sum()) < 64:
        mask = np.ones(lum.shape, dtype=bool)
    mean = a[mask].mean(axis=0)
    g = float(mean[1]) + 1e-6
    return {"cast_r": float(mean[0] / g), "cast_b": float(mean[2] / g)}


# ------------------------------------------------------------------ calibration

def _pct(values: list[float], p: float) -> float:
    vals = sorted(v for v in values if v is not None and v == v)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * (p / 100.0)
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return float(vals[lo])
    return float(vals[lo] + (vals[hi] - vals[lo]) * (k - lo))


# public alias
percentile = _pct


def calibrate(rows: list[dict]) -> dict:
    """Derive *relative* thresholds from this library instead of hard numbers.

    Clusters by camera model when a cluster is large enough, otherwise falls
    back to the whole session. This is the single most important idea in
    docs/02: absolute blur numbers do not transfer between cameras.

    A percentile is only meaningful with enough samples, so every relative
    threshold is clamped by an absolute floor (SOFT_ABS_FLOOR). Without that,
    a 20-photo library reports its own blurriest photo as the 5th percentile
    and flags nothing at all.
    """
    clusters: dict[str, list[dict]] = {}
    for r in rows:
        key = (r.get("camera") or "unknown").strip() or "unknown"
        clusters.setdefault(key, []).append(r)

    def block(items: list[dict]) -> dict:
        n = len(items)
        sharp = [i.get("lap_var_mp") for i in items]
        noi = [i.get("noise") for i in items]
        con = [i.get("rms_contrast") for i in items]
        med = _pct(sharp, 50.0)
        soft = _pct(sharp, config.SOFT_PERCENTILE)
        soft_fatal = _pct(sharp, config.SOFT_FATAL_PERCENTILE)
        if n < config.SOFT_MIN_N:
            # Too few photos for a percentile to mean anything: fall back to
            # the absolute floor plus a median-relative rule.
            soft = max(config.SOFT_ABS_FLOOR, med * 0.12)
            soft_fatal = max(config.SOFT_ABS_FLOOR * 0.35, med * 0.04)
        else:
            # A percentile alone always flags ~5% of the library, even one
            # where every frame is perfectly sharp. Requiring the photo to
            # also sit far below the median means a uniformly good shoot
            # produces no blur flags at all.
            soft = min(max(soft, config.SOFT_ABS_FLOOR), med * config.SOFT_MEDIAN_CAP)
            soft_fatal = max(soft_fatal, config.SOFT_ABS_FLOOR * 0.35)
        return {
            "n": n,
            "soft": soft,
            "soft_fatal": soft_fatal,
            "sharp_median": _pct(sharp, 50.0),
            "noisy": max(_pct(noi, config.NOISY_PERCENTILE), 1.2),
            "contrast_low": _pct(con, 10.0),
            # Session-relative exposure: a whole library shot at dusk must not
            # have every frame flagged as "too dark".
            "high_p": _pct([i.get("pct_high") for i in items], config.EXPOSURE_SESSION_PCT),
            "low_p": _pct([i.get("pct_low") for i in items], config.EXPOSURE_SESSION_PCT),
            "luma_median": _pct([i.get("mean_luma") for i in items], 50.0),
        }

    out: dict[str, dict] = {}
    for key, items in clusters.items():
        if len(items) < config.SOFT_MIN_N:
            continue
        out[key] = block(items)
    out["*"] = block(rows)
    return out


def thresholds_for(calib: dict, camera: str | None) -> dict:
    key = (camera or "unknown").strip() or "unknown"
    return calib.get(key) or calib.get("*") or {}
