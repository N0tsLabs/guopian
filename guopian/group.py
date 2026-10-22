"""Burst / near-duplicate grouping and *relative* ranking inside a group.

This is the part that replaces "absolute score + global threshold" with
"compare only against photos of the same moment". Same camera, same lens,
same light, same subject -> every variable that breaks an absolute threshold
cancels out. See docs/05 §2.2.
"""

from __future__ import annotations

from . import config, phash


class _DSU:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _rank_normalise(values: list[float | None]) -> list[float | None]:
    """Map values to 0..1 by rank."""
    idx = [i for i, v in enumerate(values) if v is not None]
    n = len(idx)
    out: list[float | None] = [None] * len(values)
    if n == 0:
        return out
    if n == 1:
        out[idx[0]] = 0.5
        return out
    order = sorted(idx, key=lambda i: values[i])
    for pos, i in enumerate(order):
        out[i] = pos / float(n - 1)
    return out


# ------------------------------------------------------------------ membership

def _aspect(row: dict) -> float:
    w, h = row.get("width") or 0, row.get("height") or 0
    return (w / h) if w and h else 0.0


def _comparable(a: dict, b: dict) -> bool:
    """A real burst shares orientation. Big aspect mismatch => hash collision.

    This matters because heavily blurred / crushed frames lose all detail and
    their pHash collapses towards a constant, which otherwise merges unrelated
    photos into one giant group.
    """
    aa, ab = _aspect(a), _aspect(b)
    if aa and ab and abs(aa - ab) / max(aa, ab) > config.GROUP_ASPECT_TOL:
        return False
    return True


def _same_subject(a: dict, b: dict) -> bool:
    """一张有两个人、另一张一个人都没有 —— 不是可以互相替代的两帧。

    这是用户实际报的那类错：背景一模一样（同一个湖、同一个机位），任何
    "整张图像不像"的度量都认为它们接近；但一张是他俩的合影、一张是空景，
    在"这两张里挑一张留下"这个用法下它们根本不是同一个瞬间。

    只挡最明确的情况（≥2 人对 0 人）。一张有一人、一张没人，可能是同一个人
    走进画面，那仍然是同一个瞬间，不该拆。
    """
    fa = a.get("face_count") or 0
    fb = b.get("face_count") or 0
    return not ((fa >= 2 and fb == 0) or (fb >= 2 and fa == 0))


def build_groups(rows: list[dict]) -> list[dict]:
    """`rows` must be sorted by taken_ts. Returns membership + duplicate marks."""
    n = len(rows)
    if n == 0:
        return []
    dsu = _DSU(n)

    # Bursts are consecutive in time, so we only compare a local window.
    # O(n*k) instead of O(n^2), and it matches how people actually shoot.
    for i in range(n):
        ti = rows[i].get("taken_ts") or 0.0
        hi = rows[i].get("phash")
        for j in range(i + 1, min(n, i + 40)):
            tj = rows[j].get("taken_ts") or 0.0
            if ti and tj and (tj - ti) > config.BURST_WINDOW_SEC:
                break
            if not _comparable(rows[i], rows[j]):
                continue
            if not _same_subject(rows[i], rows[j]):
                continue
            if phash.hamming(hi, rows[j].get("phash")) <= config.PHASH_SIMILAR:
                dsu.union(i, j)

    buckets: dict[int, list[int]] = {}
    for i in range(n):
        buckets.setdefault(dsu.find(i), []).append(i)

    groups: list[dict] = []
    for gid, members in enumerate(buckets.values(), start=1):
        sub = [rows[i] for i in members]

        # Exact duplicates: same image imported/stored twice. That means
        # identical pixel dimensions plus a near-identical hash -- a plain
        # hash match alone also fires on two different frames of one scene.
        dup_of: dict[int, str] = {}
        order = sorted(range(len(sub)), key=lambda k: -(sub[k].get("size") or 0))
        for a_pos, a in enumerate(order):
            if members[a] in dup_of:
                continue
            for b in order[:a_pos]:
                if (sub[a].get("width") != sub[b].get("width") or
                        sub[a].get("height") != sub[b].get("height")):
                    continue
                if phash.hamming(sub[a].get("phash"), sub[b].get("phash")) <= config.PHASH_DUP:
                    dup_of[members[a]] = sub[b].get("name") or ""
                    break

        groups.append({
            "gid": gid,
            "members": members,
            "exact_dup_of": dup_of,
            "scores": {},
            "rank": {m: 1 for m in members},
            "best": None,
            "best_score": 0.0,
        })
    return groups


# ------------------------------------------------------------------ scoring

def _eyes_and_gaze(fcs: list[dict]) -> tuple[float | None, float | None]:
    """Eyes-open score and worst gaze offset, over the faces we may judge."""
    judged = [f for f in fcs if (f.get("gates") or {}).get("judge_eyes")]
    if not judged:
        return None, None
    worst_blink = max(max(f.get("blink_l") or 0.0, f.get("blink_r") or 0.0) for f in judged)
    if worst_blink >= config.EYE_BLINK_CLOSED:
        eyes = 0.0
    elif worst_blink >= config.EYE_BLINK_MAYBE:
        eyes = 0.5
    else:
        eyes = 1.0
    gaze = max((f.get("gaze_away") or 0.0) for f in judged)
    return eyes, gaze


def score_components(row: dict, fcs: list[dict]) -> dict[str, float]:
    """Only the components that are actually computable for this photo.

    Photos without faces simply do not get eyes/gaze/smile components, and the
    weights are renormalised. Otherwise landscape bursts would be punished for
    signals that cannot exist.
    """
    comp: dict[str, float] = {}

    lv = row.get("lap_var_mp")
    if lv is not None:
        comp["sharp"] = float(lv)

    ph = row.get("pct_high") or 0.0
    pl = row.get("pct_low") or 0.0
    comp["exposure"] = 1.0 - min(1.0, ph / 10.0) * 0.5 - min(1.0, pl / 20.0) * 0.5

    # Noise inflates Laplacian variance, so a grainy frame can look "sharpest
    # in the burst". Score noise separately so it cannot win that way.
    ns = row.get("noise")
    if ns is not None:
        comp["clean"] = 1.0 - min(1.0, ns / 12.0)

    eyes, gaze = _eyes_and_gaze(fcs)
    if eyes is not None:
        comp["eyes"] = eyes
    if gaze is not None:
        comp["gaze"] = 1.0 - min(1.0, gaze / 1.5)

    ratios = [f["face_sharp_ratio"] for f in fcs if f.get("face_sharp_ratio") is not None]
    if ratios:
        comp["face_sharp"] = max(ratios)
    if fcs:
        comp["smile"] = max((f.get("smile") or 0.0) for f in fcs)
    return comp


_WEIGHTS = {
    "sharp": 0.30,
    "exposure": 0.20,
    "eyes": 0.25,
    "clean": 0.08,
    "face_sharp": 0.10,
    "gaze": 0.08,
    "smile": 0.07,
}


def _weighted(comp: dict[str, float]) -> float:
    total_w = sum(_WEIGHTS[k] for k in comp)
    if total_w <= 0:
        return 0.0
    acc = 0.0
    for k, v in comp.items():
        if k == "sharp":       # unbounded -> saturating curve
            v = v / (v + 40.0)
        elif k == "face_sharp":
            v = v / (v + 1.0)
        acc += _WEIGHTS[k] * max(0.0, min(1.0, v))
    return acc / total_w


def rank_groups(rows: list[dict], face_index: dict[int, list[dict]],
                groups: list[dict]) -> None:
    """Fill in per-photo scores, in-group ranks and the group's best shot."""
    by_id = {r["id"]: r for r in rows}
    for g in groups:
        members = g["members"]
        comps = [score_components(by_id.get(m, {}), face_index.get(m, [])) for m in members]

        # Inside one burst the absolute sharpness number is meaningless on its
        # own -- what matters is which frame is sharpest. Replace it with the
        # in-group rank.
        if len(members) >= 3:
            for key in ("sharp", "face_sharp"):
                vals = [c.get(key) for c in comps]
                if sum(v is not None for v in vals) >= 2:
                    ranks = _rank_normalise(vals)
                    for k in range(len(comps)):
                        if ranks[k] is not None:
                            comps[k][key] = ranks[k]

        scores = [_weighted(c) for c in comps]
        order = sorted(range(len(members)), key=lambda k: -scores[k])
        best_score = scores[order[0]] if order else 0.0
        for pos, k in enumerate(order):
            g["scores"][members[k]] = round(scores[k], 4)
            g["rank"][members[k]] = 1 if abs(scores[k] - best_score) < 1e-9 else pos + 1
        if order:
            g["best"] = members[order[0]]
            g["best_score"] = round(best_score, 4)
