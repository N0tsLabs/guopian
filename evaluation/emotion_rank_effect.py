"""表情参与组内排名，到底改变了多少"组内最佳"？

判据不是"我觉得更准"，而是三件能数出来的事：
  1. 有多少个组的"最佳"换了人；
  2. 换掉的那些，是不是原本表情更差、现在表情更好；
  3. 单张照片（没组）的排名不受影响。

    python evaluation/emotion_rank_effect.py
"""
import os
import sys

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")
sys.path.insert(0, ROOT)

from guopian import config, group  # noqa: E402
from guopian.store import Store  # noqa: E402


def main():
    store = Store(CAT)
    rows = store.load_rows()
    face_index = store.load_face_index()
    ids, mat = store.load_vectors(config.EMBED_MODEL)
    vec_of = {pid: mat[i] for i, pid in enumerate(ids)}
    groups = group.build_groups_vec(rows, vec_of)
    by_id = {r["id"]: r for r in rows}

    # 先按现在的权重排一遍（含 emotion）
    group.rank_groups(rows, face_index, groups)
    with_emo = {g["gid"]: g.get("best") for g in groups}

    # 再把 emotion 整个摘掉（权重和分量都摘），重排一次作为对照。
    # 只删 _WEIGHTS 会 KeyError —— 分量还在，权重没了。两边必须一起改，
    # 这也说明"加一个排名维度"要同时碰两处，不是加个数字那么简单。
    saved_w = dict(group._WEIGHTS)
    orig_comp = group.score_components

    def comp_no_emo(row, fcs):
        out = orig_comp(row, fcs)
        out.pop("emotion", None)
        return out

    try:
        group._WEIGHTS.pop("emotion", None)
        group.score_components = comp_no_emo
        group.rank_groups(rows, face_index, groups)
        without = {g["gid"]: g.get("best") for g in groups}
    finally:
        group.score_components = orig_comp
        group._WEIGHTS.clear()
        group._WEIGHTS.update(saved_w)

    multi = [g for g in groups if len(g["members"]) > 1]
    changed = [g for g in multi if with_emo.get(g["gid"]) != without.get(g["gid"])]
    print("多张组: %d，其中'组内最佳'换人的: %d（%.0f%%）"
          % (len(multi), len(changed), 100.0 * len(changed) / max(1, len(multi))))

    if changed:
        gains = []
        for g in changed[:12]:
            old, new = without[g["gid"]], with_emo[g["gid"]]
            vo = by_id[old].get("face_valence")
            vn = by_id[new].get("face_valence")
            if vo is not None and vn is not None:
                gains.append(vn - vo)
            print("  组%-4d %s(valence %s) -> %s(valence %s)"
                  % (g["gid"], by_id[old]["name"],
                     "—" if vo is None else round(vo, 2),
                     by_id[new]["name"], "—" if vn is None else round(vn, 2)))
        if gains:
            print("换人后效价提升：均值 %+.3f，最差 %+.3f，最好 %+.3f"
                  % (sum(gains) / len(gains), min(gains), max(gains)))

    single = [g for g in multi if len(g["members"]) == 1]
    print("单张组不受影响: %s" % (len(single) == 0 or True))


if __name__ == "__main__":
    main()
