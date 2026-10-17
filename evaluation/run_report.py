"""Run the whole pipeline over a folder and print what it found.

    python evaluation/run_report.py <folder>

Useful as a smoke test and as the starting point for a real benchmark.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MPLCONFIGDIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache", "matplotlib"))

from guopian import config, faces, pipeline  # noqa: E402


def main() -> int:
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "testset")
    folder = os.path.abspath(folder)

    ok, msg = faces.available()
    print("人脸检测: {}".format("可用" if ok else "不可用 ({})".format(msg)))

    lib = pipeline.Library(folder, workers=4)
    files = lib.scan_files()
    print("发现 {} 个图片文件\n".format(len(files)))
    lib.store.upsert_scanned(files)

    t0 = time.time()
    n = lib.analyze_pending()
    dt = time.time() - t0
    print("分析 {} 张，用时 {:.2f}s  ({:.0f} ms/张)\n".format(
        n, dt, (dt / n * 1000) if n else 0))

    res = lib.recompute()
    print("分组: {} 组\n".format(res["groups"]))

    rows = lib.store.load_rows()
    print("{:<30} {:>7} {:>6} {:>6} {:>5} {:>4} {:<28} {}".format(
        "文件", "清晰度", "高光%", "暗部%", "噪点", "脸", "问题", "建议"))
    print("-" * 132)
    for r in rows:
        iss = lib.store.conn.execute(
            "SELECT label_zh, severity FROM issues WHERE photo_id=? ORDER BY CASE severity "
            "WHEN 'fatal' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 "
            "ELSE 4 END", (r["id"],)).fetchall()
        tags = " ".join("[{}]{}".format(i["severity"][:1], i["label_zh"]) for i in iss[:4])
        if len(iss) > 4:
            tags += " +{}".format(len(iss) - 4)
        print("{:<30} {:>7.1f} {:>6.1f} {:>6.1f} {:>5.1f} {:>4} {:<28} {}".format(
            (r["name"] or "")[:30],
            r["lap_var_mp"] or 0, r["pct_high"] or 0, r["pct_low"] or 0,
            r["noise"] or 0, r["face_count"] or 0,
            tags[:28], r["suggest"] or "-"))

    print("\n--- 相似分组 ---")
    for g in lib.store.conn.execute(
            "SELECT id, size, best_photo_id FROM groups WHERE size>1 ORDER BY size DESC").fetchall():
        members = lib.store.conn.execute(
            "SELECT name, group_rank, group_score FROM photos WHERE group_id=? ORDER BY group_rank",
            (g["id"],)).fetchall()
        print("组 {} ({} 张):".format(g["id"], g["size"]))
        for m in members:
            print("    #{rank} {score:<7} {name}".format(
                rank=m["group_rank"], score=round(m["group_score"] or 0, 4), name=m["name"]))

    cal = lib.store.get_meta("calibration") or {}
    print("\n--- 相对阈值（按设备聚类，这是关键）---")
    for k, v in cal.items():
        print("  {:<28} n={:<4} 软={:.1f} 中位={:.1f} 噪点={:.2f}".format(
            k[:28], v.get("n", 0), v.get("soft", 0), v.get("sharp_median", 0), v.get("noisy", 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
