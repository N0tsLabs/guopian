"""Build CLIP vectors for the tags and for every photo, then evaluate.

    python evaluation/clip_index.py build     # tags + all photos -> .cache/*.npy
    python evaluation/clip_index.py sim       # does cosine separate "same moment"?
    python evaluation/clip_index.py search 湖 雪山 人像
    python evaluation/clip_index.py sheet 湖  # dump top-9 as a contact sheet

Prototype only. Nothing here is wired into the app yet; the point is to measure
whether a local CLIP actually answers the questions we are asking it, on this
user's real library, before any of it ships.
"""
import json
import os
import sqlite3
import sys
import time

import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = r"E:\ai project\guopian"
VENDOR = os.path.join(ROOT, ".cache", "clipvendor", "CLIP-main")
WEIGHTS = os.path.join(ROOT, "models", "ViT-B-32.pt")
CAT = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")
DB = os.path.join(CAT, "catalog.db")
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "docs", "img")

sys.path.insert(0, VENDOR)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clip  # noqa: E402
from guopian import config, imageio  # noqa: E402
import scene_tags  # noqa: E402

_model = None


def model():
    global _model
    if _model is None:
        m, pre = clip.load(WEIGHTS, device="cpu", jit=False)
        m.eval()
        _model = (m, pre)
    return _model


def rows():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con.execute("SELECT * FROM photos ORDER BY id").fetchall()


def thumb(row):
    tc = imageio.ThumbCache(CAT)
    return tc.get_or_build(row["path"], row["size"], row["mtime"], config.THUMB_CARD)


def prebuild(rs, threads=8):
    """Build the card thumbnails that are not cached yet.

    Only 177 of 1428 had ever been looked at, so most are missing. Decoding a
    6000x4000 JPEG is the slow part and PIL releases the GIL, so threads help.
    """
    todo = [r for r in rs if not os.path.exists(thumb(r))]
    print("thumbs to build: %d / %d" % (len(todo), len(rs)), flush=True)
    if not todo:
        return
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    done = 0

    def one(r):
        try:
            thumb(r)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=threads) as ex:
        for _ in ex.map(one, todo):
            done += 1
            if done % 100 == 0:
                el = time.time() - t0
                print("  %4d/%d  %.1f/s  %.0fs" % (done, len(todo), done / el, el), flush=True)
    print("thumbs done in %.0fs" % (time.time() - t0), flush=True)


def encode_images(paths, batch=24):
    m, pre = model()
    vecs = []
    t0 = time.time()
    for i in range(0, len(paths), batch):
        chunk = paths[i:i + batch]
        tensors = []
        for p in chunk:
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            tensors.append(pre(im))
        with torch.no_grad():
            v = m.encode_image(torch.stack(tensors))
        v = v / v.norm(dim=-1, keepdim=True)
        vecs.append(v.numpy())
        if (i // batch) % 10 == 0:
            el = time.time() - t0
            print("  %4d/%d  %.1f photo/s" % (i + len(chunk), len(paths),
                                              (i + len(chunk)) / max(el, 1e-6)),
                  flush=True)
    return np.concatenate(vecs, axis=0)


def cmd_build():
    tags = scene_tags.as_dicts()
    m, _pre = model()
    toks = clip.tokenize([t["en"] for t in tags], truncate=True)
    with torch.no_grad():
        tv = m.encode_text(toks)
    tv = (tv / tv.norm(dim=-1, keepdim=True)).numpy()
    np.save(os.path.join(CACHE, "tag_vecs.npy"), tv.astype(np.float32))
    with open(os.path.join(CACHE, "tag_meta.json"), "w", encoding="utf-8") as f:
        json.dump(tags, f, ensure_ascii=False, indent=1)
    print("tags: %d x %d" % tv.shape)

    rs = rows()
    prebuild(rs)
    paths = [thumb(r) for r in rs]
    missing = [p for p in paths if not os.path.exists(p)]
    print("photos: %d, missing thumbs: %d" % (len(rs), len(missing)))
    pv = encode_images(paths)
    np.save(os.path.join(CACHE, "photo_vecs.npy"), pv.astype(np.float32))
    with open(os.path.join(CACHE, "photo_ids.json"), "w") as f:
        json.dump([r["id"] for r in rs], f)
    print("photo vectors:", pv.shape)


def load():
    pv = np.load(os.path.join(CACHE, "photo_vecs.npy"))
    ids = json.load(open(os.path.join(CACHE, "photo_ids.json")))
    tv = np.load(os.path.join(CACHE, "tag_vecs.npy"))
    tags = json.load(open(os.path.join(CACHE, "tag_meta.json"), encoding="utf-8"))
    return pv, ids, tv, tags


def cmd_sim():
    from guopian import phash as P
    pv, ids, _tv, _tags = load()
    pos = {pid: i for i, pid in enumerate(ids)}
    rs = {r["id"]: r for r in rows()}
    cos = pv @ pv.T

    print("== 余弦 vs pHash 距离（时间相近的对）==")
    bands = {"0-4": [], "5-10": [], "11-20": [], "21-40": []}
    ordered = sorted(rs.values(), key=lambda r: r["taken_ts"] or 0)
    for i, r in enumerate(ordered):
        for j in range(i + 1, min(len(ordered), i + 10)):
            s = ordered[j]
            if (s["taken_ts"] or 0) - (r["taken_ts"] or 0) > 30:
                break
            d = P.hamming(r["phash"], s["phash"])
            key = "0-4" if d <= 4 else "5-10" if d <= 10 else "11-20" if d <= 20 else "21-40" if d <= 40 else None
            if key:
                bands[key].append((r["id"], s["id"]))
    for k, lst in bands.items():
        vals = [cos[pos[a], pos[b]] for a, b in lst]
        if not vals:
            continue
        v = np.array(vals)
        print("  pHash %-6s n=%-5d 余弦 均值 %.3f  10%%分位 %.3f  5%%分位 %.3f  最低 %.3f"
              % (k, len(v), v.mean(), np.percentile(v, 10), np.percentile(v, 5), v.min()))

    print("\n== 库里那对争议照片 ==")
    print("  DSC00010 vs DSC00011 余弦 = %.3f" % cos[pos[6], pos[7]])
    print("  真·近似重复(id7 vs id8, 两张空景) 余弦 = %.3f" % cos[pos[7], pos[8]])

    print("\n== 用余弦重做分组（时间窗 30 秒 + 余弦阈值）==")
    for thr in (0.80, 0.85, 0.90, 0.93, 0.95):
        # complete linkage: every pair inside a group must pass
        parent = list(range(len(ordered)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        idx_ok = []
        for i, r in enumerate(ordered):
            for j in range(i + 1, min(len(ordered), i + 40)):
                s = ordered[j]
                if (s["taken_ts"] or 0) - (r["taken_ts"] or 0) > 30:
                    break
                if cos[pos[r["id"]], pos[s["id"]]] >= thr:
                    idx_ok.append((i, j))
        # union, then split any group whose diameter is below thr (complete linkage)
        for i, j in idx_ok:
            a, b = find(i), find(j)
            if a != b:
                parent[b] = a
        buckets = {}
        for i in range(len(ordered)):
            buckets.setdefault(find(i), []).append(i)
        clean = 0
        for members in buckets.values():
            if len(members) < 2:
                continue
            ok = all(cos[pos[ordered[a]["id"]], pos[ordered[b]["id"]]] >= thr
                     for ai, a in enumerate(members) for b in members[ai + 1:])
            if ok:
                clean += 1
        sizes = sorted((len(v) for v in buckets.values() if len(v) > 1), reverse=True)
        same = any(6 in [ordered[i]["id"] for i in v] and 7 in [ordered[i]["id"] for i in v]
                   for v in buckets.values())
        print("  阈值 %.2f -> 多张组 %3d（完全连接后 %3d），最大组 %s，争议对同组 %s"
              % (thr, len(sizes), clean, sizes[:5], same))


def cmd_search(queries):
    pv, ids, tv, tags = load()
    alias = scene_tags.alias_index()
    for q in queries:
        hit = alias.get(q)
        if hit is None:
            cand = [t["zh"] for t in tags if q in t["zh"] or any(q in a for a in t["alias"])]
            hit = cand[0] if cand else None
        if hit is None:
            print("\n[%s] 词表里没有" % q)
            continue
        k = [t["zh"] for t in tags].index(hit)
        score = pv @ tv[k]
        order = np.argsort(-score)[:9]
        print("\n[%s] -> 标签 %s (%s)" % (q, hit, tags[k]["en"]))
        for n, i in enumerate(order, 1):
            print("   %d. id%-5d %-16s %.3f" % (n, ids[i],
                  os.path.basename(dict((r['id'], r) for r in rows())[ids[i]]['rel_path']),
                  score[i]))


def cmd_sheet(queries):
    pv, ids, tv, tags = load()
    alias = scene_tags.alias_index()
    rs = {r["id"]: r for r in rows()}
    W, H, COLS = 220, 165, 5
    for q in queries:
        hit = alias.get(q)
        if hit is None:
            continue
        k = [t["zh"] for t in tags].index(hit)
        score = pv @ tv[k]
        order = np.argsort(-score)[: COLS * 2]
        canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
        for n, i in enumerate(order):
            im = ImageOps.exif_transpose(Image.open(thumb(rs[ids[i]]))).convert("RGB")
            im.thumbnail((W - 6, H - 6), Image.Resampling.LANCZOS)
            canvas.paste(im, ((n % COLS) * W + 3, (n // COLS) * H + 3))
        path = os.path.join(OUT, "_clip_%s.png" % hit)
        canvas.save(path)
        print("saved", path, "top scores", np.round(score[order[:5]], 3))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        cmd_build()
    elif cmd == "sim":
        cmd_sim()
    elif cmd == "search":
        cmd_search(sys.argv[2:])
    elif cmd == "sheet":
        cmd_sheet(sys.argv[2:])
