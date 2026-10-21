"""按"词表内最像哪个"来搜，而不是靠一个全局阈值。

量出来一个事实：CLIP 的绝对分数不能跨词比较。命中词的最高分能低到 0.235
（夜景），不命中词的最高分能高到 0.254（地铁）。所以"分数 > 0.25 就算找到"
必然两头出错。

但分类是可靠的：给每张照片在 78 个词里取 argmax，问"这张最像哪个词"。
不命中的词自然没人把它当第一。这个脚本量 argmax 分布，确认它能把
"没有这类照片"和"有 40 张"分开。

    python evaluation/search_argmax.py
"""
import os
import sys

import numpy as np

ROOT = r"E:\ai project\guopian"
CACHE = os.path.join(ROOT, ".cache")
sys.path.insert(0, ROOT)

from guopian import tags  # noqa: E402


def main():
    pv = np.load(os.path.join(CACHE, "photo_vecs_int8.npy")).astype(np.float32)
    tv = tags.vectors()
    names = tags.names()
    sc = pv @ tv.T                     # (N, 78)
    best = sc.argmax(axis=1)

    print("每张照片最像的那个词（argmax）分布：")
    uniq, counts = np.unique(best, return_counts=True)
    order = np.argsort(-counts)
    for i in order[:14]:
        print("  %-6s %4d 张" % (names[uniq[i]], counts[i]))
    covered = len(uniq)
    print("  ...共 %d/%d 个词当过第一名" % (covered, len(names)))

    print("\n命中 / 不命中 两组词分别有多少张以它为第一名：")
    for label, words in (("命中", ["湖泊", "人像", "雪山", "经幡", "寺庙", "夜景", "山峰"]),
                         ("不命中", ["海边", "食物", "猫", "沙漠", "地铁", "蛋糕", "火锅"])):
        print("--", label)
        for w in words:
            k = names.index(w)
            n_arg = int((best == k).sum())
            n_top2 = int((np.argsort(-sc, axis=1)[:, :2] == k).any(axis=1).sum())
            print("  %-6s argmax %3d 张   前二 %3d 张" % (w, n_arg, n_top2))


if __name__ == "__main__":
    main()
