"""Guopian configuration: every tunable threshold lives here.

Thresholds are *starting points*, not literature constants. They are calibrated
against your own library at runtime (see `calibrate()` in metrics.py), because
no absolute blur/exposure number is comparable across cameras and lenses.
"""

from __future__ import annotations

import os
import sys


def _bundle_root() -> str:
    """Root of the read-only assets, in source *and* in a frozen exe."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- paths

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = _bundle_root()
WEB_DIR = os.path.join(ROOT_DIR, "web")
MODEL_DIR = os.path.join(ROOT_DIR, "models")
FACE_MODEL = os.path.join(MODEL_DIR, "face_landmarker.task")

# CLIP's vision tower, exported to ONNX and quantised on the way out: 96 MB
# instead of 352 MB, and no torch at runtime. Only the visual half ships --
# the scene words are a fixed vocabulary whose vectors are precomputed
# (guopian/data/tag_vecs.npy), so the text tower is not needed in the app.
SCENE_MODEL = os.path.join(MODEL_DIR, "clip_vision.onnx")
# Bumped whenever the exported graph or its preprocessing changes: it is part of
# the identity of a stored vector, so old vectors get recomputed rather than
# silently mixed with new ones.
EMBED_MODEL = "clip-vitb32-int8-v1"
EMBED_BATCH = 8
EMBED_EDGE = 1600          # encode the same preview the stage shows

# 分组（有画面向量时走这条路，见 group.build_groups_vec）
#
# 为什么和 pHash 那套参数不是一套：pHash 那套是并查集，靠"能借道"把照片串
# 起来，所以阈值和时间窗都要给得很大才能连上；向量这套是完全连接，借不了道，
# 阈值给紧反而更准。实测：真近似重复余弦 0.98，同场景不同瞬间 0.90-0.95，
# "一张双人合影 vs 一张空景" 0.58 —— 0.85 落在空档里。
GROUP_COSINE = 0.85
GROUP_WINDOW_SEC = 15.0
# 一组最多几张。连拍一个上午能在同一机位拍上百张，全串一组就没法"挑一张"了。
# 12 是"一个连拍序列"的量级，不是"一个景点"。
GROUP_MAX = 12

# Per-library working data lives in <library>/.guopian/
WORK_DIR_NAME = ".guopian"
TRASH_DIR_NAME = "_guopian_rejected"

# ---------------------------------------------------------------- analysis

# Bump to force re-analysis of everything after changing detectors.
#
# 5: face detection now retries on overlapping tiles when the whole-frame pass
#    finds nothing. A face covering 3% of the frame was being shrunk to ~8px by
#    the detector's own rescaling and missed; measured 18/93 photos with a face
#    before, and every crop that was tried found one.
#
# 4: blinks now require BOTH eyes (a real blink closes both; the previous
#    single-eye rule flagged four confident false positives on one library),
#    CATCHLIGHT_MIN moved off the median (0.12 -> 0.04), and the frown label was
#    corrected to say what browDown actually measures.
ANALYSIS_VERSION = 6

THUMB_SMALL = 400     # grid + the left-hand list
THUMB_CARD = 1600     # instant first paint while the full image loads
THUMB_ZOOM = 3000     # RAW/HEIC only: the largest preview we can extract
FULL_EDGE = 4096      # ditto, for "full"

# Formats the browser can render natively. For these we serve the ORIGINAL
# file once the user zooms in -- the whole point of a local-first app is that
# there is no bandwidth to save by downscaling, and a preview scaled up is
# just a blurry photo.
BROWSER_DISPLAYABLE = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp"}
MAX_DIRECT_BYTES = 150 << 20   # above this, fall back to a generated preview

SUPPORTED_EXT = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif",
    ".heic", ".heif", ".hif", ".avif",
    ".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".pef", ".srw",
}

# Long edge used for *analysis*. JPEGs are decoded with libjpeg's scaled DCT
# (1/1, 1/2, 1/4, 1/8) so a 6000x4000 file never has to be materialised whole.
# 1500 is chosen deliberately: for a 24MP source libjpeg can then use 1/4
# (1500px) instead of 1/2 (3000px), which is ~4x less decode work. Faces are
# gated on their pixel size *in this decoded image* (see FACE_MIN_PIXELS).
ANALYSIS_EDGE = 1500

# ---------------------------------------------------------------- exposure

# Exposure. Absolute numbers alone are useless (a night shot is legitimately
# dark, a snowfield legitimately bright), so each flag needs BOTH an absolute
# floor and to stand out within this session.
PCT_HIGH_LEVEL = 250      # >= this counts as blown-out
PCT_HIGH_FLAG = 6.0       # % of frame blown out
PCT_HIGH_FATAL = 18.0     # % that almost always ruins the shot
PCT_LOW_LEVEL = 5         # <= this counts as crushed black
PCT_LOW_FLAG = 25.0
PCT_LOW_FATAL = 50.0
EXPOSURE_SESSION_PCT = 90.0   # must also beat this percentile of the session
DYNAMIC_RANGE_LOW = 60.0  # p99 - p1 (0-255 scale) below this looks flat

# ---------------------------------------------------------------- sharpness

# Laplacian variance normalised by megapixel. Flagged RELATIVE to the library
# (or camera cluster) distribution, never against a hard number.
SOFT_PERCENTILE = 5.0     # bottom N% of the session is "soft"
SOFT_FATAL_PERCENTILE = 1.0
# Fraction of the session's median below which we call it unusable.
SOFT_MEDIAN_RATIO_FATAL = 0.15
# A percentile is meaningless on a small library (with 20 photos the 5th
# percentile IS the blurriest photo). So the relative threshold is never
# allowed below this absolute floor, and short sessions use it directly.
SOFT_ABS_FLOOR = 60.0
SOFT_MIN_N = 30
# The relative blur threshold is also capped at this fraction of the session
# median, so a library where everything is sharp produces zero blur flags.
SOFT_MEDIAN_CAP = 0.35

# ---------------------------------------------------------------- noise

NOISY_PERCENTILE = 90.0

# ---------------------------------------------------------------- geometry

TILT_FLAG_DEG = 1.5
TILT_MAX_DEG = 12.0        # beyond this it is a deliberate diagonal, not a horizon
TILT_MIN_SUPPORT = 0.30    # share of edge energy that must agree on one angle

MIN_LONG_EDGE = 2000
MIN_FILE_BYTES = 500 * 1024


# ---------------------------------------------------------------- faces

FACE_MIN_PIXELS = 56          # face box shorter side, in the DECODED image
FACE_EDGE_MAX_YAW = 32.0      # beyond this we refuse to judge the eyes

# Blinks are judged on BOTH eyes, never one.
#
# `eyeBlinkLeft` / `eyeBlinkRight` are regression outputs, not measurements, and
# they carry a systematic side bias. Measured on one real library: four photos
# all read 0.44-0.49 on one eye and 0.19-0.33 on the other, and every one of
# them was flagged as "eyes possibly closed". None of them was a blink -- a real
# blink closes both eyes, and the consistent asymmetry is the model, not the
# subject. Requiring both eyes removes that whole class of false positive.
#
# The thresholds themselves are unchanged: the bilateral requirement is what
# does the work, and lowering them on top of it would just re-admit the noise.
EYE_BLINK_CLOSED = 0.60
EYE_BLINK_MAYBE = 0.40
EYE_MIN_PIXELS = 18           # eye crop shorter side, decoded pixels

MOUTH_OPEN = 0.40

# browDown rises when frowning AND when concentrating, squinting into harsh
# light, or just holding a neutral face. 0.40 was low enough that a single
# 0.47 reading got reported as "表情严肃" -- a claim the model never made.
# Raised so it only fires on a pronounced lowering, and the label now says what
# was actually measured.
FROWN_BROW = 0.55
SMILE_GOOD = 0.35
SQUINT_GOOD = 0.25

# Gaze. "Looking away" is the single easiest signal to get wrong: in candid
# travel photos it is the *norm*, not a defect. It is therefore session
# relative, low severity, and never drives a reject on its own.
GAZE_AWAY = 0.45
GAZE_SESSION_PCT = 85.0
FACE_BLUR_RATIO = 0.18   # face ROI sharpness vs whole-frame sharpness
# ...and it also has to be low compared with every other face in the library,
# otherwise smooth skin alone would trip the flag. See docs/02 §3.1.
FACE_SHARP_PERCENTILE = 15.0

# A face box this close to the frame border is being clipped by the edge --
# there is no headroom left. Reported as a hint only: a tight crop is a
# legitimate composition, it just deserves a second look.
FACE_EDGE_MARGIN = 0.012

# Catchlight: a small specular highlight in the eye. An eye that is open but
# has no highlight reads as dead on a portrait. Measured as the 98th percentile
# of the eye region minus the face's own median brightness, in 0..1 of full
# range. Only reported when BOTH eyes lack it, and only as a hint -- overcast
# daylight genuinely produces weaker catchlights than a studio strobe.
#
# 0.12 was measured to be almost exactly the MEDIAN of this metric (0.112 on the
# library it was tuned on), so "below 0.12" meant "below average" and flagged
# about half of all faces. Every value it produced sat in 0.031-0.114 -- noise
# clustered under the line, not eyes without highlights. 0.04 asks the question
# the label actually claims to answer: is there no specular highlight at all?
CATCHLIGHT_MIN = 0.04

# ---------------------------------------------------------------- white balance

# Grey-world cast, always judged against the median of the same shoot: a sunset
# really is orange, so only photos that stand out from their own siblings are
# flagged. CAST_* are ratios against green, so 1.0 is neutral.
CAST_MEDIAN_TOL = 0.055   # minimum absolute deviation from the session median
CAST_PCT = 4.0            # ...and it must be in the extreme N% of the session

# ---------------------------------------------------------------- grouping

BURST_WINDOW_SEC = 30.0   # only compare photos taken this close together
PHASH_DUP = 4             # <= exact duplicate
PHASH_SIMILAR = 10        # <= same moment / near duplicate
# A burst always shares the camera's orientation, so a big aspect-ratio
# difference means the pHash match is a coincidence (blurred photos collide).
GROUP_ASPECT_TOL = 0.08

# ---------------------------------------------------------------- decisions

DECISIONS = ("keep", "reject", "mark")

# The three things you can say about a photo. All three are *judgements about
# the photo*, not file operations -- which is why the negative one is 不要
# rather than 删除, and 保留 was rejected too (it reads as "keep the file").
#
# The bar a word has to clear:
#   1. it describes the photo, never the file
#   2. it is unambiguous out of context ("确认" failed this -- confirm what?)
#   3. the two directions form a natural opposition
#
# DECISION_LABELS is the canonical vocabulary. It is the ONLY place these words
# are written down: the server sends them to the UI at startup and the frontend
# fills its placeholders from that. It used to be mirrored in web/app.js and
# again as bare text in index.html, so renaming a decision took four edits and
# missing one produced no error -- just two different words on one screen.
DECISION_LABELS = {
    "keep": "过",      # 审过、留下了
    "reject": "不过",   # 审过、不要 —— 但不会删文件
    "mark": "精选",     # 过，而且是这一批里最好的
}

# Two more sets are DERIVED from the above, so they live here too rather than
# being written out again in the interface. Rename 要 to 入选 and both of these
# have to follow.
#
#   VERDICT  the software's suggestion, before you have decided
#   OWNED    the badge shown once a photo carries YOUR decision
DECISION_VERDICT = {
    "keep": "建议过",
    "reject": "建议不过",
    "maybe": "建议复查",
}
DECISION_OWNED = {
    "keep": "你留下的",
    "reject": "你不过的",
    "mark": "你精选的",
}

# "Not yet reviewed" is simply the absence of a decision: navigating with
# ↑/↓ leaves it alone, so there is no separate pending/skip state.

# Decisions from older catalogs that are no longer part of the model. They are
# migrated to NULL (= back to unreviewed) when a catalog is opened.
RETIRED_DECISIONS = ("maybe", "skip")

# Not a fourth judgement -- the *absence* of one. It lets the client take back
# a 精选 mark in place, instead of making the user reach for undo and lose
# their position in the list.
CLEAR = "clear"

# ---------------------------------------------------------------- settings

# What the settings screen offers, and what each one defaults to. This is the
# schema: the API serves it, the UI renders it, and apply_settings() below is
# the ONLY place any of it turns into behaviour.
#
# The rule for adding an entry: it must be wired to something. A switch that
# saves a value nobody reads is worse than no switch -- it makes the screen look
# like it does more than it does.
SETTINGS_DEFAULTS = {
    # behaviour
    #
    # One folder per decision. They default to the decision WORDS themselves so
    # the app and the disk use a single vocabulary -- seeing 要 in the toolbar
    # and "keep" on disk is how a project ends up with two names for one thing,
    # which this codebase has already been bitten by. Rename them here, or
    # rename DECISION_LABELS and everything follows.
    #
    # Photos with NO decision stay where they are: these folders describe the
    # result of going through a shoot, and an unreviewed photo has no result.
    "dir_mark": DECISION_LABELS["mark"],
    "dir_keep": DECISION_LABELS["keep"],
    "dir_reject": DECISION_LABELS["reject"],
    "trash_dir": TRASH_DIR_NAME,     # legacy single-folder key; see _dir_for
    "confirm_apply": True,           # ask before moving anything
    "read_only": False,              # open libraries read-only by default
    "default_filter": "all",         # what the list shows when a library opens
    "default_sort": "time",
    "density": "standard",           # compact | standard | roomy
    "workers": 0,                    # 0 = let the machine decide

    # judgement
    "strictness": "standard",        # relaxed | standard | strict
    "burst_window": BURST_WINDOW_SEC,  # seconds; photos closer than this group
    # How far apart two perceptual hashes may be and still count as the same
    # moment. This is the knob behind "why were those two grouped and not these
    # three" -- pHash measures near-identical framing, so a subject who moves
    # between frames drifts past a low threshold. Raising it groups more.
    "phash_similar": PHASH_SIMILAR,
    "analysis_edge": ANALYSIS_EDGE,  # long edge used for detection
}

# "Stricter" means MORE photos get flagged. So a threshold that fires when a
# value rises above it has to come DOWN, and one that fires when a value falls
# below it has to go UP. Keeping the two lists apart is the entire trick, and
# getting it backwards would make "strict" quietly mean "lenient".
_STRICT_ABOVE = ("EYE_BLINK_MAYBE", "EYE_BLINK_CLOSED", "FROWN_BROW",
                 "PCT_HIGH_FLAG", "PCT_LOW_FLAG", "CAST_MEDIAN_TOL",
                 "GAZE_AWAY")
_STRICT_BELOW = ("CATCHLIGHT_MIN",)

STRICTNESS_FACTOR = {"relaxed": 1.30, "standard": 1.00, "strict": 0.75}

# Density is a single multiplier on spacing, not a second stylesheet.
DENSITY_FACTOR = {"compact": 0.88, "standard": 1.00, "roomy": 1.14}

# The values above are the shipped defaults. These are what apply_settings()
# restores before applying a change, so switching strictness twice does not
# compound the scale factor.
_BASELINE = {
    name: globals()[name]
    for name in _STRICT_ABOVE + _STRICT_BELOW + ("BURST_WINDOW_SEC", "ANALYSIS_EDGE",
                                          "PHASH_SIMILAR")
}


# The folder each decision lands in, resolved once at settings time. Kept as
# module state because decisions.py reads it at call time, exactly like the
# detector thresholds.
DECISION_DIRS = dict(SETTINGS_DEFAULTS)


def dir_for(decision: str) -> str:
    """Folder name for a decision, or "" for anything with no decision."""
    return DECISION_DIRS.get("dir_" + decision, "")


def apply_settings(s: dict | None = None) -> dict:
    """Push a settings dict into the module constants the detectors read.

    Modules read these as `config.X` at call time, so rebinding the module
    attribute is enough -- no restart, no plumbing. Everything is reset to the
    shipped baseline first, otherwise a second call would scale a value that was
    already scaled.
    """
    global TRASH_DIR_NAME, BURST_WINDOW_SEC, ANALYSIS_EDGE, PHASH_SIMILAR

    s = dict(SETTINGS_DEFAULTS, **(s or {}))

    for name, base in _BASELINE.items():
        globals()[name] = base

    k = STRICTNESS_FACTOR.get(s.get("strictness"), 1.0)
    if k != 1.0:
        for name in _STRICT_ABOVE:
            globals()[name] = globals()[name] * k
        for name in _STRICT_BELOW:
            globals()[name] = globals()[name] / k

    # A folder NAME, not a path: this gets joined onto the library root, and a
    # name containing separators would let a setting move files somewhere the
    # user never pointed at.
    def _safe(v, fallback):
        v = os.path.basename((v or "").strip().replace("\\", "/").rstrip("/"))
        return v or fallback

    for key, label in (("dir_mark", DECISION_LABELS["mark"]),
                       ("dir_keep", DECISION_LABELS["keep"]),
                       ("dir_reject", DECISION_LABELS["reject"])):
        DECISION_DIRS[key] = _safe(s.get(key), label)

    name = (s.get("trash_dir") or "").strip() or TRASH_DIR_NAME
    # A folder name, not a path: this gets joined onto the library root, and
    # letting it contain separators would let a setting move files somewhere
    # the user never pointed at.
    TRASH_DIR_NAME = os.path.basename(name.replace("\\", "/").rstrip("/")) or "_guopian_rejected"
    BURST_WINDOW_SEC = float(s.get("burst_window") or BURST_WINDOW_SEC)
    ANALYSIS_EDGE = int(s.get("analysis_edge") or ANALYSIS_EDGE)
    PHASH_SIMILAR = int(s.get("phash_similar") or PHASH_SIMILAR)

    return s
