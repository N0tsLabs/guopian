"""MobileNet 特征够不够用？先量可分性，再决定要不要用它。

第一次量的结果不对劲：随机照片对的余弦中位数 0.706、p99 0.891，而相邻 60 秒
内的照片对中位数才 0.872 —— 两个分布几乎叠在一起。ImageNet 分类器倒二层
特征就是这样：它学的是"这是不是金毛"，不是"这是不是同一个场景"，通道之间
高度相关，余弦会被压到 0.7-0.9 这个窄区间。

这里比较三种处理：
  raw      直接用 576 维
  white    PCA 白化到 256 维（检索界的标准做法）
  white+  在输入 320 上再白化

判据用 AUC：把"60 秒内的照片对"当正样本、"随机照片对"当负样本，看哪种表示
能把它们排开。AUC 只用来选表示，最终仍以对照图为准。

    python evaluation/mnet_repr.py
"""
import os
import sys

import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "82ChinaJoyCoser-a5c3da0d79")
CACHE = os.path.join(ROOT, ".cache")
sys.path.insert(0, ROOT)
os.environ.setdefault("TORCH_HOME", os.path.join(CACHE, "torch"))

from guopian import config, imageio  # noqa: E402


def rows_of(cat):
    import sqlite3
    con = sqlite3.connect(os.path.join(cat, "catalog.db"))
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT * FROM photos ORDER BY taken_ts IS NULL, taken_ts, path")]


def embed(rows, edge, gem=False):
    from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights

    w = MobileNet_V3_Small_Weights.IMAGENET1K_V1
    m = mobilenet_v3_small(weights=w).eval()
    tc = imageio.ThumbCache(CAT)
    pre = w.transforms()
    tensors = []
    for r in rows:
        p = tc.get_or_build(r["path"], r["size"], r["mtime"], config.THUMB_CARD)
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        if edge != 224:
            im = im.resize((edge, edge), Image.Resampling.BILINEAR)
        tensors.append(pre(im) if edge == 224 else torch.from_numpy(
            np.asarray(im, dtype=np.float32).transpose(2, 0, 1) / 255.0))
    out = []
    with torch.no_grad():
        for i in range(0, len(tensors), 16):
            x = torch.stack(tensors[i:i + 16])
            if edge != 224:
                x = torch.nn.functional.interpolate(x, size=(224, 224), mode="bilinear",
                                                    align_corners=False)
                x = (x - torch.tensor([0.485, 0.456, 0.406])[None, :, None, None]) / \
                    torch.tensor([0.229, 0.224, 0.225])[None, :, None, None]
            f = m.features(x)
            if gem:
                f = f.clamp(min=1e-6).pow(3).mean(dim=(2, 3)).pow(1 / 3)
            else:
                f = torch.nn.functional.adaptive_avg_pool2d(f, 1).flatten(1)
            out.append(torch.nn.functional.normalize(f, dim=1).numpy())
    return np.vstack(out)


def whiten(V, dim=256):
    mu = V.mean(axis=0, keepdims=True)
    X = V - mu
    # 用 SVD 做 PCA，白化到 dim 维
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    k = min(dim, len(S))
    W = Vt[:k].T / (S[:k][None, :] / np.sqrt(len(X)))
    Z = X @ W
    return Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)


def auc(pos, neg):
    """P(正样本分数 > 负样本分数)，曼-惠特尼形式。"""
    allv = np.concatenate([pos, neg])
    order = allv.argsort()
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(allv) + 1)
    rp = ranks[:len(pos)].sum()
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def pairs(rows, V, span=40, window=60):
    n = len(rows)
    ts = np.array([r.get("taken_ts") or 0.0 for r in rows])
    pos = []
    for i in range(n):
        for j in range(i + 1, min(n, i + span)):
            if abs(ts[j] - ts[i]) > window:
                break
            pos.append(float(V[i] @ V[j]))
    rng = np.random.default_rng(0)
    idx = rng.integers(0, n, size=(4000, 2))
    neg = [float(V[a] @ V[b]) for a, b in idx if a != b]
    return np.array(pos), np.array(neg)


def main():
    rows = rows_of(CAT)
    print("照片:", len(rows))
    for name, fn in (("raw 576d", lambda V: V),
                     ("white 256d", whiten),
                     ("white 128d", lambda V: whiten(V, 128))):
        cache = os.path.join(CACHE, "mnet_%s.npy" % name.replace(" ", "_"))
        if os.path.exists(cache):
            V = np.load(cache)
        else:
            base = os.path.join(CACHE, "mnet_%d.npy" % len(rows))
            V0 = np.load(base) if os.path.exists(base) else None
            if V0 is None:
                V0 = embed(rows, 224)
                np.save(base, V0)
            V = fn(V0)
            np.save(cache, V)
        pos, neg = pairs(rows, V)
        print("%-12s 正样本余弦 中位 %.3f | 负样本 中位 %.3f p99 %.3f | AUC %.3f"
              % (name, np.median(pos), np.median(neg), np.percentile(neg, 99),
                 auc(pos, neg)))


if __name__ == "__main__":
    main()
