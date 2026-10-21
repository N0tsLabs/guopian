"""每张照片的分数先按它自己的词分布做 z-score，再比。

为什么：经幡最高分 0.254，但"公园/雾/强光"这类通用词在几乎所有户外照片上
都拿 0.26+，于是经幡永远排不进前三 —— 不是它不像，而是整张照片对所有词都
偏高。先把每张照片的词分数标准化（减自己的均值、除自己的标准差），
"这张特别像经幡"才会浮出来。这是检索里常用的 per-query/per-item 归一化。

    python evaluation/search_zscore.py
写对照图：python evaluation/search_zscore.py sheet 经幡 夜景
"""
import os
import sys

import numpy as np

ROOT = r"E:\ai project\guopian"
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "docs", "img")
sys.path.insert(0, ROOT)

from guopian import tags  # noqa: E402


def zscores(pv, tv):
    s = pv @ tv.T
    mu = s.mean(axis=1, keepdims=True)
    sd = s.std(axis=1, keepdims=True) + 1e-6
    return (s - mu) / sd, s


def main():
    pv = np.load(os.path.join(CACHE, "photo_vecs_int8.npy")).astype(np.float32)
    tv = tags.vectors()
    names = tags.names()
    z, raw = zscores(pv, tv)

    print("%-8s %7s %7s %7s   %s" % ("", "z>1.5", "z>2.0", "z>2.5", "最高 z"))
    print("-- 命中")
    for w in ("湖泊", "人像", "雪山", "经幡", "寺庙", "夜景", "山峰", "栈道"):
        k = names.index(w)
        print("  %-6s %7d %7d %7d   %.2f"
              % (w, int((z[:, k] > 1.5).sum()), int((z[:, k] > 2.0).sum()),
                 int((z[:, k] > 2.5).sum()), z[:, k].max()))
    print("-- 不命中")
    for w in ("海边", "食物", "猫", "沙漠", "地铁", "蛋糕", "火锅"):
        k = names.index(w)
        print("  %-6s %7d %7d %7d   %.2f"
              % (w, int((z[:, k] > 1.5).sum()), int((z[:, k] > 2.0).sum()),
                 int((z[:, k] > 2.5).sum()), z[:, k].max()))

    if len(sys.argv) > 2 and sys.argv[1] == "sheet":
        import json
        import sqlite3
        from PIL import Image, ImageOps

        from guopian import config, imageio

        cat = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")
        con = sqlite3.connect(os.path.join(cat, "catalog.db"))
        con.row_factory = sqlite3.Row
        rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM photos")}
        ids = json.load(open(os.path.join(CACHE, "photo_ids.json")))
        tc = imageio.ThumbCache(cat)
        W, H, COLS = 200, 150, 5
        for w in sys.argv[2:]:
            k = names.index(w)
            order = np.argsort(-z[:, k])[: COLS * 2]
            canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
            for n, i in enumerate(order):
                r = rows[ids[i]]
                p = tc.get_or_build(r["path"], r["size"], r["mtime"], config.THUMB_CARD)
                im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
                im.thumbnail((W - 6, H - 6), Image.Resampling.LANCZOS)
                canvas.paste(im, ((n % COLS) * W + 3, (n // COLS) * H + 3))
            path = os.path.join(OUT, "_z_%s.png" % w)
            canvas.save(path)
            print("saved", path)


if __name__ == "__main__":
    main()
