"""Single-photo analysis: raw signals only, no judgement.

Pass 1 (this module) is the expensive part and produces *numbers*.
Pass 2 (`evaluate`) turns numbers into named problems, and it needs the whole
library first because most thresholds are relative. Splitting them is what
makes the progressive pipeline in docs/05 possible.
"""

from __future__ import annotations

import math
import os
from typing import Any

from PIL import Image

from . import config, faces, imageio, metrics, phash


def analyze_photo(path: str) -> dict:
    """Decode once, derive every raw signal. Raises on unreadable files."""
    img, was_raw_preview, decode_scale = imageio.open_image(path, max_edge=config.ANALYSIS_EDGE)
    W, H = img.size

    meta = imageio.read_exif(img)
    # Report the ORIGINAL pixel dimensions, not the decoded ones: the decode is
    # deliberately downscaled (see config.ANALYSIS_EDGE), and showing a 24MP
    # photo as "3000x2000" would be wrong in the UI and in the size checks.
    inv = 1.0 / decode_scale if decode_scale else 1.0
    meta["width"] = int(round(W * inv))
    meta["height"] = int(round(H * inv))
    meta["taken_at"] = meta.get("taken_at")
    meta["taken_ts"] = imageio._parse_taken_ts(meta.get("taken_at"))
    if meta["taken_ts"] is None:
        try:
            meta["taken_ts"] = os.path.getmtime(path)
        except OSError:
            meta["taken_ts"] = None
    for k in ("camera", "lens"):
        meta.setdefault(k, None)
    for k in ("iso", "aperture", "focal", "orientation"):
        meta.setdefault(k, None)
    meta["shutter"] = meta.get("shutter")
    meta["raw_preview"] = was_raw_preview

    gray = metrics.to_gray(img)
    norm_scale = max(gray.shape) / float(max(W, H))
    m = metrics.global_metrics(gray, W, H)
    m.update(metrics.color_cast(img))

    m["face_count"] = 0
    face_rows: list[dict] = []
    if faces.available()[0]:
        try:
            face_rows = faces.analyze_faces(img, gray, norm_scale, m["lap_var"], decode_scale)
            m["face_count"] = len(face_rows)
        except Exception:
            face_rows = []
            m["face_count"] = 0

    try:
        ph = phash.phash_gray(gray)
    except Exception:
        ph = None

    return {"meta": meta, "metrics": m, "faces": face_rows, "phash": ph}


# ------------------------------------------------------------------ pass 2

_SEV_ORDER = {"fatal": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

_ISSUE_TEXT = {
    "eye_closed":        ("眼睛闭合", "Eyes closed"),
    "eye_maybe_closed":  ("眼睛可能闭着", "Eyes possibly closed"),
    "mouth_open":        ("嘴巴张开（可能在说话）", "Mouth open"),
    "frowning":          ("眉头压低", "Brow lowered"),
    "looking_away":      ("视线没看镜头", "Looking away"),
    "head_turned":       ("头部偏转较大", "Head turned"),
    "face_blurry":       ("人脸区域不够清晰", "Face not sharp"),
    "face_overexposed":  ("人脸高光溢出", "Face overexposed"),
    "face_underexposed": ("人脸过暗", "Face too dark"),
    "face_small":        ("人脸太小", "Face too small"),
    "overexposed":       ("高光溢出", "Blown highlights"),
    "underexposed":      ("暗部死黑", "Crushed shadows"),
    "low_contrast":      ("画面发灰、对比度低", "Flat / low contrast"),
    "blurry":            ("模糊 / 失焦", "Blurry or out of focus"),
    "noisy":             ("噪点偏高", "Noisy"),
    "tilted":            ("画面倾斜", "Tilted horizon"),
    "face_edge_cut":     ("人脸贴近画面边缘", "Face at the frame edge"),
    "no_catchlight":     ("眼睛缺少眼神光", "No catchlight in the eyes"),
    "color_cast":        ("白平衡色偏", "Colour cast"),
    "low_resolution":    ("分辨率偏低", "Low resolution"),
    "compressed":        ("压缩痕迹明显", "Heavy compression"),
    "duplicate":         ("与另一张几乎完全相同", "Near-identical to another photo"),
    "soft_group_rank":   ("相似组内排名靠后", "Ranked low within its group"),
}


def _issue(kind: str, severity: str, confidence: float, detail: str = "",
           face_idx: int | None = None, evidence: dict | None = None) -> dict:
    zh, en = _ISSUE_TEXT.get(kind, (kind, kind))
    return {
        "kind": kind, "severity": severity, "confidence": round(float(confidence), 3),
        "label_zh": zh, "label_en": en, "detail": detail,
        "face_idx": face_idx, "evidence": evidence or {},
    }


def evaluate(row: dict, face_rows: list[dict], calib: dict,
             group_ctx: dict | None = None) -> list[dict]:
    """Turn raw numbers into a list of named, evidence-carrying problems."""
    th = metrics.thresholds_for(calib, row.get("camera"))
    soft = th.get("soft") or 0.0
    soft_fatal = th.get("soft_fatal") or 0.0
    sharp_median = th.get("sharp_median") or 0.0
    noisy = th.get("noisy") or 1e9
    contrast_low = th.get("contrast_low") or 0.0

    issues: list[dict] = []

    # ---------------------------------------------------------- global
    # Exposure needs BOTH an absolute floor and to stand out in this session.
    # A whole trip shot at dusk must not have every frame flagged "too dark".
    high_p = th.get("high_p") or 0.0
    low_p = th.get("low_p") or 0.0

    ph = row.get("pct_high")
    if ph is not None and ph > config.PCT_HIGH_FLAG and ph >= high_p:
        if ph > config.PCT_HIGH_FATAL:
            issues.append(_issue("overexposed", "fatal", min(1.0, ph / 30.0),
                                 "高光溢出 {:.1f}%".format(ph), evidence={"pct_high": ph}))
        else:
            issues.append(_issue("overexposed", "high", min(0.95, 0.5 + ph / 40.0),
                                 "高光溢出 {:.1f}%".format(ph), evidence={"pct_high": ph}))

    pl = row.get("pct_low")
    if pl is not None and pl > config.PCT_LOW_FLAG and pl >= low_p:
        if pl > config.PCT_LOW_FATAL:
            issues.append(_issue("underexposed", "fatal", min(1.0, pl / 80.0),
                                 "暗部死黑 {:.1f}%".format(pl), evidence={"pct_low": pl}))
        else:
            issues.append(_issue("underexposed", "high", min(0.95, 0.5 + pl / 100.0),
                                 "暗部死黑 {:.1f}%".format(pl), evidence={"pct_low": pl}))

    lv = row.get("lap_var_mp")
    if lv is not None and soft > 0 and lv < soft:
        sev = "fatal" if (soft_fatal > 0 and lv < soft_fatal) or \
                         (sharp_median > 0 and lv < sharp_median * config.SOFT_MEDIAN_RATIO_FATAL) else "high"
        conf = 0.55 if sev == "high" else 0.9
        if soft > 0:
            conf = min(0.98, 0.55 + 0.4 * (1.0 - min(1.0, lv / soft)))
        issues.append(_issue("blurry", sev, conf,
                             "清晰度 {:.0f}，本机偏软阈值 {:.0f}".format(lv, soft),
                             evidence={"lap_var_mp": lv, "threshold": soft}))

    dr = row.get("dynamic_range")
    if dr is not None and dr < config.DYNAMIC_RANGE_LOW:
        issues.append(_issue("low_contrast", "low", 0.45,
                             "动态范围 {:.0f}/255".format(dr), evidence={"dynamic_range": dr}))

    ns = row.get("noise")
    if ns is not None and ns > noisy:
        issues.append(_issue("noisy", "medium", min(0.9, 0.5 + (ns / max(noisy, 1e-6) - 1) * 0.3),
                             "噪点 {:.2f}".format(ns), evidence={"noise": ns}))

    tl = row.get("tilt_support")
    td = row.get("tilt_deg")
    if (td is not None and tl is not None
            and tl >= config.TILT_MIN_SUPPORT
            and config.TILT_FLAG_DEG < abs(td) <= config.TILT_MAX_DEG):
        issues.append(_issue("tilted", "low", min(0.85, 0.35 + tl),
                             "倾斜 {:.1f}°（集中度 {:.0%}）".format(td, tl),
                             evidence={"tilt_deg": td, "tilt_support": tl}))

    w, h = row.get("width") or 0, row.get("height") or 0
    if w and h and max(w, h) < config.MIN_LONG_EDGE:
        issues.append(_issue("low_resolution", "low", 0.7,
                             "{}×{}".format(w, h), evidence={"width": w, "height": h}))

    bl = row.get("blockiness")
    if bl is not None and bl > 1.6:
        issues.append(_issue("compressed", "low", min(0.8, (bl - 1.2) / 1.5),
                             "块效应 {:.2f}".format(bl), evidence={"blockiness": bl}))

    # ---------------------------------------------------------- faces
    judgeable = 0
    for i, f in enumerate(face_rows):
        g = f.get("gates") or {}
        bx = {"x": f.get("x"), "y": f.get("y"), "w": f.get("w"), "h": f.get("h")}

        # A face box pressed against the border means the head is clipped and
        # there is no headroom left. Hint only -- a tight crop is a legitimate
        # composition, it just deserves a second look.
        fx_, fy_ = f.get("x") or 0.0, f.get("y") or 0.0
        fw_, fh_ = f.get("w") or 0.0, f.get("h") or 0.0
        em = config.FACE_EDGE_MARGIN
        if (fx_ <= em or fy_ <= em
                or fx_ + fw_ >= 1.0 - em or fy_ + fh_ >= 1.0 - em):
            issues.append(_issue("face_edge_cut", "info", 0.5,
                                 "人脸贴近画面边缘", face_idx=i, evidence=bx))

        if g.get("too_small"):
            issues.append(_issue("face_small", "low", 0.6,
                                 "人脸约 {:.0f}px".format(g.get("face_px") or 0),
                                 face_idx=i, evidence=bx))
            continue
        if not g.get("judge_eyes", False):
            continue  # turned / tiny eyes -> refuse to judge rather than guess
        judgeable += 1

        bl_l, bl_r = f.get("blink_l") or 0.0, f.get("blink_r") or 0.0
        # BOTH eyes, never one. A real blink closes both; a single high reading
        # is the model's side bias or an occluded eye, and calling that "eyes
        # possibly closed" was the source of four confident false positives on a
        # real library (0.49/0.20, 0.45/0.25, 0.48/0.33, 0.44/0.19 -- all one
        # eye high, the other low, all reported as blinks).
        both_closed = bl_l >= config.EYE_BLINK_CLOSED and bl_r >= config.EYE_BLINK_CLOSED
        both_maybe = bl_l >= config.EYE_BLINK_MAYBE and bl_r >= config.EYE_BLINK_MAYBE
        # Kept in the evidence so an asymmetric reading is still visible to
        # whoever is wondering why this photo was not flagged.
        blink_ev = {**bx, "blink_l": bl_l, "blink_r": bl_r,
                    "asymmetric": abs(bl_l - bl_r) >= 0.25}
        if both_closed:
            conf = min(bl_l, bl_r)      # the weaker eye is the honest one
            issues.append(_issue("eye_closed", "fatal", conf,
                                 "双眼闭合（{:.2f} / {:.2f}）".format(bl_l, bl_r),
                                 face_idx=i, evidence=blink_ev))
        elif both_maybe:
            conf = min(bl_l, bl_r)
            issues.append(_issue("eye_maybe_closed", "medium", conf,
                                 "双眼可能闭合（{:.2f} / {:.2f}）".format(bl_l, bl_r),
                                 face_idx=i, evidence=blink_ev))

        # Catchlight: an open eye with no specular highlight reads as dead on a
        # portrait. Only reported when BOTH eyes lack it, and only as a hint --
        # overcast daylight genuinely gives weaker catchlights than a strobe.
        cl, cr = f.get("catch_l"), f.get("catch_r")
        if (not both_closed and cl is not None and cr is not None
                and cl < config.CATCHLIGHT_MIN and cr < config.CATCHLIGHT_MIN):
            issues.append(_issue("no_catchlight", "low", 0.45,
                                 "两眼都缺少眼神光（{:.2f} / {:.2f}）".format(cl, cr),
                                 face_idx=i, evidence={**bx, "catch_l": cl, "catch_r": cr}))

        jaw = f.get("jaw_open") or 0.0
        smile = f.get("smile") or 0.0
        if jaw > config.MOUTH_OPEN and smile < 0.2:
            issues.append(_issue("mouth_open", "medium", min(0.9, jaw),
                                 "张嘴度 {:.2f}".format(jaw), face_idx=i,
                                 evidence={**bx, "jaw_open": jaw}))

        brow = f.get("brow_down") or 0.0
        if brow > config.FROWN_BROW and smile < 0.2 and jaw < config.MOUTH_OPEN:
            issues.append(_issue("frowning", "low", min(0.8, brow),
                                 "眉头压低 {:.2f}".format(brow), face_idx=i,
                                 evidence={**bx, "brow_down": brow}))

        # "Looking away" stays LOW severity and session-relative on purpose.
        # In candid travel photos it is the norm, not a defect -- flagging it
        # absolutely would put a warning on half the library (docs/05 3.3).
        away = f.get("gaze_away") or 0.0
        gaze_p = th.get("gaze_p85") or 0.0
        yaw = abs(f.get("yaw") or 0.0)
        if away > config.GAZE_AWAY and away >= gaze_p and yaw <= config.FACE_EDGE_MAX_YAW:
            issues.append(_issue("looking_away", "info", min(0.6, 0.3 + away / 4.0),
                                 "视线偏移 {:.2f}".format(away), face_idx=i,
                                 evidence={**bx, "gaze_x": f.get("gaze_x"),
                                           "gaze_y": f.get("gaze_y")}))
        if yaw > config.FACE_EDGE_MAX_YAW:
            issues.append(_issue("head_turned", "low", min(0.85, yaw / 90.0),
                                 "偏转 {:.0f}°".format(yaw), face_idx=i,
                                 evidence={**bx, "yaw": f.get("yaw")}))

        ratio = f.get("face_sharp_ratio")
        fsharp = f.get("face_sharp")
        face_p15 = th.get("face_sharp_p15")
        # Two independent conditions, because smooth skin alone makes a face
        # ROI less "sharp" than a detailed background. Requiring the face to
        # also sit in the bottom slice of *all* faces in the library kills
        # almost all of the false positives.
        ratio_bad = ratio is not None and ratio < config.FACE_BLUR_RATIO
        abs_bad = (face_p15 is None) or (fsharp is not None and fsharp < face_p15)
        if ratio_bad and abs_bad and fsharp is not None:
            conf = min(0.9, 0.5 + (config.FACE_BLUR_RATIO - ratio) * 2.0)
            issues.append(_issue("face_blurry", "high", conf,
                                 "人脸清晰度 {:.2f}（画面 {:.0f}%）".format(ratio, ratio * 100),
                                 face_idx=i,
                                 evidence={**bx, "face_sharp_ratio": ratio,
                                           "face_sharp": fsharp}))

        fh = f.get("face_pct_high")
        if fh is not None and fh > config.PCT_HIGH_FLAG * 2:
            issues.append(_issue("face_overexposed", "medium", min(0.9, fh / 25.0),
                                 "人脸高光 {:.1f}%".format(fh), face_idx=i,
                                 evidence={**bx, "face_pct_high": fh}))
        fl = f.get("face_pct_low")
        if fl is not None and fl > config.PCT_LOW_FLAG * 2:
            issues.append(_issue("face_underexposed", "medium", min(0.9, fl / 50.0),
                                 "人脸暗部 {:.1f}%".format(fl), face_idx=i,
                                 evidence={**bx, "face_pct_low": fl}))

    # ---------------------------------------------------------- colour cast
    # Judged only against the median of this shoot (see pipeline.recompute):
    # warm light is a property of the scene, not a defect, so the only thing
    # worth reporting is a photo that disagrees with its own siblings.
    cctx = th.get("cast") or {}
    cr, cb = row.get("cast_r"), row.get("cast_b")
    if cctx and cr is not None and cb is not None:
        dr = cr - cctx["r_med"]
        db = cb - cctx["b_med"]
        mag = math.hypot(dr, db)
        extreme = (cr <= cctx["r_lo"] or cr >= cctx["r_hi"]
                   or cb <= cctx["b_lo"] or cb >= cctx["b_hi"])
        if extreme and mag >= config.CAST_MEDIAN_TOL:
            if dr > 0 and db <= 0:
                way = "偏暖"
            elif dr < 0 and db >= 0:
                way = "偏冷"
            elif db < 0:
                way = "偏绿"
            else:
                way = "偏品红"
            sev = "low" if mag < config.CAST_MEDIAN_TOL * 2 else "medium"
            issues.append(_issue("color_cast", sev, min(0.85, 0.35 + mag * 4.0),
                                 "{}（偏离本批中位 {:.3f}）".format(way, mag),
                                 evidence={"cast_r": cr, "cast_b": cb,
                                           "r_med": cctx["r_med"],
                                           "b_med": cctx["b_med"]}))

    # ---------------------------------------------------------- group context
    if group_ctx:
        if group_ctx.get("exact_duplicate_of"):
            issues.append(_issue("duplicate", "medium", 0.95,
                                 "与 {} 几乎完全相同".format(group_ctx["exact_duplicate_of"]),
                                 evidence={"of": group_ctx["exact_duplicate_of"]}))
        gsize, grank = group_ctx.get("group_size"), group_ctx.get("group_rank")
        if gsize and gsize > 1 and grank and grank > max(2, gsize // 2):
            issues.append(_issue("soft_group_rank", "info",
                                 min(0.8, grank / float(gsize)),
                                 "相似组 {} 张中排名第 {}".format(gsize, grank),
                                 evidence={"group_size": gsize, "group_rank": grank}))

    issues.sort(key=lambda x: _SEV_ORDER.get(x["severity"], 9))
    return issues


def verdict_from(issues: list[dict], group_ctx: dict | None = None) -> dict:
    """Turn the issue list into a suggestion. Never a silent deletion."""
    fatal = [i for i in issues if i["severity"] == "fatal"]
    high = [i for i in issues if i["severity"] == "high"]
    medium = [i for i in issues if i["severity"] == "medium"]

    if fatal:
        sug = "reject"
        why = fatal[0]["label_zh"]
    elif len(high) >= 2:
        sug = "reject"
        why = "、".join(i["label_zh"] for i in high[:2])
    elif high or len(medium) >= 2:
        sug = "maybe"
        why = (high + medium)[0]["label_zh"] if (high or medium) else ""
    else:
        sug = "keep"
        why = "未发现明显问题"

    # "Best of the group" is a *ranking* statement. It can promote a maybe to
    # a keep, but it must never bury a real defect: being the best of five
    # broken frames still leaves you with a broken frame.
    if (group_ctx and group_ctx.get("group_size", 0) > 1
            and group_ctx.get("group_best") and sug != "reject"):
        sug = "keep"
        why = "相似组内最佳"

    conf = 0.5
    if fatal:
        conf = max(i["confidence"] for i in fatal)
    elif high:
        conf = max(i["confidence"] for i in high)
    elif sug == "keep":
        conf = 0.6
    return {"suggest": sug, "reason": why, "confidence": round(float(conf), 3)}
