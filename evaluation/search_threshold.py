"""搜索要输出多少张？先量一下分数分布再决定阈值。

"这个词没有对应的照片"和"这个词有 300 张"必须给出不同的结果，否则搜
"海边"会返回 60 张雪山——看着像功能坏了。这里量的是：命中词和不命中词的
分布差多少，以及一个自适应阈值能不能把它们分开。

    python evaluation/search_threshold.py
"""
import json
import os
import sys

import numpy as np

ROOT = r"E:\ai project\guopian"
CACHE = os.path.join(ROOT, ".cache")
sys.path.insert(0, ROOT)

from guopian import tags  # noqa: E402


def main():
    pv = np.load(os.path.join(CACHE, "photo_vecs_int8.npy")).astype(np.float32)
    tv = tags.vectors()                      # fp16 on disk -> float32 here
    names = tags.names()

    print("%-8s %6s %6s %6s %6s %6s %6s" % ("", "max", "p1", "mean", "std", ">0.25", ">0.30"))
    present = ["湖泊", "人像", "雪山", "经幡", "寺庙", "夜景"]
    absent = ["海边", "食物", "猫", "沙漠", "地铁", "蛋糕"]
    for label, words in (("命中", present), ("不命中", absent)):
        print("--", label)
        for w in words:
            k = names.index(w)
            s = pv @ tv[k]
            print("  %-6s %6.3f %6.3f %6.3f %6.3f %6d %6d"
                  % (w, s.max(), np.percentile(s, 99), s.mean(), s.std(),
                     int((s > 0.25).sum()), int((s > 0.30).sum())))

    print("\n自适应阈值（mean + k*std）能通过多少张：")
    for w in ("湖泊", "人像", "雪山", "海边", "食物", "猫"):
        k = names.index(w)
        s = pv @ tv[k]
        for mult in (2.0, 3.0):
            thr = s.mean() + mult * s.std()
            print("  %-6s k=%.0f thr=%.3f -> %4d 张" % (w, mult, thr, int((s > thr).sum())))


if __name__ == "__main__":
    main()
