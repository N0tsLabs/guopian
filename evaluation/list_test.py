"""Verify the list-first behaviour: every filter returns what the panel needs."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


def call(path, method="GET", body=None, timeout=90):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, None


ok = True
for _ in range(60):
    st, _ = call("/api/health", timeout=5)
    if st == 200:
        break
    time.sleep(1)

for _ in range(60):
    st, s = call("/api/state", timeout=10)
    if st == 200 and s.get("progress", {}).get("phase") == "done":
        break
    time.sleep(1)

st, s = call("/api/state")
if st != 200:
    print("  库还没打开 —— 先在界面上选一个文件夹")
    sys.exit(0)

print("库       : {}".format(s["root"]))
print("只读     : {}".format(s["read_only"]))
d = s["counts"]["decisions"]
print("总数     : {}   要 {}  不要 {}  收藏 {}  未审 {}".format(
    s["counts"]["total"], d.get("keep", 0), d.get("reject", 0),
    d.get("mark", 0), d.get("undecided", 0)))

print("\n=== 左侧列表用到的每个筛选 ===")
for flt, label in [("all", "全部（默认）"), ("pending", "未审"),
                   ("keep", "要"), ("reject", "不要"), ("mark", "收藏")]:
    st, q = call("/api/queue?filter={}".format(flt))
    n_decided = sum(1 for c in (q or {}).get("items", []) if c.get("decision"))
    print("  {:<16} {:>4} 张   其中已决策 {:>3} 张".format(
        label, (q or {}).get("total", -1), n_decided))
    if flt == "all":
        ok = ok and (q or {}).get("total", 0) > 0
        ok = ok and n_decided > 0

print("\n=== 打开项目时的落点（模拟前端的 pickStartIndex）===")
st, q = call("/api/queue?filter=all")
items = (q or {}).get("items", [])
first_open = next((i for i, c in enumerate(items) if not c.get("decision")), None)
print("  '全部' 里第一张未审的序号: {}".format(
    first_open + 1 if first_open is not None else "无（都审完了）"))

print("\n=== 列表项的数据够不够画 ===")
if items:
    c = items[0]
    need = ["id", "name", "decision", "suggest", "group_rank", "group_size", "issues"]
    missing = [k for k in need if k not in c]
    print("  第一项字段: {} {}".format(
        "齐全" if not missing else "缺 " + ",".join(missing),
        "| 名字={} 决策={} 建议={} 问题={}条".format(
            c["name"], c.get("decision") or "无", c.get("suggest"), len(c.get("issues") or []))))
    ok = ok and not missing

print("\n===== {} =====".format("列表行为正确" if ok else "有问题"))
sys.exit(0 if ok else 1)
