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

from . import analyze, config, embed, faces, group, imageio, metrics
from .store import Store


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
        self._embed_thread: threading.Thread | None = None

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
                return True
            except Exception as e:
                # Discard anything half-written for this photo before recording
                # the failure, otherwise a partial row would look "analysed".
                try:
                    self.store.conn.rollback()
                except Exception:
                    pass
                self.store.mark_error(row["id"], "{}: {}".format(type(e).__name__, e))
                return False

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futs = {pool.submit(work, r): r for r in pending}
            for fut in as_completed(futs):
                row = futs[fut]
                try:
                    got = fut.result()
                except Exception:
                    got = False
                with self.progress.lock:
                    self.progress.done += 1
                    if got:
                        self.progress.ok += 1
                    else:
                        self.progress.failed += 1
                    self.progress.current = row["name"]
                    if self.progress.done:
                        self.progress.rate = self.progress.done / max(
                            0.001, time.time() - self.progress.started)
        return len(pending)

    # -------------------------------------------------------------- stage 3

    def embed_pending(self, limit: int | None = None) -> int:
        """算每张照片的画面向量（语义搜索 + 相似分组的原料）。

        和 analyze_pending 分工不同：那一步算的是"这张图技术上怎么样"，
        这一步算的是"这张图拍的是什么"。所以它只读已经缓存的预览图，
        不解原图、不碰 EXIF —— 一个缩略图就够了，一张 20 ms。

        模型不在就安静地跳过。搜索是可选功能，不能因为没下模型就挡住
        看照片这件事。
        """
        ok, why = embed.available()
        if not ok:
            self.progress.update(phase="embed-skip", message=why)
            return 0

        pending = self.store.missing_vectors(config.EMBED_MODEL)
        if limit:
            pending = pending[:limit]
        if not pending:
            return 0

        self.progress.update(phase="embed", total=len(pending), done=0, ok=0, failed=0,
                             started=time.time(), finished=0.0,
                             message="识别画面内容…")
        from PIL import Image

        size = config.EMBED_BATCH
        for start in range(0, len(pending), size):
            if self._cancel.is_set():
                break
            chunk = pending[start:start + size]
            images, keep = [], []
            for row in chunk:
                try:
                    p = self.thumbs.get_or_build(row["path"], row["size"],
                                                 row["mtime"], config.EMBED_EDGE)
                    images.append(Image.open(p))
                    keep.append(row)
                except Exception:
                    self.store.mark_error(row["id"], "缩略图读不出来")
                    with self.progress.lock:
                        self.progress.done += 1
                        self.progress.failed += 1
            if not images:
                continue
            try:
                vecs = embed.encode(images)
            except Exception as e:
                # A batch that fails should not take the whole pass down: the
                # photos stay "missing" and the next run retries them.
                with self.progress.lock:
                    self.progress.message = "向量化失败：{}".format(e)
                continue
            for row, v in zip(keep, vecs):
                self.store.set_vector(row["id"], v, config.EMBED_MODEL)
            self.store.conn.commit()
            with self.progress.lock:
                self.progress.done += len(keep)
                self.progress.ok += len(keep)
                self.progress.current = keep[-1]["name"]
                self.progress.rate = self.progress.done / max(
                    0.001, time.time() - self.progress.started)
                self.progress.message = "识别画面内容 {}/{}".format(
                    self.progress.done, self.progress.total)
        self.progress.update(message="画面识别完成，共 {} 张".format(self.progress.ok))
        return len(pending)

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

        row_group_ctx: dict[int, dict] = {}
        for g in groups:
            for m in g["members"]:
                row_group_ctx[m] = {
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

        self.store.save_pass2(groups, verdicts, issues)
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

            # 画面向量放在最后：它不影响"这张照片好不好"，只影响"找不找得到"。
            # 先让人能看照片，再让搜索可用。
            self.embed_pending()

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

    def embedding(self) -> bool:
        """向量化那一遍还在跑吗。"""
        return bool(self._embed_thread and self._embed_thread.is_alive())

    def start_embed(self) -> bool:
        """只补向量，不重跑分析。

        单独一个入口，因为这两件事的时间尺度差一个数量级：分析 1428 张要
        几分钟，算向量一分钟。下了模型以后没必要为此重跑一遍分析。
        """
        if self.embedding():
            return False
        self._cancel.clear()
        self._embed_thread = threading.Thread(target=self._embed_only, daemon=True)
        self._embed_thread.start()
        return True

    def _embed_only(self):
        """单独补向量时也要把进度状态收尾，否则界面会一直停在"识别中"。"""
        t0 = time.time()
        try:
            n = self.embed_pending()
            self.progress.update(phase="done", finished=time.time(),
                                 message="画面识别完成 · {} 张 · {:.0f} 秒".format(
                                     n, time.time() - t0))
        except Exception as e:
            self.progress.update(phase="error",
                                 message="{}: {}".format(type(e).__name__, e))

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
