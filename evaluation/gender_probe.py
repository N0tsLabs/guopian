"""CLIP 能不能从人脸裁切里分出男女？—— 用人眼核对，不靠分数自我感觉。

没有标注数据，所以做法和之前一样：把一个词的 Top-N 和 Bottom-N 都摊成对照图，
一眼能不能看出它其实在瞎猜。分数高低本身不算证据。

    python evaluation/gender_probe.py
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
OUT = os.path.join(ROOT, "docs", "img")
sys.path.insert(0, VENDOR)
sys.path.insert(0, ROOT)

import clip  # noqa: E402
from guopian import config, imageio  # noqa: E402

PAIRS = {
    "性别": (["a close up photo of a woman's face",
              "a photo of a female person"],
             ["a close up photo of a man's face",
              "a photo of a male person"]),
    "好坏": (["a sharp professional portrait photograph"],
             ["a blurry amateur snapshot photo"]),
}


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM photos")}
    biggest = {}
    for r in con.execute("SELECT photo_id, x, y, w, h, face_px FROM faces ORDER BY face_px DESC"):
        biggest.setdefault(r["photo_id"], dict(r))

    usable = [pid for pid, f in biggest.items()
              if (f["face_px"] or 0) >= 90 and pid in rows]
    usable.sort()
    print("可用近景人脸: %d" % len(usable))

    m, pre = clip.load(WEIGHTS, device="cpu", jit=False)
    m.eval()

    tc = imageio.ThumbCache(CAT)
    crops = {}
    for pid in usable:
        p = tc.get_or_build(rows[pid]["path"], rows[pid]["size"], rows[pid]["mtime"],
                            config.THUMB_CARD)
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        W, H = im.size
        f = biggest[pid]
        side = max(f["w"] * W, f["h"] * H) * 1.7
        cx, cy = f["x"] * W, f["y"] * H
        box = (int(max(0, cx - side / 2)), int(max(0, cy - side / 2)),
               int(min(W, cx + side / 2)), int(min(H, cy + side / 2)))
        crops[pid] = im.crop(box)

    vecs = []
    for pid in usable:
        vecs.append(pre(crops[pid]))
    with torch.no_grad():
        v = m.encode_image(torch.stack(vecs))
    v = (v / v.norm(dim=-1, keepdim=True)).numpy()

    for label, (pos, neg) in PAIRS.items():
        with torch.no_grad():
            tp = m.encode_text(clip.tokenize(pos, truncate=True))
            tn = m.encode_text(clip.tokenize(neg, truncate=True))
        tp = (tp / tp.norm(dim=-1, keepdim=True)).numpy().max(axis=0)
        tn = (tn / tn.norm(dim=-1, keepdim=True)).numpy().max(axis=0)
        d = v @ tp - v @ tn
        order = np.argsort(-d)
        print("\n%s: 正类得分区间 %.3f..%.3f | 与负类之差 均值 %.3f 正数占比 %.0f%%"
              % (label, (v @ tp).min(), (v @ tp).max(), d.mean(), 100.0 * (d > 0).mean()))

        W, H, COLS = 140, 140, 8
        for side, idx in (("正", order[:COLS * 2]), ("负", order[-COLS * 2:][::-1])):
            canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
            for n, i in enumerate(idx):
                im = crops[usable[i]].resize((W - 4, H - 4), Image.Resampling.LANCZOS)
                canvas.paste(im, ((n % COLS) * W + 2, (n // COLS) * H + 2))
            path = os.path.join(OUT, "_%s_%s.png" % (label, side))
            canvas.save(path)
            print("saved", path)


if __name__ == "__main__":
    main()
