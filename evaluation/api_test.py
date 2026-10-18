"""Exercise the running Guopian HTTP API the way the browser does (UTF-8 JSON)."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8850"
FOLDER = os.environ.get("GUOPIAN_TEST_FOLDER", r"D:\photos\shoot")
# 用一个真实存在、并且已经审过一批照片的库来跑。
# 仓库里不写死任何人的路径。
PARENT = r"D:\photos"


def call(path, method="GET", body=None, timeout=120, raw=False):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            blob = r.read()
            if raw:
                return r.status, blob
            return r.status, (json.loads(blob.decode("utf-8")) if blob else None)
    except urllib.error.HTTPError as e:
        blob = e.read()
        if raw:
            return e.code, blob
        try:
            return e.code, json.loads(blob.decode("utf-8"))
        except Exception:
            return e.code, blob.decode("utf-8", "ignore")


def show(label, ok, extra=""):
    print("  [{}] {:<34} {}".format("OK  " if ok else "FAIL", label, extra))
    return 0 if ok else 1


fails = 0

print("== 1. 首页状态（未打开库）==")
st, home = call("/api/home")
fails += show("GET /api/home", st == 200, "current={} recent={}".format(
    home.get("current") is not None, len(home.get("recent") or [])))

print("\n== 2. 盘符 ==")
st, roots = call("/api/fs/roots")
fails += show("GET /api/fs/roots", st == 200 and roots.get("roots"),
              ", ".join(r["name"] for r in (roots.get("roots") or [])[:8]))

print("\n== 3. 应用内目录浏览（中文路径）==")
st, d = call("/api/fs/list?path=" + urllib.parse.quote(PARENT))
fails += show("GET /api/fs/list 旅行照片", st == 200 and d.get("path") == PARENT,
              "直属 {} 张".format(d.get("photos")))
for sub in (d.get("dirs") or []):
    print("        📁 {:<12} {} 张".format(sub["name"], sub["photos"]))
fails += show("目录计数正确", any(s["name"] == "100MSDCF" and s["photos"] == 93
                                for s in (d.get("dirs") or [])),
              "100MSDCF 应为 93 张")

print("\n== 4. 打开图书馆（中文路径 + 只读）==")
st, o = call("/api/open", "POST", {"path": FOLDER, "read_only": True})
fails += show("POST /api/open", st == 200 and o.get("ok"),
              "root={} read_only={}".format(o.get("root"), o.get("read_only")))

print("\n== 5. 等分析完成 ==")
last = None
for _ in range(90):
    time.sleep(1)
    st, s = call("/api/state", timeout=10)
    if st == 200 and s.get("progress", {}).get("phase") == "done":
        last = s
        break
    last = s if st == 200 else last
if last:
    p = last["progress"]
    fails += show("分析完成", p.get("phase") == "done",
                  "{} 张 · {}s · {} ms/张".format(
                      last["counts"]["analyzed"], p.get("elapsed"),
                      round(p.get("elapsed", 0) * 1000 / max(1, last["counts"]["analyzed"]))))
    print("        问题分类: " + (", ".join(
        "{}×{}".format(i["label_zh"], i["n"]) for i in last["issue_summary"][:6]) or "无"))

print("\n== 6. 队列 ==")
# filter=all, not pending. This used to ask for the pending list and assert it
# was non-empty, which quietly assumed the library still had undecided photos --
# so the whole suite started failing the moment a library was fully triaged, for
# a reason that has nothing to do with the code under test. `all` is never empty
# for a library that has photos.
st, q = call("/api/queue?filter=all&sort=time")
fails += show("GET /api/queue", st == 200 and q.get("total", 0) > 0,
              "{} 张，首张 {}".format(q.get("total"), q["items"][0]["name"] if q.get("items") else "-"))
st, qp = call("/api/queue?filter=pending&sort=time")
print("        其中待审 {} 张".format(qp.get("total")))
first = q["items"][0] if q.get("items") else None
if first:
    print("        建议={} 问题={} 相似组={}/{}".format(
        first.get("suggest"), len(first.get("issues") or []),
        first.get("group_rank"), first.get("group_size")))

print("\n== 7. 图片服务 ==")
for size in ("small", "card"):
    st, blob = call("/img/{}/{}".format(first["id"], size), raw=True)
    fails += show("GET /img/{}/{}".format(first["id"], size),
                  st == 200 and len(blob) > 1000, "{} bytes".format(len(blob)))

print("\n== 8. 人脸 + 详情 ==")
st, ph = call("/api/photo/{}".format(first["id"]))
fails += show("GET /api/photo", st == 200,
              "faces={} issues={}".format(len(ph.get("faces") or []), len(ph.get("issues") or [])))

print("\n== 9. 决策 / 撤销 ==")
st, r = call("/api/decide", "POST", {"id": first["id"], "action": "keep"})
fails += show("POST /api/decide", st == 200 and r.get("ok"), str(r.get("action")))
st, r = call("/api/undo", "POST", {})
fails += show("POST /api/undo", st == 200 and r.get("ok"), str(r.get("result")))

print("\n== 10. 只读保护 ==")
st, r = call("/api/apply", "POST", {"mode": "quarantine", "confirm": True})
fails += show("只读时拒绝移动文件", r.get("ok") is False, str(r.get("error")))

print("\n== 11. 回首页（关闭库）==")
st, r = call("/api/close", "POST", {})
fails += show("POST /api/close", st == 200 and r.get("ok"))
st, home2 = call("/api/home")
fails += show("回首页后 current 为空", home2.get("current") is None,
              "recent={} 条".format(len(home2.get("recent") or [])))
for item in (home2.get("recent") or [])[:4]:
    print("        {}  {}  ({}/{} 已决定)".format(
        item["name"], item["path"], item.get("decided", 0), item.get("total", 0)))

print("\n===== {} =====".format("全部通过" if fails == 0 else "{} 项失败".format(fails)))
sys.exit(0 if fails == 0 else 1)
