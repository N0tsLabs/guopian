"""Face, eye, expression and gaze signals via MediaPipe Face Landmarker.

One Apache-2.0 model gives us, in a single pass:
    478 landmarks (incl. irises) + 52 ARKit blendshapes + head pose matrix

which covers closed eyes, expression, gaze direction and head turn together.
See docs/02 for why blendshapes beat hand-rolled Eye-Aspect-Ratio geometry.

Every signal is *gated*: when a face is turned away, too small or too blurry we
refuse to judge instead of crying wolf.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any

import numpy as np
from PIL import Image

from . import config, metrics

_HAVE_MP = None
_MP_ERROR = None

# FaceMesh landmark index groups
_R_EYE = (33, 133, 159, 145, 153, 144)     # subject's right eye (image left)
_L_EYE = (263, 362, 386, 374, 380, 373)    # subject's left eye  (image right)
_LEFT_FACE = 234
_RIGHT_FACE = 454
_NOSE = 1
_CHIN = 152
_FOREHEAD = 10


def _load_mp():
    global _HAVE_MP, _MP_ERROR
    if _HAVE_MP is not None:
        return _HAVE_MP
    try:
        from mediapipe.tasks import python as mp_python  # noqa: F401
        from mediapipe.tasks.python import vision  # noqa: F401

        _HAVE_MP = True
    except Exception as e:  # pragma: no cover
        _HAVE_MP = False
        _MP_ERROR = "{}: {}".format(type(e).__name__, e)
    return _HAVE_MP


def available() -> tuple[bool, str | None]:
    if not _load_mp():
        return False, _MP_ERROR
    if not os.path.exists(config.FACE_MODEL):
        return False, "model missing: run  python scripts/fetch_models.py"
    return True, None


# ------------------------------------------------------------------ pool
#
# IMPORTANT (this is a 40+ second bug if you get it wrong):
# A MediaPipe FaceLandmarker takes ~42 s to destroy on Windows. If it is held
# in a threading.local it gets collected when the worker thread dies, and
# ThreadPoolExecutor.shutdown() then blocks for the full 42 s *after* all the
# real work has finished. Keeping a strong reference forever means the
# destructor only ever runs at interpreter exit.
#
# The pool (rather than one per thread) bounds memory: each landmarker holds
# its own TFLite interpreter.

_pool: "queue.LifoQueue" = queue.LifoQueue()
_pinned: list = []
_pool_lock = threading.Lock()
_max_lm = 4


def configure_pool(n_workers: int) -> None:
    """Cap how many landmarkers may exist at once (one per parallel worker)."""
    global _max_lm
    _max_lm = max(1, min(int(n_workers), 8))


def pool_stats() -> dict:
    return {"created": len(_pinned), "idle": _pool.qsize(), "max": _max_lm}


def _create_landmarker():
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    opts = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=config.FACE_MODEL),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=10,
        min_face_detection_confidence=0.35,
        min_face_presence_confidence=0.35,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
    )
    return vision.FaceLandmarker.create_from_options(opts)


def _acquire_lm():
    try:
        return _pool.get_nowait()
    except queue.Empty:
        pass
    with _pool_lock:
        if len(_pinned) < _max_lm:
            lm = _create_landmarker()
            _pinned.append(lm)          # never released -> never destroyed mid-run
            return lm
    return _pool.get()                  # block until a worker frees one


def _release_lm(lm) -> None:
    _pool.put(lm)


# ------------------------------------------------------------------ helpers

def _bs_map(blendshapes) -> dict[str, float]:
    out: dict[str, float] = {}
    if not blendshapes:
        return out
    for c in blendshapes:
        name = (c.category_name or "").lstrip("_")
        out[name] = float(c.score)
    return out


def _euler_from_matrix(m: np.ndarray) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees from MediaPipe's 4x4 face transform."""
    r = np.asarray(m, dtype=np.float64)[:3, :3]
    sy = float(np.sqrt(r[0, 0] ** 2 + r[1, 0] ** 2))
    if sy > 1e-6:
        pitch = np.degrees(np.arctan2(-r[2, 0], sy))
        yaw = np.degrees(np.arctan2(r[1, 0], r[0, 0]))
        roll = np.degrees(np.arctan2(r[2, 1], r[2, 2]))
    else:  # gimbal lock
        pitch = np.degrees(np.arctan2(-r[2, 0], sy))
        yaw = np.degrees(np.arctan2(-r[0, 1], r[1, 1]))
        roll = 0.0
    return float(yaw), float(pitch), float(roll)


def _eye_box(pts: np.ndarray, idx, w: int, h: int, pad: float = 0.35) -> list[float]:
    sel = pts[list(idx)]
    x0, y0 = sel[:, 0].min(), sel[:, 1].min()
    x1, y1 = sel[:, 0].max(), sel[:, 1].max()
    bw, bh = x1 - x0, y1 - y0
    x0 = max(0.0, x0 - bw * pad)
    y0 = max(0.0, y0 - bh * pad)
    x1 = min(1.0, x1 + bw * pad)
    y1 = min(1.0, y1 + bh * pad)
    return [float(x0), float(y0), float(x1 - x0), float(y1 - y0)]


# ------------------------------------------------------------------ main

def _catchlight(gray: np.ndarray, box, ref: float, gw: int, gh: int):
    """Specular highlight inside one eye, as a brightness delta over the face.

    A catchlight is a small, very bright blob in the eye. It matters because an
    eye that is open but has no catchlight reads as *dead* on a portrait -- one
    of the most common reasons a technically fine frame gets thrown away.

    Measured relative to the face's own median brightness so it adapts to how
    the face is lit, rather than demanding an absolute pixel value. Returns
    None when the eye is too small for the number to mean anything.
    """
    x, y, w, h = box
    x0 = int(max(0, x * gw)); y0 = int(max(0, y * gh))
    x1 = int(min(gw, (x + w) * gw)); y1 = int(min(gh, (y + h) * gh))
    if x1 - x0 < 3 or y1 - y0 < 2:
        return None
    roi = gray[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    hi = float(np.percentile(roi, 98))
    return max(0.0, (hi - ref) / 255.0)


# ── second detection pass ─────────────────────────────────────────────────
#
# A face that covers 3% of a 6000px frame is, by the time the detector has
# finished rescaling its input to its own ~256px working size, about eight
# pixels across -- and BlazeFace will not find it. Feeding it MORE resolution
# does not help for the same reason: measured 5 / 4 / 4 faces at 1500 / 3000 /
# full resolution on the same 20 photos. Higher was slightly WORSE.
#
# The only thing that increases a face's share of the detector's input is to
# crop. Measured on DSC09891-09893 and DSC09869 -- a standing woman, nothing
# occluding her, no rotation, plainly visible -- the whole frame finds 0 and a
# crop finds 1, every time.
#
# So: if the whole-frame pass finds nothing, retry on overlapping tiles. The
# landmarks that come back are in TILE coordinates and are mapped back to the
# full frame before anything else looks at them, so no downstream code has to
# know this happened. Rotation in the pose matrix is unaffected by translation,
# and blendshapes are shape-only, so both survive the shift untouched.
#
# Cost is bounded to photos where the first pass found nothing -- which is most
# of a travel library, so it is measured, not assumed. See
# evaluation/face_tiling_cost.py.
_FACE_TILES = (
    (0.00, 0.00, 0.60, 0.60),
    (0.40, 0.00, 1.00, 0.60),
    (0.00, 0.40, 0.60, 1.00),
    (0.40, 0.40, 1.00, 1.00),
    (0.20, 0.15, 0.80, 0.85),     # centre, for a subject framed in the middle
)
# Tiles are upscaled to this before detection. Bigger than the detector's
# internal size on purpose: it means the face is not the only thing being
# shrunk.
_FACE_TILE_EDGE = 1024


def _detect_tiled(lm, mp, rgb: np.ndarray):
    """(result, scale_x, scale_y, off_x, off_y) for the best detection.

    Whole frame first, then every tile, and whichever result holds the MOST
    faces wins. Mapping is returned so the caller can put landmarks back into
    full-frame coordinates.
    """
    res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    best = (res, 1.0, 1.0, 0.0, 0.0)
    best_n = len(res.face_landmarks or [])

    # Tiling does NOT stop at the first tile that finds anybody.
    #
    # It used to, and the cost of that was a group photo with two people in it:
    # the whole-frame pass found the taller one, so the tiles never ran, and the
    # other person -- unobstructed, eyes open, plainly visible -- got no box at
    # all. "Found one, missed one" is the common case, not the edge case.
    #
    # Now every tile is tried and the result with the MOST faces wins. That needs
    # no IoU merging: the answer is still one MediaPipe result, just the best one,
    # so all the code below is unchanged. It is not perfectly general -- a tile
    # holding one different face cannot beat the whole frame holding one -- but it
    # costs nothing extra and it fixes the case that actually happens.
    if best_n >= 3:
        return best                      # already a crowd; tiles will not help

    H, W = rgb.shape[:2]
    for x0f, y0f, x1f, y1f in _FACE_TILES:
        x0, y0 = int(x0f * W), int(y0f * H)
        x1, y1 = int(x1f * W), int(y1f * H)
        if x1 - x0 < 32 or y1 - y0 < 32:
            continue
        crop = rgb[y0:y1, x0:x1]
        try:
            from PIL import Image as _Image
            ci = _Image.fromarray(crop)
            ci.thumbnail((_FACE_TILE_EDGE, _FACE_TILE_EDGE), _Image.Resampling.LANCZOS)
            carr = np.asarray(ci, dtype=np.uint8)
        except Exception:
            continue
        r2 = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=carr))
        n2 = len(r2.face_landmarks or [])
        if n2 > best_n:
            # tile coords (0..1 of the crop) -> full-frame normalised
            best = (r2,
                    (x1 - x0) / float(W), (y1 - y0) / float(H),
                    x0 / float(W), y0 / float(H))
            best_n = n2
    return best


def analyze_faces(img: Image.Image, gray_norm: np.ndarray,
                  norm_scale: float, frame_lap_var: float,
                  decode_scale: float = 1.0) -> list[dict]:
    """Detect faces and derive every facial signal we report.

    norm_scale   = (thumbnail long edge) / (decoded long edge) -- maps the
                   normalised landmarks onto the grayscale array.
    decode_scale = (decoded long edge) / (original long edge) -- we gate on
                   ORIGINAL pixel sizes, because that is what the user sees.
    """
    ok, _ = available()
    if not ok:
        return []

    import mediapipe as mp

    rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    lm = _acquire_lm()
    try:
        res, sx, sy, ox, oy = _detect_tiled(lm, mp, rgb)
    except Exception:
        _release_lm(lm)
        return []
    _release_lm(lm)

    if not res.face_landmarks:
        return []

    W, H = img.size
    gh, gw = gray_norm.shape
    out: list[dict] = []

    for fi, lms in enumerate(res.face_landmarks):
        # When the face came from a tile these are crop coordinates; map them
        # back so every consumer sees full-frame normalised values and nothing
        # downstream needs to know a crop happened.
        pts = np.array([[p.x * sx + ox, p.y * sy + oy, getattr(p, "z", 0.0)]
                        for p in lms], dtype=np.float64)
        if pts.shape[0] < 468:
            continue

        x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
        x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
        pw, ph = (x1 - x0) * W, (y1 - y0) * H          # face box in original pixels

        bs = _bs_map(res.face_blendshapes[fi]) if res.face_blendshapes else {}

        yaw = pitch = roll = 0.0
        if res.facial_transformation_matrixes and fi < len(res.facial_transformation_matrixes):
            try:
                yaw, pitch, roll = _euler_from_matrix(res.facial_transformation_matrixes[fi])
            except Exception:
                pass

        # ---- gaze from the 8 eyeLook* blendshapes -----------------------
        g = lambda k: bs.get(k, 0.0)  # noqa: E731
        look_left = g("eyeLookOutLeft") + g("eyeLookInRight")
        look_right = g("eyeLookInLeft") + g("eyeLookOutRight")
        look_up = g("eyeLookUpLeft") + g("eyeLookUpRight")
        look_dn = g("eyeLookDownLeft") + g("eyeLookDownRight")
        gaze_x = (look_left - look_right) / 2.0     # + = subject looks to their left
        gaze_y = (look_up - look_dn) / 2.0          # + = up
        gaze_away = float(min(1.0, np.hypot(gaze_x, gaze_y)))

        # ---- expression -------------------------------------------------
        smile = max(g("mouthSmileLeft"), g("mouthSmileRight"))
        jaw_open = g("jawOpen")
        brow_down = max(g("browDownLeft"), g("browDownRight"))
        squint = max(g("eyeSquintLeft"), g("eyeSquintRight"))
        pucker = max(g("mouthPucker"), g("mouthFunnel"))
        frown = max(g("mouthFrownLeft"), g("mouthFrownRight"))

        # ---- face-region sharpness / exposure ---------------------------
        face_sharp = face_high = face_low = None
        face_med = None
        fx0 = int(max(0, x0 * gw))
        fy0 = int(max(0, y0 * gh))
        fx1 = int(min(gw, x1 * gw))
        fy1 = int(min(gh, y1 * gh))
        if fx1 - fx0 >= 16 and fy1 - fy0 >= 16:
            roi = gray_norm[fy0:fy1, fx0:fx1]
            rm = metrics.region_metrics(roi)
            face_sharp = rm.get("lap_var")
            face_high = rm.get("pct_high")
            face_low = rm.get("pct_low")
            face_med = float(np.median(roi))

        # ---- catchlight --------------------------------------------------
        catch_l = catch_r = None
        if face_med is not None:
            catch_r = _catchlight(gray_norm, _eye_box(pts, _R_EYE, W, H), face_med, gw, gh)
            catch_l = _catchlight(gray_norm, _eye_box(pts, _L_EYE, W, H), face_med, gw, gh)

        # ---- gating ------------------------------------------------------
        # Gate on the size in the *decoded* image, because that is the pixels
        # the model actually saw and therefore what decides whether its
        # blendshapes mean anything. (Original-pixel size is kept for display.)
        inv = 1.0 / decode_scale if decode_scale else 1.0
        pw_orig, ph_orig = pw * inv, ph * inv
        eye_w_px = (pts[list(_L_EYE)][:, 0].max() - pts[list(_R_EYE)][:, 0].min()) * W
        gates = {
            "face_px": float(min(pw, ph)),
            "face_px_original": float(min(pw_orig, ph_orig)),
            "eye_px": float(eye_w_px),
            "yaw": abs(float(yaw)),
            "decode_scale": float(decode_scale),
            "too_small": min(pw, ph) < config.FACE_MIN_PIXELS,
            "eye_too_small": eye_w_px < config.EYE_MIN_PIXELS * 2,
            "turned": abs(float(yaw)) > config.FACE_EDGE_MAX_YAW,
        }
        gates["judge_eyes"] = not (gates["too_small"] or gates["eye_too_small"] or gates["turned"])

        face_ratio = None
        if face_sharp is not None and frame_lap_var > 1e-6:
            face_ratio = float(face_sharp / frame_lap_var)

        out.append({
            "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
            "yaw": float(yaw), "pitch": float(pitch), "roll": float(roll),
            "blink_l": g("eyeBlinkLeft"), "blink_r": g("eyeBlinkRight"),
            "gaze_x": float(gaze_x), "gaze_y": float(gaze_y), "gaze_away": gaze_away,
            "smile": float(smile), "jaw_open": float(jaw_open),
            "brow_down": float(brow_down), "squint": float(squint),
            "pucker": float(pucker), "frown": float(frown),
            "face_sharp": face_sharp, "face_pct_high": face_high, "face_pct_low": face_low,
            "face_sharp_ratio": face_ratio,
            "face_median": face_med,
            "catch_l": catch_l, "catch_r": catch_r,
            "gates": gates,
            "landmarks": {
                "r_eye": _eye_box(pts, _R_EYE, W, H),
                "l_eye": _eye_box(pts, _L_EYE, W, H),
                "nose": [float(pts[_NOSE][0]), float(pts[_NOSE][1])],
            },
            "n_landmarks": int(pts.shape[0]),
        })

    return out
