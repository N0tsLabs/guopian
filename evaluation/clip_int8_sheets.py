"""Do the int8 search results still look right? Numbers plus pictures.

Top-20 overlap between fp32 and int8 was 11-19/20, which mostly says the tail
is a near-tie. What matters is whether the results a person sees are still the
right photos, so this prints top-5/top-10 agreement and writes contact sheets
from the int8 model for a visual check.

    python evaluation/clip_int8_sheets.py
"""
import json
import os
import sqlite3
import sys

import numpy as np
from PIL import Image, ImageOps

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "docs", "img")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guopian import config, imageio  # noqa: E402


def main():
    pv32 = np.load(os.path.join(CACHE, "photo_vecs.npy"))
    pv8 = np.load(os.path.join(CACHE, "photo_vecs_int8.npy"))
    ids = json.load(open(os.path.join(CACHE, "photo_ids.json")))
    tv = np.load(os.path.join(CACHE, "tag_vecs.npy"))
    tags = json.load(open(os.path.join(CACHE, "tag_meta.json"), encoding="utf-8"))
    names = [t["zh"] for t in tags]

    con = sqlite3.connect(os.path.join(CAT, "catalog.db"))
    con.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM photos")}
    tc = imageio.ThumbCache(CAT)

    print("%-8s %6s %7s %7s" % ("", "top5", "top10", "top20"))
    for name in ("湖泊", "人像", "雪山", "夜景", "食物", "花", "经幡", "城市街道", "树木", "晴天"):
        if name not in names:
            continue
        k = names.index(name)
        o32 = np.argsort(-(pv32 @ tv[k]))
        o8 = np.argsort(-(pv8 @ tv[k]))
        row = []
        for n in (5, 10, 20):
            row.append(len(set(o32[:n]) & set(o8[:n])))
        print("%-8s %6d %7d %7d" % (name, *row))

    W, H, COLS = 200, 150, 5
    for name in ("湖泊", "人像", "雪山"):
        k = names.index(name)
        score = pv8 @ tv[k]
        order = np.argsort(-score)[: COLS * 2]
        canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
        for n, i in enumerate(order):
            r = rows[ids[i]]
            p = tc.get_or_build(r["path"], r["size"], r["mtime"], config.THUMB_CARD)
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            im.thumbnail((W - 6, H - 6), Image.Resampling.LANCZOS)
            canvas.paste(im, ((n % COLS) * W + 3, (n // COLS) * H + 3))
        path = os.path.join(OUT, "_int8_%s.png" % name)
        canvas.save(path)
        print("saved", path)


if __name__ == "__main__":
    main()
