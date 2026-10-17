"""Does a photo survive being filed into a folder?

The three-folder scheme moves files, and a moved file has a new path -- while
`photos.path` is the UNIQUE key the whole catalog hangs off. If the catalog is
not updated in the same breath, the analysis, the faces, the issues and the
decision itself all point at a file that is no longer there, and the next index
quietly inserts them as brand-new photos.

Run entirely on a synthetic library under .cache. It never touches a real one.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from guopian import config, decisions, paths  # noqa: E402
from guopian.session import Session  # noqa: E402


def make_photos(folder: str, n: int = 12) -> None:
    """Small synthetic JPEGs. Real ones are not needed to test file bookkeeping."""
    from PIL import Image

    os.makedirs(folder, exist_ok=True)
    rng = np.random.default_rng(7)
    for i in range(n):
        a = (rng.random((240, 320, 3)) * 255).astype(np.uint8)
        Image.fromarray(a).save(os.path.join(folder, "IMG_{:03d}.jpg".format(i)),
                                quality=70)


def main() -> int:
    work = os.path.join(ROOT, ".cache", "foldertest")
    shutil.rmtree(work, ignore_errors=True)
    libdir = os.path.join(work, "shoot")
    os.makedirs(libdir, exist_ok=True)
    make_photos(libdir, 12)

    sess = Session(workers=1)
    lib = sess.open(libdir, work_dir=os.path.join(work, "catalog"))
    # open() starts the scan on a worker thread, so the count is 0 the instant it
    # returns. Wait for it to settle instead of racing it.
    import time
    deadline = time.time() + 120
    last = -1
    while time.time() < deadline:
        n = lib.store.conn.execute("SELECT COUNT(*) n FROM photos").fetchone()["n"]
        if n and n == last:
            break
        last = n
        time.sleep(0.4)
    print("  索引 {} 张".format(last))

    con = lib.store.conn
    ids = [r["id"] for r in con.execute("SELECT id FROM photos ORDER BY id")]
    # 4 keep, 3 reject, 2 mark, 3 left undecided
    for pid, d in zip(ids[:4], ["keep"] * 4):
        con.execute("UPDATE photos SET decision=? WHERE id=?", (d, pid))
    for pid, d in zip(ids[4:7], ["reject"] * 3):
        con.execute("UPDATE photos SET decision=? WHERE id=?", (d, pid))
    for pid, d in zip(ids[7:9], ["mark"] * 2):
        con.execute("UPDATE photos SET decision=? WHERE id=?", (d, pid))
    con.commit()

    pv = decisions.preview(lib.store)
    print("\n  归档前预览:")
    for g in pv["groups"]:
        print("    {:<6} {:<10} {} 张  {:.1f} MB".format(
            g["label"], g["dir"], g["count"], g["mb"]))
    print("    未审 {} 张（留在原地）".format(pv["undecided"]))

    r = decisions.apply(lib.store)
    print("\n  执行: ok={} moved={} counts={}".format(r["ok"], r["moved"], r.get("counts")))

    print("\n  磁盘上的结果:")
    for name in sorted(os.listdir(libdir)):
        p = os.path.join(libdir, name)
        if os.path.isdir(p):
            print("    {}/  {} 个文件".format(name, len(os.listdir(p))))
    loose = [f for f in os.listdir(libdir) if os.path.isfile(os.path.join(libdir, f))]
    print("    根目录下还有 {} 张（应该是 3 张未审的）".format(len(loose)))

    # THE question: does the catalog still know these photos?
    print("\n  catalog 里路径更新了吗:")
    moved_rows = con.execute(
        "SELECT name, rel_path, decision FROM photos WHERE decision IS NOT NULL "
        "ORDER BY rel_path LIMIT 4").fetchall()
    for r2 in moved_rows:
        print("    {:<14} {:<16} {}".format(r2["name"], r2["rel_path"], r2["decision"]))

    missing = [r2["path"] for r2 in con.execute(
        "SELECT path FROM photos WHERE decision IS NOT NULL").fetchall()
        if not os.path.exists(r2["path"])]
    print("\n  指向不存在的文件的记录: {}".format(len(missing)))
    print("  " + ("OK —— 路径同步了" if not missing else "!! 有 {} 条失联".format(len(missing))))

    # re-index: an existing library must not duplicate anything
    print("\n  重新索引（模拟下次打开）:")
    before = con.execute("SELECT COUNT(*) n FROM photos").fetchone()["n"]
    lib2 = sess.open(libdir, work_dir=os.path.join(work, "catalog"))
    after = lib2.store.conn.execute("SELECT COUNT(*) n FROM photos").fetchone()["n"]
    print("    照片数 {} -> {}".format(before, after))
    lost = lib2.store.conn.execute(
        "SELECT COUNT(*) n FROM photos WHERE decision IS NOT NULL").fetchone()["n"]
    print("    保住了决定的有 {} 张（应该是 9）".format(lost))
    print("  " + ("OK —— 决定没丢" if lost == 9 and after == before
                  else "!! 决定丢了或者照片重复了"))

    # and back
    rb = decisions.rollback(lib.store, r["batch"])
    print("\n  回滚: restored={}".format(rb.get("restored")))
    loose2 = [f for f in os.listdir(libdir) if os.path.isfile(os.path.join(libdir, f))]
    print("    根目录下 {} 张（应该恢复到 12）".format(len(loose2)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
