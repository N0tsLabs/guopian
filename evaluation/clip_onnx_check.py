"""Does the int8 ONNX model rank photos the same as the fp32 torch model?

Shipping the quantised tower saves 250 MB of download, but only if it agrees
with the model every threshold was measured on. Checked two ways:
  * per-photo embedding agreement (cosine int8 vs fp32)
  * do the top-20 hits for each scene word come out the same?

    python evaluation/clip_onnx_check.py
"""
import json
import os
import sqlite3
import sys
import time

import numpy as np
from PIL import Image

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")
CACHE = os.path.join(ROOT, ".cache")
MODEL = os.path.join(ROOT, "models", "clip_vision.int8.onnx")

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guopian import config, imageio  # noqa: E402
from export_clip_onnx import preprocess  # noqa: E402

N_PX = 224


def main():
    import onnxruntime as ort

    pv32 = np.load(os.path.join(CACHE, "photo_vecs.npy"))
    ids = json.load(open(os.path.join(CACHE, "photo_ids.json")))
    tv = np.load(os.path.join(CACHE, "tag_vecs.npy"))
    tags = json.load(open(os.path.join(CACHE, "tag_meta.json"), encoding="utf-8"))

    con = sqlite3.connect(os.path.join(CAT, "catalog.db"))
    con.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM photos")}
    tc = imageio.ThumbCache(CAT)

    sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    t0 = time.time()
    out = []
    B = 16
    for i in range(0, len(ids), B):
        batch = []
        for pid in ids[i:i + B]:
            r = rows[pid]
            p = tc.get_or_build(r["path"], r["size"], r["mtime"], config.THUMB_CARD)
            batch.append(preprocess(Image.open(p)))
        v = sess.run(None, {"pixels": np.stack(batch).astype(np.float32)})[0]
        v = v / np.linalg.norm(v, axis=1, keepdims=True)
        out.append(v)
        if (i // B) % 20 == 0:
            print("  %d/%d  %.0fs" % (i + len(batch), len(ids), time.time() - t0), flush=True)
    pv8 = np.concatenate(out).astype(np.float32)
    np.save(os.path.join(CACHE, "photo_vecs_int8.npy"), pv8)
    dt = time.time() - t0
    print("int8 encoded %d in %.0fs (%.0f ms each)" % (len(ids), dt, dt * 1000 / len(ids)))

    agree = (pv32 * pv8).sum(axis=1)
    print("\n每张照片的向量一致性: 均值 %.4f  最低 %.4f  低于0.95的有 %d 张"
          % (agree.mean(), agree.min(), int((agree < 0.95).sum())))

    print("\n各标签 top-20 重合度（fp32 vs int8）:")
    for name in ("湖泊", "人像", "雪山", "夜景", "食物", "花", "经幡", "城市街道"):
        k = [t["zh"] for t in tags].index(name)
        s32 = pv32 @ tv[k]
        s8 = pv8 @ tv[k]
        top32 = set(np.argsort(-s32)[:20])
        top8 = set(np.argsort(-s8)[:20])
        inter = len(top32 & top8)
        print("  %-6s 重合 %2d/20   (满分 20)" % (name, inter))

    # the pair that started all this
    pos = {pid: i for i, pid in enumerate(ids)}
    for a, b, label in ((6, 7, "争议对 双人合影/空景"), (7, 8, "真·空景重拍")):
        print("  %s: fp32 %.3f  int8 %.3f"
              % (label, pv32[pos[a]] @ pv32[pos[b]], pv8[pos[a]] @ pv8[pos[b]]))


if __name__ == "__main__":
    main()
