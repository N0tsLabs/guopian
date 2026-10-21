"""分组：pHash 单链 vs 画面向量完全连接，在真实库上对比。

判据三条，都是能数出来的：
  1. 争议那对（双人合影 / 空景，余弦 0.58）分不分组；
  2. 最大的组有多大 —— 单链会把一个上午串成上百张；
  3. 有多少组"一张有人、一张没人" —— 这是用户实际抱怨的那种错。

    python evaluation/group_compare.py [catalog_dir]
"""
import os
import sys
from collections import defaultdict

ROOT = r"E:\ai project\guopian"
sys.path.insert(0, ROOT)

from guopian import config, group  # noqa: E402
from guopian.store import Store  # noqa: E402

CAT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "catalogs", "101MSDCF-61e11b7294")


def mixed_face(groups, rows):
    """组里同时有"有人脸"和"没人脸"的，算一次错配。"""
    n = 0
    for g in groups:
        if len(g["members"]) < 2:
            continue
        fc = [(rows[m].get("face_count") or 0) for m in g["members"]]
        if min(fc) == 0 and max(fc) >= 2:
            n += 1
    return n


def report(name, groups, rows):
    multi = [g for g in groups if len(g["members"]) > 1]
    sizes = sorted((len(g["members"]) for g in multi), reverse=True)
    covered = sum(sizes)
    pair_same = None
    for g in groups:
        ids = {rows[m]["id"] for m in g["members"]}
        if 6 in ids or 7 in ids:
            if pair_same is None:
                pair_same = 6 in ids and 7 in ids
            elif pair_same != (6 in ids and 7 in ids):
                pair_same = False
    print("%-8s 多张组 %3d | 进组 %4d (%2.0f%%) | 最大的组 %-18s | 有人/没人混组 %2d | 争议对同组 %s"
          % (name, len(multi), covered, 100.0 * covered / max(1, len(rows)),
             str(sizes[:5]), mixed_face(groups, rows),
             "是" if pair_same else "否"))


def main():
    store = Store(CAT)
    rows = store.load_rows()
    ids, mat = store.load_vectors(config.EMBED_MODEL)
    vec_of = {pid: mat[i] for i, pid in enumerate(ids)}
    print("照片 %d，有向量 %d，余弦阈值 %.2f，窗口 %.0f 秒，每组上限 %d"
          % (len(rows), len(vec_of), config.GROUP_COSINE,
             config.GROUP_WINDOW_SEC, config.GROUP_MAX))
    print()

    # 现状（库里已经写好的分组）
    cur = defaultdict(list)
    for r in rows:
        if r.get("group_id"):
            cur[r["group_id"]].append(r)
    print("库里现有分组：多张组 %d，最大 %d 张"
          % (len([g for g in cur.values() if len(g) > 1]),
             max((len(g) for g in cur.values()), default=0)))
    print()

    old = group.build_groups(rows)
    report("pHash", old, rows)

    if vec_of:
        new = group.build_groups_vec(rows, vec_of)
        report("向量", new, rows)
        # 余弦分布，给阈值一个交代
        import numpy as np
        pos = {pid: i for i, pid in enumerate(ids)}
        same, diff = [], []
        for g in new:
            ms = g["members"]
            for a in range(len(ms)):
                for b in range(a + 1, len(ms)):
                    same.append(float(mat[pos[rows[ms[a]]["id"]]] @ mat[pos[rows[ms[b]]["id"]]]))
        print("\n组内余弦：最低 %.3f  均值 %.3f  张数中位 %d"
              % (min(same) if same else 0, sum(same) / max(1, len(same)), len(same)))


if __name__ == "__main__":
    main()
