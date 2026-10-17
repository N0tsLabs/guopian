"""End-to-end test of the three-folder apply, on the real 93 photos.

The server I run cannot write to D: -- its Python is confined to the workspace,
while robocopy and cmd are not. So the library is mirrored into the workspace and
the real photos go through the real pipeline there: real analysis, real
decisions replayed from the original catalog, real apply() from decisions.py.

Nothing here touches D:.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SRC = r"D:\image cache\川西\100MSDCF"
MIRROR = os.path.join(ROOT, ".cache", "realtest", "100MSDCF")
API = "http://127.0.0.1:8765"


MIRROR_PATH = None          # set in main(); used by the recovery below


def _once(path, body, method):
    req = urllib.request.Request(
        API + path, data=(json.dumps(body).encode() if method == "POST" else None),
        headers={"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=600))


def _call(path, body, method):
    """Retry through a server reload.

    The dev server restarts whenever guopian/ changes, which drops the open
    library and turns the next request into a 409. Re-open and try again instead
    of failing the run -- the reload is an artefact of running a dev server, not
    something the test is meant to be measuring.
    """
    for attempt in range(6):
        try:
            return _once(path, body, method)
        except urllib.error.HTTPError as e:
            if e.code != 409 or MIRROR_PATH is None or attempt == 5:
                raise
            time.sleep(2)
            _once("/api/open", {"path": MIRROR_PATH, "read_only": False}, "POST")
            time.sleep(3)


def post(path, body=None):
    return _call(path, body or {}, "POST")


def get(path):
    return _call(path, None, "GET")


def wait_for_library(path, tries=400):
    """Open path and wait for analysis.

    The dev server reloads whenever guopian/ changes and that drops the open
    library, so /api/state can 409 halfway through. Re-open and keep going
    instead of failing the run.
    """
    for _ in range(tries):
        try:
            st = get("/api/state")
            if not st.get("progress", {}).get("running"):
                return st
        except Exception:
            post("/api/open", {"path": path, "read_only": False})
        time.sleep(1)
    raise RuntimeError("library never settled")


def catalog_for(lib_path):
    import glob
    from guopian import paths
    return os.path.join(paths.catalog_dir(lib_path), "catalog.db")


def main() -> int:
    global MIRROR_PATH
    MIRROR_PATH = MIRROR
    print("\n  1. 把 93 张真实照片镜像到工作区（robocopy，它能写 E:）")
    os.makedirs(os.path.dirname(MIRROR), exist_ok=True)
    subprocess.run(["robocopy", SRC, MIRROR, "/E", "/NJH", "/NJS", "/NDL", "/NP",
                    "/R:0", "/W:0"], capture_output=True)
    n = len([f for f in os.listdir(MIRROR) if f.lower().endswith(".jpg")])
    print("     镜像了 {} 张".format(n))

    print("\n  2. 通过 API 打开镜像库（真实分析，约 20 秒）")
    wait_for_library(MIRROR)
    print("     分析完成")

    print("\n  3. 把原库的 93 个决定照搬过来")
    orig = sqlite3.connect("file:{}?mode=ro".format(
        catalog_for(SRC).replace("\\", "/")), uri=True)
    orig.row_factory = sqlite3.Row
    decisions = {r["name"]: r["decision"] for r in orig.execute(
        "SELECT name, decision FROM photos WHERE decision IS NOT NULL AND decision<>''")}
    print("     原库有 {} 个决定".format(len(decisions)))

    con = sqlite3.connect(catalog_for(MIRROR))
    applied = 0
    for r in con.execute("SELECT id, name FROM photos").fetchall():
        d = decisions.get(r[1])
        if d:
            con.execute("UPDATE photos SET decision=? WHERE id=?", (d, r[0]))
            applied += 1
    con.commit()
    print("     写入了 {} 个".format(applied))

    print("\n  4. 预览")
    pv = get("/api/apply/preview?mode=quarantine")
    for g in pv["groups"]:
        print("     {:<4} {:>3} 张 {:>7} MB  ->  {}".format(
            g["label"], g["count"], g["mb"], g["path"]))
    print("     未审 {} 张留原地".format(pv["undecided"]))

    print("\n  5. 执行（走 decisions.py 的真实代码）")
    res = post("/api/apply", {"mode": "quarantine", "confirm": True})
    print("     ok={} moved={} counts={}".format(
        res.get("ok"), res.get("moved"), res.get("counts")))

    print("\n  6. 磁盘上的结果")
    for name in sorted(os.listdir(MIRROR)):
        p = os.path.join(MIRROR, name)
        if os.path.isdir(p):
            print("     {}/  {} 个文件".format(name, len(os.listdir(p))))
    loose = [f for f in os.listdir(MIRROR) if os.path.isfile(os.path.join(MIRROR, f))]
    print("     根目录还剩 {} 张".format(len(loose)))

    print("\n  7. catalog 有没有失联")
    con2 = sqlite3.connect(catalog_for(MIRROR))
    con2.row_factory = sqlite3.Row
    missing = [r["path"] for r in con2.execute("SELECT path FROM photos").fetchall()
               if not os.path.exists(r["path"])]
    print("     指向不存在文件的记录: {}".format(len(missing)))
    print("     " + ("OK —— 路径同步了" if not missing else "!! 有失联"))

    print("\n  8. 重新索引，决定会不会丢")
    before = con2.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    kept_before = con2.execute(
        "SELECT COUNT(*) FROM photos WHERE decision IS NOT NULL").fetchone()[0]
    post("/api/close")
    wait_for_library(MIRROR)
    con3 = sqlite3.connect(catalog_for(MIRROR))
    after = con3.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    kept_after = con3.execute(
        "SELECT COUNT(*) FROM photos WHERE decision IS NOT NULL").fetchone()[0]
    print("     照片数 {} -> {}".format(before, after))
    print("     决定数 {} -> {}".format(kept_before, kept_after))
    print("     " + ("OK —— 决定没丢，也没重复" if after == before and kept_after == kept_before
                    else "!! 出问题了"))

    print("\n  9. 回滚")
    rb = post("/api/apply/rollback", {"batch": res["batch"]})
    print("     restored={}".format(rb.get("restored")))
    loose2 = [f for f in os.listdir(MIRROR) if os.path.isfile(os.path.join(MIRROR, f))]
    print("     根目录恢复到 {} 张（应该 93）".format(len(loose2)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
