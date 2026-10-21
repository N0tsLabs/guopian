"""Load OpenAI CLIP ViT-B/32 from the vendored source and encode photos.

Reads the already-built `card` thumbnails straight out of the catalog, so this
does not depend on the dev server being up or on which library it has open.

    python evaluation/clip_probe.py [first_id] [count]
"""
import os
import sqlite3
import sys
import time

import numpy as np
import torch
from PIL import Image, ImageOps

VENDOR = r"E:\ai project\guopian\.cache\clipvendor\CLIP-main"
WEIGHTS = r"E:\ai project\guopian\models\ViT-B-32.pt"
DB = r"E:\ai project\guopian\catalogs\101MSDCF-61e11b7294\catalog.db"
THUMBS = r"E:\ai project\guopian\catalogs\101MSDCF-61e11b7294"

sys.path.insert(0, VENDOR)
sys.path.insert(0, r"E:\ai project\guopian")

import clip  # noqa: E402
from guopian import config, imageio  # noqa: E402


def thumb_path(row) -> str:
    key = imageio.ThumbCache.key.__func__(None, row["path"], row["size"],
                                         row["mtime"], config.THUMB_CARD) \
        if False else None
    # ThumbCache.key only uses path/size/mtime/edge, so a throwaway instance works.
    tc = imageio.ThumbCache(THUMBS)
    key = tc.key(row["path"], row["size"], row["mtime"], config.THUMB_CARD)
    return tc.path_for(key, config.THUMB_CARD)


def load(pid=None, limit=8):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if pid is None:
        rows = con.execute("SELECT * FROM photos ORDER BY id LIMIT ?", (limit,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM photos ORDER BY id LIMIT ? OFFSET ?",
                           (limit, pid)).fetchall()
    out = []
    for r in rows:
        p = thumb_path(r)
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        out.append((r["id"], r["rel_path"], im))
    return out


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    t0 = time.time()
    model, preprocess = clip.load(WEIGHTS, device="cpu", jit=False)
    model.eval()
    print("model loaded in %.1fs  dim=%d" % (time.time() - t0, model.visual.output_dim))

    items = load(start, count)
    batch = torch.stack([preprocess(im) for _, _, im in items])
    t1 = time.time()
    with torch.no_grad():
        v = model.encode_image(batch)
    v = v / v.norm(dim=-1, keepdim=True)
    dt = time.time() - t1
    print("encoded %d in %.2fs  (%.0f ms each)" % (len(items), dt, dt * 1000 / len(items)))

    sim = (v @ v.T).numpy()
    names = [str(i) for i, _, _ in items]
    print("\ncosine similarity")
    print("      " + "".join("%7s" % n for n in names))
    for k, n in enumerate(names):
        print("%5s " % n + "".join("%7.3f" % sim[k, j] for j in range(len(names))))

    ids = [i for i, _, _ in items]
    if 6 in ids and 7 in ids:
        print("\nDSC00010 / DSC00011 (person vs empty) cosine = %.3f"
              % sim[ids.index(6), ids.index(7)])
    np.save(r"E:\ai project\guopian\.cache\clip_sample.npy", v.numpy())


if __name__ == "__main__":
    main()
