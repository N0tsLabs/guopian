"""把 MobileNet 特征按"完全连接"分组，然后出图让人眼判断。

阈值不能只看 AUC 拍板：AUC 是排序质量，分组要的是"错一个就毁一组"。
所以这里扫几个阈值 × 几个时间窗，把最大的几组摊成对照图，逐组看。

    python evaluation/mnet_group.py [阈值] [时间窗秒]
"""
import os
import sys

import numpy as np
from PIL import Image, ImageOps

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "82ChinaJoyCoser-a5c3da0d79")
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "docs", "img")
sys.path.insert(0, ROOT)

from guopian import config, imageio  # noqa: E402


def rows_of(cat):
    import sqlite3
    con = sqlite3.connect(os.path.join(cat, "catalog.db"))
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT * FROM photos ORDER BY taken_ts IS NULL, taken_ts, path")]


def groups_vec(rows, V, cosine, window, max_size=12):
    """和 guopian/group.py 的 build_groups_vec 同一套逻辑：时间顺序贪心 + 完全连接。"""
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


def render(rows, groups, tag, limit=4):
    tc = imageio.ThumbCache(CAT)
    W, H = 200, 150
    pics = []
    for members in sorted(groups, key=len, reverse=True)[:limit]:
        if len(members) < 2:
            continue
        pics.append(members[:8])
    if not pics:
        return None
    cols = 8
    canvas = Image.new("RGB", (W * cols, H * len(pics)), (18, 18, 18))
    for r, members in enumerate(pics):
        for c, idx in enumerate(members):
            ph = rows[idx]
            p = tc.get_or_build(ph["path"], ph["size"], ph["mtime"], config.THUMB_CARD)
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            im.thumbnail((W - 4, H - 4), Image.Resampling.LANCZOS)
            canvas.paste(im, (c * W + 2, r * H + 2))
    path = os.path.join(OUT, "_grp_%s.png" % tag)
    canvas.save(path)
    return path


def main():
    rows = rows_of(CAT)
    V = np.load(os.path.join(CACHE, "mnet_%d.npy" % len(rows)))
    print("照片 %d | 特征 %s" % (len(rows), V.shape))

    print("\n%-6s %-6s %6s %6s %8s %6s" % ("余弦", "窗口", "多张组", "进组%", "最大组", "出图"))
    for window in (30, 120, 600):
        for cosine in (0.80, 0.85, 0.90, 0.94):
            gs = groups_vec(rows, V, cosine, window)
            multi = [g for g in gs if len(g) > 1]
            covered = sum(len(g) for g in multi)
            print("%-6.2f %-6d %6d %5.0f%% %8d" % (
                cosine, window, len(multi), 100.0 * covered / len(rows),
                max((len(g) for g in multi), default=0)), end="")
            if window == 600 and cosine in (0.85, 0.90):
                p = render(rows, gs, "%.2f" % cosine)
                print("  ", p)
            else:
                print()

    if len(sys.argv) > 2:
        cosine, window = float(sys.argv[1]), int(sys.argv[2])
        gs = groups_vec(rows, V, cosine, window)
        p = render(rows, gs, "pick", limit=6)
        print("\n%s -> %s" % ((cosine, window), p))


if __name__ == "__main__":
    main()
