#!/usr/bin/env python3
"""过片 Guopian - start the culler.

    guopian.exe                  open the app (pick a folder inside it)
    guopian.exe "D:\\Photos"     open that folder straight away

Everything runs locally; no photo ever leaves this machine.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys

# ---------------------------------------------------------------------------
# This block MUST run before flask/werkzeug are imported.
#
# In a windowed PyInstaller build (console=False) Windows gives the process no
# console at all, so sys.stdout and sys.stderr are literally None, and the
# C-level file descriptors 1 and 2 are invalid. Werkzeug binds a logging
# handler to sys.stderr at import time; MediaPipe's C++ runtime writes to the
# real descriptors. Fixing only the Python side leaves `import mediapipe`
# killing the process silently -- no traceback, exit code 0.
#
# The log must live where guopian.paths resolves, or every diagnostic vanishes
# on a machine where the primary location is not writable.
# ---------------------------------------------------------------------------

from guopian import paths  # stdlib-only, safe to import this early

_LOG_FH = None


def _redirect_c_streams(to_path: str) -> None:
    try:
        fd = os.open(to_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.dup2(fd, 1)
            os.dup2(fd, 2)
        finally:
            if fd > 2:
                os.close(fd)
    except Exception:
        pass


def _bootstrap_streams() -> None:
    global _LOG_FH

    # Only a windowed build has broken streams. Redirecting unconditionally
    # would send a console build's print() output into the log file too, and
    # then `--report` and `--selftest` would look like they had printed
    # nothing at all.
    broken = sys.stdout is None or sys.stderr is None
    if not broken:
        return

    try:
        target = os.path.join(paths.user_data_dir(), "guopian.log")
    except Exception:
        target = None

    if target:
        _redirect_c_streams(target)

    try:
        _LOG_FH = open(target, "a", encoding="utf-8", buffering=1) if target else None
    except Exception:
        _LOG_FH = None
    if _LOG_FH is None:
        import io

        _LOG_FH = io.StringIO()
    if sys.stdout is None:
        sys.stdout = _LOG_FH
    if sys.stderr is None:
        sys.stderr = _LOG_FH


def _bootstrap_logging() -> None:
    import logging

    def fix(lg):
        for h in list(getattr(lg, "handlers", [])):
            if isinstance(h, logging.StreamHandler) and getattr(h, "stream", "x") is None:
                h.stream = sys.stderr

    for name in list(logging.Logger.manager.loggerDict):
        fix(logging.getLogger(name))
    fix(logging.getLogger())


_bootstrap_streams()

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "matplotlib"),
)

from guopian import __version__, config, launcher, session as session_mod, server  # noqa: E402

_bootstrap_logging()


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _setup_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass


def main() -> int:
    _setup_console_encoding()

    ap = argparse.ArgumentParser(
        prog="guopian",
        description="过片 Guopian - 本地照片筛选 / local photo culling",
    )
    ap.add_argument("folder", nargs="?",
                    help="照片文件夹。不填就直接打开界面，在界面里选。")
    ap.add_argument("--port", type=int, default=8765, help="本地端口 (默认 8765)")
    ap.add_argument("--workers", type=int, default=None, help="分析线程数")
    ap.add_argument("--work-dir", default=None,
                    help="索引/缩略图位置（默认在用户数据目录）")
    ap.add_argument("--portable", action="store_true",
                    help="便携模式：索引放在程序目录下的 catalogs/")
    ap.add_argument("--read-only", action="store_true",
                    help="禁止一切文件移动。筛选照常，但永远不会改动原图。")
    ap.add_argument("--reset", action="store_true", help="清空该库的索引重新分析")
    ap.add_argument("--no-open", action="store_true", help="不要打开窗口")
    ap.add_argument("--browser", action="store_true",
                    help="用默认浏览器打开，而不是应用窗口")
    ap.add_argument("--dev", action="store_true",
                    help="开发模式：普通浏览器标签页 + 自动刷新 + 自动重启 + 不缓存资源")
    ap.add_argument("--devtools", action="store_true",
                    help="应用窗口里自动打开 DevTools")
    ap.add_argument("--no-scan", action="store_true", help="打开文件夹但不自动扫描")
    ap.add_argument("--report", action="store_true",
                    help="只做分析并打印报告，不启动界面")
    ap.add_argument("--selftest", action="store_true",
                    help="启动服务并自检一次，然后退出。排查打包问题用。")
    ap.add_argument("--version", action="version",
                    version="过片 Guopian {} ({})".format(
                        __version__, "packaged" if paths.is_frozen() else "source"))
    args = ap.parse_args()

    if args.portable:
        os.environ["GUOPIAN_PORTABLE"] = "1"

    # Flask's reloader runs this file twice: a supervising parent that holds
    # the listening socket, and a child that actually serves. Both would
    # otherwise run the port check, open the library and start two scans.
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    is_supervisor = args.dev and not is_reloader_child

    # Double-launching should not start a second server. (The reloader child
    # always sees the parent's socket, so it must not test for it.)
    if (not args.report and not args.selftest and not is_reloader_child
            and port_in_use(args.port)):
        url = "http://127.0.0.1:{}".format(args.port)
        if not args.no_open:
            if args.browser or args.dev or not _open_window(url, args.port):
                import webbrowser

                webbrowser.open(url)
        if sys.stdout is not None:
            print("过片已经在运行，已切换到 {}\n".format(url))
        return 0

    sess = session_mod.Session(
        read_only=args.read_only,
        # A command-line value wins; otherwise the saved setting is the
        # default, and 0 means "let the machine decide".
        workers=args.workers or (session_mod.get_settings().get("workers") or None))

    folder = (args.folder or "").strip().strip('"')
    if folder and is_supervisor:
        folder = ""          # the reloader child will open it instead
    if folder:
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            launcher.fatal("过片", "不是有效的文件夹:\n{}".format(folder))
            return 2
        if args.reset:
            import shutil

            shutil.rmtree(args.work_dir or paths.catalog_dir(folder), ignore_errors=True)
        try:
            lib = sess.open(folder, work_dir=args.work_dir,
                            read_only=args.read_only, scan=not args.no_scan)
        except Exception as e:
            launcher.fatal("过片无法打开这个文件夹", "{}\n\n{}".format(e, folder))
            return 1
        paths.log("open root={} work={} read_only={} frozen={}".format(
            folder, lib.work_dir, args.read_only, paths.is_frozen()))
    elif not is_supervisor:
        # No folder given: this is the normal double-click path. Show the app
        # first and let the user pick a library from inside it.
        paths.log("start with no folder (home screen), frozen={}".format(paths.is_frozen()))

    if args.report:
        if sess.require() is None:
            print("--report 需要指定照片文件夹")
            return 2
        return _report(sess.require())

    if args.selftest:
        return _selftest(sess, args.port)

    try:
        server.serve(sess, port=args.port, open_browser=not args.no_open,
                     window=not args.browser, dev=args.dev, devtools=args.devtools)
    except KeyboardInterrupt:
        print("\nbye.")
    except OSError as e:
        launcher.fatal("过片无法启动", "端口 {} 可能被占用。\n\n{}".format(args.port, e))
        return 1
    except Exception as e:
        import traceback

        launcher.fatal("过片启动失败", "{}\n\n{}".format(e, traceback.format_exc()[-1200:]))
        return 1
    finally:
        try:
            from guopian import window as window_mod

            window_mod.close_windows()
        except Exception:
            pass
        sess.close()
    return 0


def _open_window(url: str, port: int) -> bool:
    from guopian import window as window_mod

    return window_mod.open_app_window(url, port)


def _selftest(sess, port: int) -> int:
    """Start the server, talk to it over HTTP, report, exit.

    A windowed build has nowhere to print: this is the only way to prove from
    the outside that the packaged app really serves its UI.
    """
    import json
    import threading
    import time
    import urllib.request

    print("== 过片自检 self test ==")
    print("  version : {} ({})".format(
        __version__, "packaged" if paths.is_frozen() else "source"))
    print("  frozen  : {}".format(paths.is_frozen()))
    print("  bundle  : {}".format(config.ROOT_DIR))
    print("  web dir : {} (exists={})".format(config.WEB_DIR, os.path.isdir(config.WEB_DIR)))
    print("  model   : {} (exists={})".format(config.FACE_MODEL, os.path.exists(config.FACE_MODEL)))
    print("  stdout  : {} / stderr: {}".format(
        type(sys.stdout).__name__, type(sys.stderr).__name__))
    print("  browser : {}".format(_browser_path() or "(none found)"))

    ok, msg = _face_status()
    print("  faces   : {} {}".format(ok, msg or ""))

    lib = sess.require()
    if lib is not None:
        print("  root    : {}".format(lib.root))
        print("  catalog : {}".format(lib.work_dir))
        try:
            files = lib.scan_files()
            lib.store.upsert_scanned(files)
            print("  发现    : {} 个图片文件".format(len(files)))
            if files:
                n = lib.analyze_pending(limit=5)
                res = lib.recompute()
                print("  分析    : {} 张，分组 {} 组".format(n, res.get("groups")))
                nf = lib.store.conn.execute("SELECT COUNT(*) n FROM faces").fetchone()["n"]
                print("  人脸    : {} 条记录".format(nf))
        except Exception as e:
            import traceback

            print("  [FAIL] 分析流程: {}\n{}".format(e, traceback.format_exc()[-800:]))
            return 1

    app = server.create_app(sess, open_browser=False, port=port)
    t = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False,
                               threaded=True, use_reloader=False),
        daemon=True)
    t.start()

    base = "http://127.0.0.1:{}".format(port)
    for _ in range(40):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=3) as r:
                if r.status == 200:
                    break
        except Exception:
            continue
    else:
        print("  [FAIL] 服务在 20 秒内没有起来")
        return 1

    checks: list[tuple[str, bool, str]] = []
    paths_to_check = ["/api/health", "/api/home", "/api/fs/roots",
                      "/api/fs/list", "/", "/app.js", "/style.css", "/home.js"]
    if lib is not None:
        paths_to_check += ["/api/state", "/api/queue"]
    for path in paths_to_check:
        try:
            with urllib.request.urlopen(base + path, timeout=20) as r:
                body = r.read()
                checks.append((path, r.status == 200 and len(body) > 0,
                               "{} bytes".format(len(body))))
        except Exception as e:
            checks.append((path, False, str(e)))

    if lib is not None:
        try:
            with urllib.request.urlopen(base + "/api/queue?filter=all", timeout=30) as r:
                q = json.loads(r.read().decode("utf-8"))
                if q.get("items"):
                    pid = q["items"][0]["id"]
                    for sz in ("small", "card"):
                        with urllib.request.urlopen(
                                base + "/img/{}/{}".format(pid, sz), timeout=30) as rr:
                            b = rr.read()
                            checks.append(("/img/{}/{}".format(pid, sz), len(b) > 0,
                                           "{} bytes".format(len(b))))
        except Exception as e:
            checks.append(("/api/queue", False, str(e)))

    failed = 0
    for name, good, detail in checks:
        print("  [{}] {:<24} {}".format("OK  " if good else "FAIL", name, detail))
        failed += 0 if good else 1

    print("== {} ==".format("自检通过" if failed == 0 else "{} 项失败".format(failed)))
    print("   界面地址: {}".format(base))
    return 0 if failed == 0 else 1


def _browser_path():
    try:
        from guopian import window as window_mod

        return window_mod.find_browser()
    except Exception:
        return None


def _face_status():
    from guopian import faces

    return faces.available()


def _report(lib) -> int:
    import time

    t0 = time.time()
    files = lib.scan_files()
    lib.store.upsert_scanned(files)
    print("  发现 {} 个图片文件".format(len(files)))

    n = lib.analyze_pending()
    dt = time.time() - t0
    print("  分析 {} 张，用时 {:.1f}s  ({:.0f} ms/张，{} 线程)".format(
        n, dt, (dt / n * 1000) if n else 0, lib.workers))

    res = lib.recompute()
    print("  分组 {} 组，建议分布 {}".format(res["groups"], res.get("suggest")))

    rows = lib.store.load_rows()
    print("\n{:<22} {:>9} {:>7} {:>7} {:>6} {:>4}  {:<26} {}".format(
        "文件", "清晰度", "高光%", "暗部%", "噪点", "脸", "问题", "建议"))
    print("-" * 118)
    for r in rows:
        iss = lib.store.conn.execute(
            "SELECT label_zh, severity FROM issues WHERE photo_id=? ORDER BY CASE severity "
            "WHEN 'fatal' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 "
            "ELSE 4 END", (r["id"],)).fetchall()
        tags = " ".join("{}{}".format(i["severity"][:1].upper(), i["label_zh"]) for i in iss[:3])
        if len(iss) > 3:
            tags += " +{}".format(len(iss) - 3)
        print("{:<22} {:>9.1f} {:>7.1f} {:>7.1f} {:>6.2f} {:>4}  {:<26} {}".format(
            (r["name"] or "")[:22], r["lap_var_mp"] or 0, r["pct_high"] or 0,
            r["pct_low"] or 0, r["noise"] or 0, r["face_count"] or 0,
            tags[:26], r["suggest"] or "-"))

    for g in lib.store.conn.execute(
            "SELECT id, size FROM groups WHERE size>1 ORDER BY size DESC LIMIT 25").fetchall():
        members = lib.store.conn.execute(
            "SELECT name, group_rank FROM photos WHERE group_id=? ORDER BY group_rank",
            (g["id"],)).fetchall()
        print("  组 {} ({} 张): {}".format(
            g["id"], g["size"],
            " | ".join("#{} {}".format(m["group_rank"], m["name"]) for m in members[:8])))

    cal = lib.store.get_meta("calibration") or {}
    print("\n--- 相对阈值（按相机聚类）---")
    for k, v in cal.items():
        print("  {:<26} n={:<5} 偏软={:>8.1f} 中位={:>9.1f} 噪点={:>5.2f}".format(
            k[:26], v.get("n", 0), v.get("soft", 0), v.get("sharp_median", 0),
            v.get("noisy", 0)))

    nf = lib.store.conn.execute("SELECT COUNT(*) n FROM faces").fetchone()["n"]
    print("\n  共检出人脸 {} 张".format(nf))
    print("  报告模式：未改动任何照片。")
    print("  索引位置: {}".format(lib.work_dir))
    return 0


if __name__ == "__main__":
    if paths.is_frozen():
        sys.exit(launcher.run_guarded(main))
    sys.exit(main())
