"""Greedy complete-linkage grouping on CLIP cosine, to see what parameters fit.

The current pHash grouping is single-linkage (union-find), so a long session at
one viewpoint chains into a giant group: measured here as 128 photos in one
"burst". Complete linkage -- every pair inside a group must pass -- caps the
diameter and is what "the same moment, interchangeable" actually means.

    python evaluation/clip_group_eval.py
"""
import json
import os
import sys

import numpy as np

ROOT = r"E:\ai project\guopian"
CACHE = os.path.join(ROOT, ".cache")
sys.path.insert(0, ROOT)

import sqlite3  # noqa: E402

DB = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294", "catalog.db")


def load():
    pv = np.load(os.path.join(CACHE, "photo_vecs.npy"))
    ids = json.load(open(os.path.join(CACHE, "photo_ids.json")))
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    meta = {r["id"]: dict(r) for r in con.execute(
        "SELECT id, rel_path, taken_ts, phash, face_count FROM photos")}
    order = sorted(ids, key=lambda i: (meta[i]["taken_ts"] or 0, meta[i]["rel_path"]))
    pos = {pid: k for k, pid in enumerate(ids)}
    return pv, ids, meta, order, pos


def group(order, meta, pos, cos, window, thr, max_size=12):
    assigned = set()
    groups = []
    for i, pid in enumerate(order):
        if pid in assigned:
            continue
        members = [pid]
        assigned.add(pid)
        for j in range(i + 1, len(order)):
            other = order[j]
            if (meta[other]["taken_ts"] or 0) - (meta[pid]["taken_ts"] or 0) > window:
                break
            if other in assigned or len(members) >= max_size:
                continue
            if all(cos[pos[other], pos[m]] >= thr for m in members):
                members.append(other)
                assigned.add(other)
        groups.append(members)
    return groups


def stats(groups):
    multi = [g for g in groups if len(g) > 1]
    sizes = sorted((len(g) for g in multi), reverse=True)
    covered = sum(sizes)
    return len(multi), sizes[:6], covered


def main():
    pv, ids, meta, order, pos = load()
    cos = pv @ pv.T
    print("照片 %d，其中有人脸 %d" % (
        len(ids), sum(1 for pid in ids if (meta[pid]["face_count"] or 0) > 0)))
    print("\n窗口(秒) 阈值  多张组  最大的几组   被分进组的照片")
    for window in (8, 15, 30):
        for thr in (0.85, 0.88, 0.90, 0.92):
            n, sizes, covered = stats(group(order, meta, pos, cos, window, thr))
            print("  %4d   %.2f  %5d   %-22s %4d (%.0f%%)"
                  % (window, thr, n, str(sizes), covered, 100.0 * covered / len(ids)))

    # the disputed pair must stay apart at every setting above
    print("\n争议那对 DSC00010/DSC00011 余弦 %.3f" % cos[pos[6], pos[7]])

    # a 128-photo pile is not a burst; show what one looks like under 15s/0.90
    groups = group(order, meta, pos, cos, 15, 0.90)
    big = max(groups, key=len)
    if len(big) > 3:
        print("\n最大的一组（%d 张）:" % len(big))
        for pid in big[:8]:
            print("   id%-5d %s  faces=%s" % (pid, meta[pid]["rel_path"].split("\\")[-1],
                                              meta[pid]["face_count"]))
        print("   ...")


if __name__ == "__main__":
    main()
