"""一次性把词表编码成向量，写进 guopian/data/tag_vecs.npy（提交进仓库）。

只在加词、换模型时跑。照片向量不用重算 —— 词和照片在同一个空间。

    python evaluation/export_tags.py [--onnx]
"""
import os
import sys

import numpy as np

ROOT = r"E:\ai project\guopian"
VENDOR = os.path.join(ROOT, ".cache", "clipvendor", "CLIP-main")
WEIGHTS = os.path.join(ROOT, "models", "ViT-B-32.pt")
OUT = os.path.join(ROOT, "guopian", "data", "tag_vecs.npy")

sys.path.insert(0, ROOT)
sys.path.insert(0, VENDOR)

from guopian import tags  # noqa: E402


def main():
    import torch
    import clip

    model, _ = clip.load(WEIGHTS, device="cpu", jit=False)
    model.eval()
    prompts = [t[1] for t in tags.TAGS]
    with torch.no_grad():
        v = model.encode_text(clip.tokenize(prompts, truncate=True))
    v = v / v.norm(dim=-1, keepdim=True)
    arr = v.numpy().astype(np.float16)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.save(OUT, arr)
    print("wrote %s  %d tags x %d  %.0f KB"
          % (OUT, arr.shape[0], arr.shape[1], os.path.getsize(OUT) / 1024))
    print("tags:", ", ".join(tags.names()[:12]), "...")


if __name__ == "__main__":
    main()
