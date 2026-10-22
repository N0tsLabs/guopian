"""The analysis pipeline: scan -> metrics+faces -> relative evaluation.

Stage 1 (expensive) produces raw numbers per photo.
Stage 2 (cheap, whole-library) calibrates thresholds, groups bursts, ranks
inside groups and turns numbers into named problems.

The UI can start working the moment stage 1 has touched enough photos; stage 2
is re-run whenever new results land. That is the "progressive" design from
docs/05 -- analysis is ~10x faster than a human, so the only thing that ever
felt slow was waiting for *all* of it.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import analyze, config, faces, group, imageio, metrics
from .store import Store, face_gates as store_face_gates


class Progress:
    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "idle"
        self.total = 0
        self.done = 0
        self.ok = 0
        self.failed = 0
        self.current = ""
        self.message = ""
        self.started = 0.0
        self.finished = 0.0
        self.rate = 0.0
        self.cancelled = False
        # 边分析边分类：{"face": 12, "no_face": 3, "issue:blurry": 2, ...}
        # 首屏那个"分类情况"图表读的就是它。只在第一遍分析时填 —— 之后
        # 精确的分类在 recompute() 里按标定重算，两套数字不混用。
        self.buckets: dict[str, int] = {}

    def snap(self) -> dict:
        with self.lock:
            elapsed = (self.finished or time.time()) - self.started if self.started else 0.0
            return {
                "phase": self.phase, "total": self.total, "done": self.done,
                "ok": self.ok, "failed": self.failed, "current": self.current,
                "message": self.message, "elapsed": round(elapsed, 2),
                "rate": round(self.rate, 2),
                "eta": round((self.total - self.done) / self.rate, 1) if self.rate > 0 and self.done < self.total else 0,
                "cancelled": self.cancelled,
                "running": self.phase not in ("idle", "done", "error", "cancelled"),
                "buckets": dict(self.buckets),
            }

    def update(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)
            if self.started and self.done:
                self.rate = self.done / max(0.001, time.time() - self.started)


class Library:
    def __init__(self, root: str, workers: int | None = None, work_dir: str | None = None,
                 read_only: bool = False):
        """`work_dir` keeps the catalog and thumbnails OUTSIDE the photo folder.

        Needed for read-only sources (an SD card, a mounted backup, or simply
        not wanting to drop a .guopian directory into someone's library).

        `read_only=True` additionally makes the server refuse to apply any
        decision to disk -- culling still works, nothing can ever be moved.
        """
        self.root = os.path.abspath(root)
        if not os.path.isdir(self.root):
            raise NotADirectoryError(self.root)
        self.work_dir = os.path.abspath(work_dir) if work_dir else \
            os.path.join(self.root, config.WORK_DIR_NAME)
        self.read_only = bool(read_only)
        self.store = Store(self.work_dir)
        self.store.set_meta("root", self.root)
        self.store.set_meta("read_only", self.read_only)
        self.thumbs = imageio.ThumbCache(self.work_dir)
        self.workers = workers or max(1, min(8, (os.cpu_count() or 4) - 1))
        self.progress = Progress()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    # -------------------------------------------------------------- scan

    def scan_files(self) -> list[dict]:
        rows = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames
                           if d not in (config.WORK_DIR_NAME, config.TRASH_DIR_NAME)
                           and not d.startswith(".")]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in config.SUPPORTED_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                rows.append({
                    "path": full,
                    "rel_path": os.path.relpath(full, self.root),
                    "name": fn,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "ext": ext,
                })
        rows.sort(key=lambda r: (r["rel_path"] or ""))
        return rows

    # -------------------------------------------------------------- stage 1

    def analyze_pending(self, limit: int | None = None) -> int:
        self.store.conn  # ensure schema
        pending = self.store.needs_analysis(config.ANALYSIS_VERSION)
        if limit:
            pending = pending[:limit]
        self.progress.update(phase="analyze", total=len(pending), done=0, ok=0, failed=0,
                             started=time.time(), finished=0.0, message="分析中")
        if not pending:
            return 0

        face_ok, face_msg = faces.available()
        if face_ok:
            faces.configure_pool(self.workers)
        self.progress.update(
            message=("分析中（人脸检测已启用）" if face_ok else "分析中（未启用人脸检测：{}）".format(face_msg))
        )

        def work(row):
            if self._cancel.is_set():
                return None
            try:
                res = analyze.analyze_photo(row["path"])
                self.store.save_analysis(row["id"], res["meta"], res["metrics"],
                                         res["faces"], [], res["phash"])
                return res
            except Exception as e:
                # Discard anything half-written for this photo before recording
                # the failure, otherwise a partial row would look "analysed".
                try:
                    self.store.conn.rollback()
                except Exception:
                    pass
                self.store.mark_error(row["id"], "{}: {}".format(type(e).__name__, e))
                return None

        self._live_reset()
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futs = {pool.submit(work, r): r for r in pending}
            for fut in as_completed(futs):
                row = futs[fut]
                try:
                    res = fut.result()
                except Exception:
                    res = None
                if res:
                    # 这一步只是让首屏图表有东西看，失败不能影响分析本身。
                    try:
                        self._live_add(row, res)
                    except Exception:
                        pass
                with self.progress.lock:
                    self.progress.done += 1
                    if res:
                        self.progress.ok += 1
                    else:
                        self.progress.failed += 1
                    self.progress.current = row["name"]
                    if self.progress.done:
                        self.progress.rate = self.progress.done / max(
                            0.001, time.time() - self.progress.started)
        return len(pending)

    # -------------------------------------------------- 边分析边分类（首屏图表）

    def _live_reset(self):
        self._live_items: list[tuple[dict, list[dict]]] = []
        self._live_calib: dict = {}
        with self.progress.lock:
            self.progress.buckets = {}

    @staticmethod
    def _live_count_into(merged: dict, faces: list[dict], calib: dict, out: dict):
        if (merged.get("face_count") or 0) > 0:
            out["face"] = out.get("face", 0) + 1
        else:
            out["no_face"] = out.get("no_face", 0) + 1
        try:
            kinds = {i["kind"] for i in analyze.evaluate(merged, faces, calib)}
        except Exception:
            kinds = set()
        for k in kinds:
            key = "issue:" + k
            out[key] = out.get(key, 0) + 1

    def _live_add(self, row: dict, res: dict):
        merged = {**row, **(res.get("meta") or {}), **(res.get("metrics") or {})}
        merged["face_count"] = len(res.get("faces") or [])
        faces = []
        for f in res.get("faces") or []:
            d = dict(f)
            d["gates"] = store_face_gates(d)
            faces.append(d)
        self._live_items.append((merged, faces))

        # 阈值要靠整批照片的分布算（soft/noisy 都是相对值），所以一开始没有
        # 标定，先用绝对门槛；每收满一批重算一次标定并把已完成的重新分类。
        # 这样图表会"越来越准"，而不是一直按第一条规则乱分。
        if len(self._live_items) % config.LIVE_REBUILD_EVERY == 0:
            self._live_calib = metrics.calibrate([m for m, _ in self._live_items])
            self._live_recount()
        else:
            add: dict[str, int] = {}
            self._live_count_into(merged, faces, self._live_calib, add)
            with self.progress.lock:
                for k, v in add.items():
                    self.progress.buckets[k] = self.progress.buckets.get(k, 0) + v

    def _live_recount(self):
        out: dict[str, int] = {}
        for merged, faces in self._live_items:
            self._live_count_into(merged, faces, self._live_calib, out)
        with self.progress.lock:
            self.progress.buckets = out

    # -------------------------------------------------------------- stage 2

    def recompute(self) -> dict:
        self.progress.update(phase="evaluate", message="计算相对阈值与相似分组…")
        rows = self.store.load_rows()
        if not rows:
            return {"photos": 0, "groups": 0}

        calib = metrics.calibrate(rows)
        face_index = self.store.load_face_index()

        # Face-region sharpness and gaze are only meaningful relative to other
        # faces, so derive their percentiles here where the face table exists.
        fsharps = [f.get("face_sharp") for fcs in face_index.values()
                   for f in fcs if f.get("face_sharp") is not None]
        f15 = metrics.percentile(fsharps, config.FACE_SHARP_PERCENTILE) if len(fsharps) >= 8 else None
        gazes = [f.get("gaze_away") for fcs in face_index.values()
                 for f in fcs if (f.get("gates") or {}).get("judge_eyes")
                 and f.get("gaze_away") is not None]
        g85 = metrics.percentile(gazes, config.GAZE_SESSION_PCT) if len(gazes) >= 8 else 0.0

        # Colour cast is always judged against the median of the same shoot. A
        # sunset really is orange; only photos that stand out from their own
        # siblings are worth a second look. Needs a decent sample before the
        # median means anything.
        casts = [(r["cast_r"], r["cast_b"]) for r in rows
                 if r["cast_r"] is not None and r["cast_b"] is not None]
        cast_ctx = None
        if len(casts) >= 12:
            rr = [c[0] for c in casts]
            bb = [c[1] for c in casts]
            cast_ctx = {
                "r_med": metrics.percentile(rr, 50.0),
                "b_med": metrics.percentile(bb, 50.0),
                "r_lo": metrics.percentile(rr, config.CAST_PCT),
                "r_hi": metrics.percentile(rr, 100.0 - config.CAST_PCT),
                "b_lo": metrics.percentile(bb, config.CAST_PCT),
                "b_hi": metrics.percentile(bb, 100.0 - config.CAST_PCT),
            }

        for blk in calib.values():
            blk["face_sharp_p15"] = f15
            blk["gaze_p85"] = g85
            blk["cast"] = cast_ctx
        self.store.set_meta("calibration", calib)

        groups = group.build_groups(rows)
        group.rank_groups(rows, face_index, groups)

        # 键必须是照片 id，不是 rows 里的下标。
        #
        # 这里原来写的是 row_group_ctx[m]（m 是 groups.members 里的下标），
        # 而下面按 row_group_ctx.get(r["id"]) 取 —— 相差一个"下标 vs id"。
        # rows 按拍摄时间排序、id 按入库顺序，两者只有恰好一致时才不出错；
        # 这个库里一错到底：组信息被贴到了别的照片上，于是"两张不同瞬间的
        # 照片在同一个组里"这种怪现象，分组算法本身反而是对的。
        row_group_ctx: dict[int, dict] = {}
        for g in groups:
            for m in g["members"]:
                pid = rows[m]["id"]
                row_group_ctx[pid] = {
                    "group_size": len(g["members"]),
                    "group_rank": g["rank"].get(m, 1),
                    "group_best": g.get("best") == m,
                    "exact_duplicate_of": g["exact_dup_of"].get(m),
                    "group_id": g["gid"],
                }

        verdicts: dict[int, dict] = {}
        issues: dict[int, list[dict]] = {}
        for r in rows:
            fcs = face_index.get(r["id"], [])
            items = analyze.evaluate(r, fcs, calib, row_group_ctx.get(r["id"]))
            issues[r["id"]] = items
            verdicts[r["id"]] = analyze.verdict_from(items, row_group_ctx.get(r["id"]))

        self.store.save_pass2(groups, verdicts, issues, rows)
        tally: dict[str, int] = {}
        for v in verdicts.values():
            tally[v["suggest"]] = tally.get(v["suggest"], 0) + 1
        return {"photos": len(rows), "groups": len(groups), "suggest": tally,
                "calibration": calib}

    # -------------------------------------------------------------- driver

    def run_full(self):
        try:
            t0 = time.time()
            self.progress.update(phase="scan", message="扫描文件…", started=t0)
            files = self.scan_files()
            self.store.upsert_scanned(files)
            self.progress.update(message="发现 {} 个图片文件".format(len(files)))

            self.analyze_pending()
            if self._cancel.is_set():
                self.progress.update(phase="cancelled", message="已取消")
                return

            self.recompute()
            self.progress.update(phase="done", finished=time.time(),
                                 message="分析完成，用时 {:.1f} 秒".format(time.time() - t0))
        except Exception as e:
            self.progress.update(phase="error", finished=time.time(),
                                 message="{}: {}".format(type(e).__name__, e),
                                 current=traceback.format_exc()[-1500:])

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._cancel.clear()
        self._thread = threading.Thread(target=self.run_full, daemon=True)
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    # -------------------------------------------------------------- read

    def counts(self) -> dict:
        c = self.store.decision_counts()
        total = self.store.conn.execute("SELECT COUNT(*) n FROM photos").fetchone()["n"]
        analyzed = self.store.conn.execute(
            "SELECT COUNT(*) n FROM photos WHERE analysis_version>=?",
            (config.ANALYSIS_VERSION,)).fetchone()["n"]
        return {"total": total, "analyzed": analyzed, "decisions": c}


