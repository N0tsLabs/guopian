"""小模型相似度实验：MobileNetV3-Small (10 MB) 的 576 维特征 vs pHash。

要回答的问题只有一个：**"同一个人、动作变了、场景没变" 这一格，小模型能不能
比 pHash 强。** 数字只用来挑阈值，最终以对照图为准。

    python evaluation/mnet_sim.py            # 只看分布
    python evaluation/mnet_sim.py sheets     # 顺便出几张对照图
"""
import json
import os
import sys

import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "82ChinaJoyCoser-a5c3da0d79")
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "docs", "img")
sys.path.insert(0, ROOT)

from guopian import config, imageio, phash  # noqa: E402

os.environ.setdefault("TORCH_HOME", os.path.join(CACHE, "torch"))


def load_rows():
    import sqlite3
    con = sqlite3.connect(os.path.join(CAT, "catalog.db"))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM photos ORDER BY taken_ts IS NULL, taken_ts, path")]
    faces = {}
    for r in con.execute("SELECT photo_id, face_px FROM faces ORDER BY face_px DESC"):
        faces.setdefault(r["photo_id"], []).append(r["face_px"])
    for r in rows:
        r["face_sizes"] = faces.get(r["id"], [])
    return rows


def embed(rows):
    from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights

    w = MobileNet_V3_Small_Weights.IMAGENET1K_V1
    m = mobilenet_v3_small(weights=w).eval()
    # 用池化后的 576 维卷积特征，而不是 1000 维分类 logits：
    # 分类头是"这是不是金毛"，检索要的是"这张图长什么样"。
    feat = torch.nn.Sequential(m.features, m.avgpool, torch.nn.Flatten())

    tc = imageio.ThumbCache(CAT)
    pre = w.transforms()
    vecs = []
    for r in rows:
        p = tc.get_or_build(r["path"], r["size"], r["mtime"], config.THUMB_CARD)
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        vecs.append(pre(im))
    out = []
    with torch.no_grad():
        for i in range(0, len(vecs), 16):
            batch = torch.stack(vecs[i:i + 16])
            v = feat(batch)
            v = torch.nn.functional.normalize(v, dim=1)
            out.append(v.numpy())
    return np.vstack(out)


def main():
    rows = load_rows()
    print("照片: %d" % len(rows))
    path = os.path.join(CACHE, "mnet_%d.npy" % len(rows))
    if os.path.exists(path):
        V = np.load(path)
        print("复用已算好的特征", V.shape)
    else:
        V = embed(rows)
        np.save(path, V)
        print("特征:", V.shape, "| 单张 %.1f KB" % (V[0].nbytes / 1024))

    n = len(rows)
    ts = np.array([r.get("taken_ts") or 0.0 for r in rows])
    ph = [r.get("phash") for r in rows]

    near, far = [], []
    hd_near, hd_far = [], []
    for i in range(n):
        for j in range(i + 1, min(n, i + 40)):
            dt = abs(ts[j] - ts[i])
            if dt > 60:
                break
            sim = float(V[i] @ V[j])
            hd = phash.hamming(ph[i], ph[j])
            near.append(sim)
            hd_near.append(hd)
    rng = np.random.default_rng(0)
    idx = rng.integers(0, n, size=(4000, 2))
    for a, b in idx:
        if a == b:
            continue
        far.append(float(V[a] @ V[b]))
        hd_far.append(phash.hamming(ph[a], ph[b]))

    print("\n相邻 60 秒内的照片对: %d" % len(near))
    print("  余弦  中位 %.3f  p10 %.3f  p90 %.3f" % (np.median(near), np.percentile(near, 10), np.percentile(near, 90)))
    print("  pHash 中位 %d  p10 %d  p90 %d" % (np.median(hd_near), np.percentile(hd_near, 10), np.percentile(hd_near, 90)))
    print("随机照片对: 余弦 中位 %.3f  p99 %.3f | pHash 中位 %d" % (
        np.median(far), np.percentile(far, 99), np.median(hd_far)))

    # 两条判据在同一批"相邻对"上的分歧：这是最值得看的样本
    near = np.array(near)
    hd_near = np.array(hd_near)
    a = np.where((hd_near > 20) & (near > 0.80))[0]      # pHash 说不同、模型说像
    b = np.where((hd_near <= 10) & (near < 0.60))[0]     # pHash 说相同、模型说不像
    print("\npHash 说不同 但 模型说像 (>0.80): %d 对" % len(a))
    print("pHash 说相同 但 模型说不像 (<0.60): %d 对" % len(b))

    if "sheets" in sys.argv:
        pairs = []
        for k in a[:8]:
            pairs.append(("模型说像", k))
        for k in b[:8]:
            pairs.append(("pHash说像", k))
        render(rows, pairs, near, hd_near)


def render(rows, pairs, sims, hds):
    """每行一对：左 pHash 说 X，右边两张图并排，方便一眼判断谁对。"""
    tc = imageio.ThumbCache(CAT)
    W, H = 260, 200
    canvas = Image.new("RGB", (W * 2 + 8, H * len(pairs)), (18, 18, 18))
    # 需要把 flat index 还原成 (i, j)
    n = len(rows)
    flat = []
    for i in range(n):
        for j in range(i + 1, min(n, i + 40)):
            flat.append((i, j))
    for row, (tag, k) in enumerate(pairs):
        i, j = flat[k]
        for col, idx in enumerate((i, j)):
            r = rows[idx]
            p = tc.get_or_build(r["path"], r["size"], r["mtime"], config.THUMB_CARD)
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            im.thumbnail((W - 6, H - 6), Image.Resampling.LANCZOS)
            canvas.paste(im, (col * W + 3, row * H + 3))
        print("  %-8s %s / %s  余弦 %.3f  pHash %d" % (
            tag, rows[i]["name"], rows[j]["name"], sims[k], hds[k]))
    path = os.path.join(OUT, "_sim_pairs.png")
    canvas.save(path)
    print("saved", path)


if __name__ == "__main__":
    main()
