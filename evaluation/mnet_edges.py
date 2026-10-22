"""边界样本：最容易判错的那几对，摊出来人眼看。

组内最低余弦的那几对 = 最可能"错并"的；时间上挨着却没过阈值的那几对 =
最可能"漏并"的。这两个集合才是阈值该不该动的依据，不是平均分。

    python evaluation/mnet_edges.py [余弦阈值] [窗口秒]
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageOps

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "82ChinaJoyCoser-a5c3da0d79")
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "docs", "img")
sys.path.insert(0, ROOT)

from guopian import config, imageio, phash  # noqa: E402


def rows_of(cat):
    import sqlite3
    con = sqlite3.connect(os.path.join(cat, "catalog.db"))
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT * FROM photos ORDER BY taken_ts IS NULL, taken_ts, path")]


def groups_vec(rows, V, cosine, window, max_size=12):
    n = len(rows)
    ts = [r.get("taken_ts") or 0.0 for r in rows]
    taken = [False] * n
    out = []
    for i in range(n):
        if taken[i]:
            continue
        taken[i] = True
        members = [i]
        for j in range(i + 1, n):
            if taken[j]:
                continue
            if ts[j] - ts[i] > window:
                break
            if len(members) >= max_size:
                break
            if all(float(V[j] @ V[m]) >= cosine for m in members):
                members.append(j)
                taken[j] = True
        out.append(members)
    return out


def sheet(rows, pairs, tag):
    tc = imageio.ThumbCache(CAT)
    W, H, PAD = 240, 190, 18
    canvas = Image.new("RGB", (W * 2 + 10, (H + PAD) * len(pairs)), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    for r, (i, j, note) in enumerate(pairs):
        for c, idx in enumerate((i, j)):
            p = tc.get_or_build(rows[idx]["path"], rows[idx]["size"], rows[idx]["mtime"],
                                config.THUMB_CARD)
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            im.thumbnail((W - 4, H - 4), Image.Resampling.LANCZOS)
            canvas.paste(im, (c * W + 2, r * (H + PAD) + 2))
        draw.text((4, r * (H + PAD) + H + 2), note, fill=(200, 200, 200))
    path = os.path.join(OUT, "_edge_%s.png" % tag)
    canvas.save(path)
    return path


def main():
    cosine = float(sys.argv[1]) if len(sys.argv) > 1 else 0.90
    window = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    rows = rows_of(CAT)
    V = np.load(os.path.join(CACHE, "mnet_%d.npy" % len(rows)))
    gs = groups_vec(rows, V, cosine, window)
    ts = [r.get("taken_ts") or 0.0 for r in rows]

    # 1) 组内最弱的那一对（错并的嫌疑最大）
    weakest = []
    for members in gs:
        if len(members) < 2:
            continue
        best = None
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                c = float(V[members[a]] @ V[members[b]])
                if best is None or c < best[0]:
                    best = (c, members[a], members[b])
        if best:
            weakest.append(best)
    weakest.sort()
    pairs = [(i, j, "组内最弱 %.3f  %s / %s" % (c, rows[i]["name"], rows[j]["name"]))
             for c, i, j in weakest[:8]]
    print("组内最弱的 8 对:", sheet(rows, pairs, "merge"))

    # 2) 时间上挨着、但没过阈值的一对（漏并的嫌疑最大）
    miss = []
    for i in range(len(rows)):
        for j in range(i + 1, min(len(rows), i + 12)):
            if ts[j] - ts[i] > 60:
                break
            c = float(V[i] @ V[j])
            if c < cosine:
                miss.append((c, i, j))
    miss.sort(reverse=True)          # 最接近阈值的先看
    pairs = [(i, j, "没过线 %.3f (阈值 %.2f)  %s / %s" % (c, cosine, rows[i]["name"], rows[j]["name"]))
             for c, i, j in miss[:8]]
    print("没过线的 8 对:", sheet(rows, pairs, "split"))

    # 3) 顺手核对：pHash 与模型的分歧
    diff = []
    for i in range(len(rows)):
        for j in range(i + 1, min(len(rows), i + 12)):
            if ts[j] - ts[i] > 60:
                break
            c = float(V[i] @ V[j])
            hd = phash.hamming(rows[i].get("phash"), rows[j].get("phash"))
            if hd > 20 and c >= cosine:
                diff.append((c, i, j, hd))
    diff.sort(key=lambda x: -x[3])
    pairs = [(i, j, "模型 %.3f 通过 / pHash %d 说不同  %s / %s" % (c, hd, rows[i]["name"], rows[j]["name"]))
             for c, i, j, hd in diff[:8]]
    if pairs:
        print("分歧的 8 对:", sheet(rows, pairs, "pHash"))


if __name__ == "__main__":
    main()
