"""Can CLIP tell us anything about "表情不好"?

Two halves, and they are different questions:
  * ranking  -- within a burst, which frame has the better expression?
  * absolute -- is this single photo's expression bad enough to flag?

Answers come from the data, not from optimism: CLIP zero-shot prompts are scored
per photo and correlated with the blendshape features MediaPipe already gives us
(blink, smile, jaw_open, squint, gaze). Then contact sheets are written so the
result can be looked at instead of trusted.

    python evaluation/clip_expression_eval.py
"""
import json
import os
import sqlite3
import sys

import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = r"E:\ai project\guopian"
VENDOR = os.path.join(ROOT, ".cache", "clipvendor", "CLIP-main")
WEIGHTS = os.path.join(ROOT, "models", "ViT-B-32.pt")
CAT = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")
DB = os.path.join(CAT, "catalog.db")
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "docs", "img")

sys.path.insert(0, VENDOR)
sys.path.insert(0, ROOT)

import clip  # noqa: E402
from guopian import config, imageio  # noqa: E402

PROMPTS = {
    "good": ["a photo of a person with a natural relaxed smile, eyes open, looking at the camera"],
    "blink": ["a photo of a person caught in the middle of a blink with eyes half closed",
              "a photo of a person with their eyes closed"],
    "awkward": ["a photo of a person with a strange awkward facial expression",
                "a photo of a person caught off guard with an ugly expression"],
    "talking": ["a photo of a person talking with their mouth open, mid sentence"],
    "squint": ["a photo of a person squinting in bright sunlight"],
}


def thumb(row):
    tc = imageio.ThumbCache(CAT)
    return tc.get_or_build(row["path"], row["size"], row["mtime"], config.THUMB_CARD)


def main():
    pv = np.load(os.path.join(CACHE, "photo_vecs.npy"))
    ids = json.load(open(os.path.join(CACHE, "photo_ids.json")))
    pos = {pid: i for i, pid in enumerate(ids)}

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM photos")}
    feats = {}
    for r in con.execute("""SELECT photo_id, max(blink_l) bl, max(blink_r) br,
                                   max(smile) sm, max(jaw_open) jo, max(squint) sq,
                                   max(brow_down) bd, max(gaze_away) ga, max(face_px) fp
                            FROM faces GROUP BY photo_id"""):
        feats[r["photo_id"]] = dict(r)

    usable = [pid for pid in ids
              if pid in feats and (feats[pid]["fp"] or 0) >= 60
              and (rows[pid]["face_count"] or 0) > 0]
    print("有可用人脸的近景照片: %d / %d" % (len(usable), len(ids)))

    m, _pre = clip.load(WEIGHTS, device="cpu", jit=False)
    m.eval()
    scores = {}
    for name, prompts in PROMPTS.items():
        toks = clip.tokenize(prompts, truncate=True)
        with torch.no_grad():
            tv = m.encode_text(toks)
        tv = tv / tv.norm(dim=-1, keepdim=True)
        v = np.array([pv[pos[pid]] for pid in usable]) @ tv.numpy().T
        scores[name] = v.max(axis=1)
        print("  提示词 %-8s -> 分数区间 %.3f..%.3f 均值 %.3f"
              % (name, scores[name].min(), scores[name].max(), scores[name].mean()))

    # ---- does it agree with the blendshapes we already trust? ----
    def col(key):
        return np.array([feats[pid][key] or 0.0 for pid in usable])

    blink = np.maximum(col("bl"), col("br"))
    smile = col("sm")
    jaw = col("jo")
    squint = col("sq")
    gaze = col("ga")

    def spearman(a, b):
        ra = np.argsort(np.argsort(a)).astype(float)
        rb = np.argsort(np.argsort(b)).astype(float)
        ra -= ra.mean()
        rb -= rb.mean()
        d = np.linalg.norm(ra) * np.linalg.norm(rb)
        return float(ra @ rb / d) if d else 0.0

    print("\n== CLIP 分数 vs 现有 blendshape 信号（Spearman 相关）==")
    print("  %-9s %8s %8s %8s %8s %8s" % ("", "闭眼", "微笑", "张嘴", "眯眼", "视线偏"))
    for name in PROMPTS:
        print("  %-9s %8.3f %8.3f %8.3f %8.3f %8.3f"
              % (name, spearman(scores[name], blink), spearman(scores[name], smile),
                 spearman(scores[name], jaw), spearman(scores[name], squint),
                 spearman(scores[name], gaze)))

    # ---- what does it actually pick? pictures beat statistics ----
    rs = {r["id"]: r for r in rows.values()}
    W, H, COLS = 200, 150, 6
    for name in ("blink", "awkward", "good"):
        order = np.argsort(-scores[name])[:COLS * 2]
        canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
        for n, i in enumerate(order):
            pid = usable[i]
            im = ImageOps.exif_transpose(Image.open(thumb(rows[pid]))).convert("RGB")
            im.thumbnail((W - 6, H - 6), Image.Resampling.LANCZOS)
            canvas.paste(im, ((n % COLS) * W + 3, (n // COLS) * H + 3))
        path = os.path.join(OUT, "_expr_%s.png" % name)
        canvas.save(path)
        print("saved", path)


if __name__ == "__main__":
    main()
