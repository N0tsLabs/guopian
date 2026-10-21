"""Same expression prompts, but on the FACE CROP instead of the whole frame.

The whole-frame test failed: no correlation with blink/smile, and the top hits
were people in sunglasses rather than closed eyes. A face occupies ~5% of a
photo, so a 224x224 centre crop of the frame throws the expression away. This
re-runs the same prompts on a crop around the biggest face to see whether the
signal is there at the right scale.

    python evaluation/clip_face_eval.py
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

PROMPTS = {
    "good": ["a photo of a person with a natural relaxed smile, eyes open"],
    "blink": ["a close up photo of a face with eyes closed",
              "a close up photo of eyes half closed mid blink"],
    "awkward": ["a close up photo of a face with a strange awkward expression",
                "a close up photo of a grimacing face"],
    "talking": ["a close up photo of a face with mouth open while talking"],
    "squint": ["a close up photo of a face squinting in bright sunlight"],
}


def thumb(row):
    tc = imageio.ThumbCache(CAT)
    return tc.get_or_build(row["path"], row["size"], row["mtime"], config.THUMB_CARD)


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM photos")}
    biggest = {}
    for r in con.execute("SELECT photo_id, x, y, w, h, face_px FROM faces "
                         "ORDER BY face_px DESC"):
        biggest.setdefault(r["photo_id"], dict(r))
    feats = {r["photo_id"]: dict(r) for r in con.execute(
        """SELECT photo_id, max(blink_l) bl, max(blink_r) br, max(smoke) _x,
                  max(smile) sm, max(jaw_open) jo, max(squint) sq, max(brow_down) bd
           FROM (SELECT *, smile AS smoke FROM faces) GROUP BY photo_id""")}

    usable = [pid for pid in biggest
              if (biggest[pid]["face_px"] or 0) >= 80 and pid in rows]
    usable.sort()
    print("可用近景人脸: %d" % len(usable))

    m, pre = clip.load(WEIGHTS, device="cpu", jit=False)
    m.eval()

    vecs = []
    for pid in usable:
        p = thumb(rows[pid])
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        W, H = im.size
        f = biggest[pid]
        # face box is normalised; grow it 60% so eyes+mouth are both inside
        cw, ch = f["w"] * W, f["h"] * H
        cx, cy = f["x"] * W, f["y"] * H
        side = max(cw, ch) * 1.6
        left = max(0, cx - side / 2)
        top = max(0, cy - side / 2)
        box = (int(left), int(top), int(min(W, left + side)), int(min(H, top + side)))
        vecs.append(pre(im.crop(box)))
    with torch.no_grad():
        v = m.encode_image(torch.stack(vecs))
    v = (v / v.norm(dim=-1, keepdim=True)).numpy()
    print("face crops encoded:", v.shape)

    scores = {}
    for name, prompts in PROMPTS.items():
        with torch.no_grad():
            tv = m.encode_text(clip.tokenize(prompts, truncate=True))
        tv = tv / tv.norm(dim=-1, keepdim=True)
        scores[name] = (v @ tv.numpy().T).max(axis=1)

    def col(key):
        return np.array([feats[pid][key] or 0.0 for pid in usable])

    blink = np.maximum(col("bl"), col("br"))

    def spearman(a, b):
        ra = np.argsort(np.argsort(a)).astype(float)
        rb = np.argsort(np.argsort(b)).astype(float)
        ra -= ra.mean()
        rb -= rb.mean()
        d = np.linalg.norm(ra) * np.linalg.norm(rb)
        return float(ra @ rb / d) if d else 0.0

    print("\n== 人脸裁切后：CLIP 分数 vs blendshape（Spearman）==")
    print("  %-9s %8s %8s %8s %8s %8s" % ("", "闭眼", "微笑", "张嘴", "眯眼", "眉压"))
    for name in PROMPTS:
        print("  %-9s %8.3f %8.3f %8.3f %8.3f %8.3f"
              % (name, spearman(scores[name], blink), spearman(scores[name], col("sm")),
                 spearman(scores[name], col("jo")), spearman(scores[name], col("sq")),
                 spearman(scores[name], col("bd"))))

    W, H, COLS = 160, 160, 6
    for name in ("blink", "awkward"):
        order = np.argsort(-scores[name])[:COLS * 2]
        canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
        for n, i in enumerate(order):
            pid = usable[i]
            im = ImageOps.exif_transpose(Image.open(thumb(rows[pid]))).convert("RGB")
            Wf, Hf = im.size
            f = biggest[pid]
            cw, ch = f["w"] * Wf, f["h"] * Hf
            cx, cy = f["x"] * Wf, f["y"] * Hf
            side = max(cw, ch) * 1.8
            box = (int(max(0, cx - side / 2)), int(max(0, cy - side / 2)),
                   int(min(Wf, cx + side / 2)), int(min(Hf, cy + side / 2)))
            im.crop(box).resize((W - 6, H - 6), Image.Resampling.LANCZOS)
            canvas.paste(im.crop(box).resize((W - 6, H - 6), Image.Resampling.LANCZOS),
                         ((n % COLS) * W + 3, (n // COLS) * H + 3))
        path = os.path.join(OUT, "_faceexpr_%s.png" % name)
        canvas.save(path)
        print("saved", path)


if __name__ == "__main__":
    main()
