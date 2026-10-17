"""Benchmark the analysis pipeline on a real folder.

    python evaluation/bench.py <folder> [n_photos] [workers...]

Reports single-thread cost per stage, then wall-clock at several worker counts,
so it is obvious whether the bottleneck is the work itself or thread scaling.
Read-only: it never writes to the photo folder.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("MPLCONFIGDIR", os.path.join(ROOT, ".cache", "matplotlib"))

from guopian import analyze, config, faces, imageio, metrics, phash  # noqa: E402


def stage_timings(paths: list[str]) -> None:
    print("\n=== 单张各阶段耗时（单线程，{} 张取样）===".format(len(paths)))
    acc: dict[str, float] = {}

    def add(k, dt):
        acc[k] = acc.get(k, 0.0) + dt

    for p in paths:
        t = time.perf_counter()
        img, _, dscale = imageio.open_image(p, max_edge=config.ANALYSIS_EDGE)
        add("1 解码(draft)", time.perf_counter() - t)
        t = time.perf_counter()
        gray = metrics.to_gray(img)
        add("2 转灰度+缩放", time.perf_counter() - t)

        t = time.perf_counter()
        _ = metrics._lap_var(gray)
        add("3a 拉普拉斯", time.perf_counter() - t)
        t = time.perf_counter()
        _ = metrics._tenengrad(gray)
        add("3b Tenengrad", time.perf_counter() - t)
        t = time.perf_counter()
        _ = metrics._hf_ratio(gray)
        add("3c FFT 高频", time.perf_counter() - t)
        t = time.perf_counter()
        _ = metrics._noise_sigma(gray)
        add("3d 噪点", time.perf_counter() - t)
        t = time.perf_counter()
        _ = metrics._tilt_deg(gray)
        add("3e 倾斜", time.perf_counter() - t)
        t = time.perf_counter()
        _ = metrics._blockiness(gray)
        add("3f 块效应", time.perf_counter() - t)

        t = time.perf_counter()
        m = metrics.global_metrics(gray, *img.size)
        add("4 global_metrics 合计", time.perf_counter() - t)

        t = time.perf_counter()
        _ = phash.phash_bytes(img)
        add("5 phash", time.perf_counter() - t)

        if faces.available()[0]:
            t = time.perf_counter()
            _ = faces.analyze_faces(img, gray, 1.0, m["lap_var"], dscale)
            add("6 人脸", time.perf_counter() - t)

    n = len(paths)
    for k in sorted(acc):
        print("  {:<24} {:8.1f} ms/张".format(k, acc[k] / n * 1000))
    print("  {:<24} {:8.1f} ms/张".format(
        "合计(不含重复计算)", (acc.get("1 解码(draft)", 0) * 2 + acc.get("2 转灰度+缩放", 0)
                          + acc.get("4 global_metrics 合计", 0) + acc.get("5 phash", 0)
                          + acc.get("6 人脸", 0)) / n * 1000))


def thread_scaling(paths: list[str], worker_counts: list[int]) -> None:
    print("\n=== 线程扩展性（完整 analyze_photo）===")
    for w in worker_counts:
        work_dir = tempfile.mkdtemp(prefix="guopian-bench-")
        from guopian.pipeline import Library

        lib = Library(os.path.dirname(paths[0]), workers=w, work_dir=work_dir, read_only=True)
        lib.store.upsert_scanned([
            {"path": p, "rel_path": os.path.basename(p), "name": os.path.basename(p),
             "size": os.path.getsize(p), "mtime": os.path.getmtime(p),
             "ext": os.path.splitext(p)[1].lower()} for p in paths])

        stamps: list[tuple[float, float]] = []

        def timed(p):
            t0 = time.perf_counter()
            try:
                analyze.analyze_photo(p)
            except Exception:
                pass
            stamps.append((t0, time.perf_counter()))

        t = time.perf_counter()
        with ThreadPoolExecutor(max_workers=w) as ex:
            list(ex.map(timed, paths))
        dt = time.perf_counter() - t
        print("  workers={:<3} {:7.2f}s  {:8.1f} ms/张".format(w, dt, dt / len(paths) * 1000))
        stamps.sort()
        print("      单张: " + " ".join("{:.0f}ms".format((b - a) * 1000) for a, b in stamps))
        _rmtree(work_dir)


def _one(p):
    try:
        analyze.analyze_photo(p)
    except Exception:
        pass


def _rmtree(d):
    import shutil

    try:
        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


def main() -> int:
    folder = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    workers = [int(x) for x in sys.argv[3:]] or [1, 2, 4, 8]

    from guopian.pipeline import Library

    lib = Library(folder, read_only=True, work_dir=tempfile.mkdtemp(prefix="guopian-bench-"))
    files = lib.scan_files()
    print("{}: {} 个文件, CPU {} 核".format(folder, len(files), os.cpu_count()))
    ok, msg = faces.available()
    print("人脸检测: {}".format("可用" if ok else "不可用 ({}）".format(msg)))
    if not files:
        return 1
    paths = [f["path"] for f in files[:n]]
    stage_timings(paths)
    thread_scaling(paths, workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
