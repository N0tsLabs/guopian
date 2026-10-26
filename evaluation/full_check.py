"""全量自检：把每个接口、每条分类、每次删除都验一遍。

分三块：
  A 接口    每个端点都能通，返回的形状对得上
  B 数据    分类/分组/判定/标定的内部一致性（不是"看起来对"，是能互相验的）
  C 删除    删项目必须把识别数据删干净，而照片一张都不能少

用法：
    python evaluation/full_check.py            # 用当前打开的库
    python evaluation/full_check.py --path ... # 指定库

发现的问题直接列出来，返回码非 0。
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"
ROOT = r"E:\ai project\guopian"
sys.path.insert(0, ROOT)

FAILS: list[str] = []
OKS: list[str] = []


def ok(msg):
    OKS.append(msg)
    print("  ok   " + msg)


def bad(msg):
    FAILS.append(msg)
    print("  FAIL " + msg)


def req(path, body=None, method=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=data, headers=headers,
                               method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def check(cond, msg, detail=""):
    if cond:
        ok(msg)
    else:
        bad("{} {}".format(msg, detail))
    return cond


# --------------------------------------------------------------------- A 接口

def api_surface():
    print("\n[A] 接口")
    st, h = req("/api/health")
    check(st == 200 and h.get("ok") is not False, "/api/health")

    st, home = req("/api/home")
    check(st == 200 and "recent" in home, "/api/home 有 recent")
    check(isinstance(home.get("recent"), list), "/api/home recent 是数组")

    st, s = req("/api/state")
    if st != 200:
        bad("/api/state 打不开（{}）—— 后面全部跳过".format(st))
        return None
    for key in ("root", "slug", "counts", "progress", "boot", "boot_needed",
                "catalog_key", "embed", "labels", "issue_summary", "calibration"):
        check(key in s, "/api/state 有 {}".format(key))
    check(isinstance(s["counts"].get("total"), int), "counts.total 是整数")
    check(bool(s["catalog_key"]), "catalog_key 非空", s["catalog_key"])

    for flt in ("all", "pending", "keep", "reject", "pick", "issues", "faces",
                "groups", "blurry", "eye_closed"):
        st, q = req("/api/queue?filter={}&sort=time".format(flt))
        check(st == 200 and isinstance(q.get("items"), list),
              "/api/queue filter={}".format(flt))
    st, q2 = req("/api/queue?filter=all&sort=group")
    check(st == 200 and isinstance(q2.get("items"), list), "/api/queue sort=group")

    st, g = req("/api/groups")
    check(st == 200 and isinstance(g.get("items"), list), "/api/groups")

    st, pv = req("/api/apply/preview?mode=quarantine")
    check(st == 200, "/api/apply/preview")

    st, ap = req("/api/applies")
    check(st == 200 and isinstance(ap.get("items"), list), "/api/applies")

    st, mo = req("/api/models")
    check(st == 200, "/api/models")

    st, fs = req("/api/fs/list?path=" + urllib.request.quote(ROOT))
    check(st == 200 and isinstance(fs.get("dirs"), list), "/api/fs/list")
    check(fs.get("photos") is None, "fs/list 不再递归数照片（photos=null）")
    st, fc = req("/api/fs/count?path=" + urllib.request.quote(ROOT))
    check(st == 200 and isinstance(fc.get("photos"), int), "/api/fs/count")
    st, fr = req("/api/fs/roots")
    check(st == 200 and isinstance(fr.get("roots"), list), "/api/fs/roots")

    st, sz = req("/api/catalog/size?path=" + urllib.request.quote(s["root"]))
    check(st == 200 and isinstance(sz.get("bytes"), int), "/api/catalog/size")

    st, se = req("/api/settings")
    check(st == 200, "/api/settings")

    # 照片详情 + 图片
    st, q = req("/api/queue?filter=all&sort=time")
    cards = q.get("items") or []
    if cards:
        pid = cards[0]["id"]
        st, ph = req("/api/photo/{}".format(pid))
        check(st == 200 and ph.get("id") == pid, "/api/photo/<id>")
        for k in ("issues", "faces", "group_id", "group_mates", "suggest",
                  "taken_ts", "width", "height"):
            check(k in ph, "/api/photo 有 {}".format(k))
        need_metrics = ("mean_luma", "pct_high", "pct_low", "lap_var", "noise",
                        "tenengrad", "hf_ratio", "tilt_deg", "cast_r", "cast_b")
        missing_m = [k for k in need_metrics if k not in ph]
        check(not missing_m, "照片指标齐全（曝光/锐度/噪点/倾斜/偏色）", str(missing_m))
        st, _ = req("/api/media/{}".format(pid))
        check(st == 200, "/api/media/<id>")
    return s


# --------------------------------------------------------------------- B 数据

def db_path(state):
    return os.path.join(state["work_dir"], "catalog.db")


def data_consistency(state):
    print("\n[B] 数据一致性")
    con = sqlite3.connect(db_path(state))
    con.row_factory = sqlite3.Row

    n_photos = con.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    check(n_photos == state["counts"]["total"],
          "photos 行数 = counts.total", "{} vs {}".format(n_photos, state["counts"]["total"]))

    # 每张分析过的照片都要有 phash、尺寸、时间
    miss = con.execute("SELECT COUNT(*) FROM photos WHERE phash IS NULL").fetchone()[0]
    check(miss == 0, "所有照片都有 phash", "缺 {}".format(miss))
    miss = con.execute("SELECT COUNT(*) FROM photos WHERE width IS NULL OR height IS NULL").fetchone()[0]
    check(miss == 0, "所有照片都有尺寸", "缺 {}".format(miss))

    # 分类：issues 的 kind 必须在已知集合里，severity 合规范
    from guopian import analyze as A
    known = set(A._ISSUE_TEXT.keys())
    kinds = {r[0] for r in con.execute("SELECT DISTINCT kind FROM issues")}
    unknown = kinds - known
    check(not unknown, "issues 里没有未知分类", str(unknown))
    sev = {r[0] for r in con.execute("SELECT DISTINCT severity FROM issues")}
    check(sev <= {"fatal", "high", "medium", "low", "info"},
          "severity 取值合法", str(sev))

    # 分类计数必须和 issue_summary 对得上
    summary = {row["kind"]: int(row["n"]) for row in (state["issue_summary"] or [])}
    mismatch_kind = None
    # 按**照片**计数，不是按 issues 行数：一张照片里两张脸都闭眼会产生两行，
    # 而界面上的"眼睛闭合 12"说的是 12 张照片。之前用 COUNT(*) 比，两边的口径
    # 不一样，碰到多人合影就误报。
    for kind, n in con.execute("SELECT kind, COUNT(DISTINCT photo_id) FROM issues GROUP BY kind"):
        if kind not in summary:
            mismatch_kind = "issue_summary 缺少 {}".format(kind)
            break
        if summary[kind] != int(n):
            mismatch_kind = "{}: db {} vs api {}".format(kind, n, summary[kind])
            break
    check(mismatch_kind is None,
          "issue_summary 与 issues 表逐项一致（{} 类）".format(len(kinds)),
          str(mismatch_kind))

    # 分组：members 必须是照片 id；group_size 必须等于组内张数；best 必须在组内
    ids = {r[0] for r in con.execute("SELECT id FROM photos")}
    gids = {r[0] for r in con.execute("SELECT id FROM groups")}
    bad_rows = con.execute(
        "SELECT COUNT(*) FROM photos WHERE group_id NOT IN (SELECT id FROM groups)").fetchone()[0]
    check(bad_rows == 0, "每张照片的 group_id 都指向存在的组", "{} 条脏数据".format(bad_rows))
    empty_groups = con.execute(
        "SELECT COUNT(*) FROM groups g WHERE NOT EXISTS "
        "(SELECT 1 FROM photos p WHERE p.group_id=g.id)").fetchone()[0]
    check(empty_groups == 0, "没有空组", "{} 个空组".format(empty_groups))

    mismatch = con.execute(
        "SELECT COUNT(*) FROM photos p JOIN (SELECT group_id, COUNT(*) c FROM photos "
        "GROUP BY group_id) g ON g.group_id = p.group_id WHERE p.group_size <> g.c").fetchone()[0]
    check(mismatch == 0, "group_size 和实际张数一致", "{} 张不一致".format(mismatch))

    orphan_best = con.execute(
        "SELECT COUNT(*) FROM groups WHERE best_photo_id IS NOT NULL AND best_photo_id NOT IN "
        "(SELECT id FROM photos)").fetchone()[0]
    check(orphan_best == 0, "best_photo_id 都指向存在的照片", "{} 条越界".format(orphan_best))

    # 判定：decision 只能是三种值或空
    dv = {r[0] for r in con.execute("SELECT DISTINCT decision FROM photos")}
    check(dv <= {"keep", "reject", "pick", None}, "decision 取值合法", str(dv))

    # 标定：有 calibration 才能谈"相对阈值"
    calib = state.get("calibration")
    check(isinstance(calib, dict) and bool(calib), "calibration 存在且非空")

    # 相似组与向量：有向量的照片应该都能参与分组
    n_vec = con.execute("SELECT COUNT(*) FROM photo_vec").fetchone()[0]
    check(n_vec == n_photos, "photo_vec 覆盖全部照片", "{}/{}".format(n_vec, n_photos))
    dims = {r[0] for r in con.execute("SELECT DISTINCT dim FROM photo_vec")}
    check(dims <= {576}, "向量维度都是 576", str(dims))

    # 组内最弱的一对不能低于阈值（完全连接的硬约束）
    from guopian import config
    import numpy as np
    ids_l, mat = [], []
    for r in con.execute("SELECT photo_id, vec FROM photo_vec ORDER BY photo_id"):
        ids_l.append(r[0])
        mat.append(np.frombuffer(r[1], dtype=np.float16).astype(np.float32))
    V = dict(zip(ids_l, mat))
    worst = 1.0
    worst_pair = None
    for g in con.execute("SELECT group_id FROM photos WHERE group_size>1 GROUP BY group_id").fetchall():
        mem = [r[0] for r in con.execute("SELECT id FROM photos WHERE group_id=?", (g[0],))]
        for a in range(len(mem)):
            for b in range(a + 1, len(mem)):
                va, vb = V.get(mem[a]), V.get(mem[b])
                if va is None or vb is None:
                    continue
                cos = float(va @ vb)
                if cos < worst:
                    worst, worst_pair = cos, (mem[a], mem[b])
    check(worst >= config.EMBED_COSINE - 0.02,
          "组内最弱的一对也在阈值附近（完全连接成立）",
          "最弱 {:.3f} < {:.2f} {!r}".format(worst, config.EMBED_COSINE, worst_pair))
    print("       组内最弱余弦：{:.3f}".format(worst))
    con.close()


# --------------------------------------------------------------------- C 删除

def deletion(state):
    """删项目：识别数据必须干净，照片一张不少。"""
    print("\n[C] 删除项目（只删识别数据）")
    path = state["root"]
    work = state["work_dir"]
    db = os.path.join(work, "catalog.db")

    photos_before = sorted(os.listdir(path))
    size_before = sum(os.path.getsize(os.path.join(path, f))
                      for f in photos_before if os.path.isfile(os.path.join(path, f)))
    check(os.path.isdir(work), "删除前 catalog 目录存在")

    # 关掉库再删（真实路径是 home 页的 ✕ → 删除数据）
    req("/api/close", {})
    st, r = req("/api/forget", {"path": path, "delete_data": True})
    check(st == 200 and r.get("ok"), "delete_data 删除成功", str(r))
    check(r.get("freed", 0) > 0, "有释放空间", str(r.get("freed")))

    check(not os.path.exists(work), "catalog 目录已不存在", work)
    check(not os.path.exists(db), "catalog.db 已不存在", db)
    leftovers = []
    for dirpath, _d, files in os.walk(work) if os.path.isdir(work) else []:
        leftovers.extend(files)
    check(not leftovers, "catalog 里没有残留文件", str(leftovers[:5]))

    # 照片必须一张不少、大小不变
    photos_after = sorted(os.listdir(path))
    size_after = sum(os.path.getsize(os.path.join(path, f))
                     for f in photos_after if os.path.isfile(os.path.join(path, f)))
    check(photos_before == photos_after, "照片文件名一个不少", 
          "前 {} 后 {}".format(len(photos_before), len(photos_after)))
    check(size_before == size_after, "照片总大小不变",
          "{} vs {}".format(size_before, size_after))

    # 也不该在照片目录里留下我们自己的东西
    hidden = [f for f in photos_after if f.startswith(".") or f in
              ("_guopian_rejected", ".guopian")]
    check(not hidden, "照片目录里没有我们留下的隐藏目录", str(hidden))

    # 重新打开：必须从零开始（新 catalog + 没有向量/分组）
    st, o = req("/api/open", {"path": path})
    check(st == 200, "重新打开成功")
    st, s2 = req("/api/state")
    check(s2["counts"]["total"] == 0 or s2["progress"]["running"],
          "重新打开时是新库（total=0 或正在扫描）",
          str(s2["counts"]))
    req("/api/cancel", {})
    print("       重新打开后的 key：{}（应为新值）".format(s2.get("catalog_key")))
    return s2


def main():
    path = None
    if "--path" in sys.argv:
        path = sys.argv[sys.argv.index("--path") + 1]

    st, home = req("/api/home")
    recent = (home.get("recent") or [])
    if path:
        req("/api/open", {"path": path})
    elif not recent:
        print("没有打开的库，也没有 --path")
        return 2
    else:
        req("/api/open", {"path": recent[0]["path"], "no_scan": True})

    st, s = req("/api/state")
    if st != 200:
        print("库打不开：", st)
        return 2
    # 等分析跑完再校验 —— 分析期间 issues 表正在被重写，逐项比对会撞上中间态
    import time as _t
    for _ in range(240):
        if not s["progress"].get("running"):
            break
        _t.sleep(2)
        st, s = req("/api/state")
    print("库：{}（{} 张）".format(s["root"], s["counts"]["total"]))

    s = api_surface() or s
    data_consistency(s)
    # 删除测试会真的删掉这个库的识别数据。只允许对仓库里的测试拷贝做，
    # 绝不对用户自己的相册跑 —— 那要重新分析十几分钟。
    inside_repo = os.path.abspath(s["root"]).lower().startswith(ROOT.lower())
    if "--keep" in sys.argv:
        print("\n[C] 跳过删除测试（--keep）")
    elif not inside_repo and "--force-delete" not in sys.argv:
        print("\n[C] 跳过删除测试：{} 不在仓库里，不敢动（要真删加 --force-delete）"
              .format(s["root"]))
    else:
        deletion(s)

    print("\n===== {} 通过 / {} 失败".format(len(OKS), len(FAILS)))
    for f in FAILS:
        print("  ✗ " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
