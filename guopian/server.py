"""Local HTTP server. Binds to 127.0.0.1 only -- photos never leave the machine."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

from flask import Flask, jsonify, request, send_file, send_from_directory

from . import config, decisions, imageio, paths, session as session_mod
from .session import Session

# kept for backward compatibility with older imports
BROWSER_EXT = config.BROWSER_DISPLAYABLE

# Set when the app window actually renders the page. Launching a browser is
# not proof that a window appeared -- Edge can crash on startup, hand off to an
# existing instance, or silently do nothing -- so we insist on evidence before
# telling the user everything is fine.
_WINDOW_SEEN = {"pending": False, "seen": False}

# Served only in --dev mode. Polls a token derived from source mtimes and
# reloads the page when anything under web/ or guopian/ changes, so the
# edit-save-look loop is one keystroke instead of a manual refresh.
_DEV_RELOAD_JS = """
(function () {
  var last = null, misses = 0;
  function poll() {
    fetch('/api/dev/token', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        misses = 0;
        if (last !== null && d.token !== last) { location.reload(); return; }
        last = d.token;
      })
      .catch(function () {
        // the Python reloader restarts the process; reconnect when it is back
        if (++misses === 4) { last = null; }
      })
      .then(function () { setTimeout(poll, 600); });
  }
  poll();
})();
"""


def _dev_token() -> float:
    """Newest mtime across the sources the UI is built from.

    `catalogs` is skipped on purpose: in portable mode the catalog and its
    thumbnail cache live INSIDE the package directory, so walking everything
    meant stat-ing thousands of cached .jpg files -- and every open tab polls
    this once or twice a second just to decide whether to reload.
    """
    newest = 0.0
    roots = [config.WEB_DIR, os.path.join(config.ROOT_DIR, "guopian")]
    skip = {"__pycache__", "catalogs", "node_modules", ".cache"}
    for base in roots:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for f in filenames:
                if f.endswith((".py", ".js", ".css", ".html")):
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(dirpath, f)))
                    except OSError:
                        pass
    return round(newest, 3)


def _row_to_card(r) -> dict:
    d = dict(r)
    ev = d.get("evidence")
    if ev:
        try:
            d["evidence"] = json.loads(ev)
        except Exception:
            d["evidence"] = None
    return d


def create_app(sess: Session, open_browser: bool = True, port: int = 0,
               dev: bool = False) -> Flask:
    app = Flask(__name__, static_folder=None)
    # Saved settings become live constants before anything reads them. Modules
    # look up `config.X` at call time, so rebinding here reaches every detector
    # without any plumbing -- and doing it at startup rather than on each
    # request means a settings change costs nothing per photo.
    config.apply_settings(session_mod.get_settings())
    # Portable became the default; installations made before that kept
    # their data in the user profile. Move it once, quietly, so an
    # upgrade does not look like every library disappeared.
    _moved = paths.migrate_legacy_data()
    # Local assets are tiny and change between builds; caching them only ever
    # produces "I updated the app but still see the old UI".
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["GUOPIAN_DEV"] = bool(dev)
    web_dir = config.WEB_DIR

    @app.after_request
    def _no_store_api(resp):
        """JSON answers describe the *currently open* library, and every library
        starts its photo ids at 1. `/api/queue?filter=all` therefore means
        something different after a project switch while its URL stays the same;
        Flask sends no Cache-Control and no validator here, so nothing stops a
        browser from reusing the old body. The app already has one measured bug
        of exactly this shape -- the thumbnails (see image()). Refuse to cache
        these instead of trusting heuristic freshness.
        """
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def need_lib():
        """(library, error_response). Every library endpoint goes through this."""
        lib = sess.require()
        if lib is not None:
            # The catalog lives in its own directory and can vanish while a
            # library is still open -- deleted by hand, or by a cleaner. Without
            # this the next request died with sqlite3.OperationalError and a 500,
            # which tells the user nothing. "The index this needs is gone" is a
            # 409, and every library endpoint goes through here, so one guard
            # covers all of them.
            try:
                lib.store.conn.execute("SELECT 1 FROM photos LIMIT 1").fetchone()
            except Exception:
                sess.close()
                return None, (jsonify({"error": "这个库的索引不在了，请重新打开",
                                       "gone": True}), 409)
        if lib is None:
            return None, (jsonify({"error": "no_library",
                                   "message": "还没有打开照片文件夹"}), 409)
        return lib, None

    # ---------------------------------------------------------- static
    @app.get("/")
    def index():
        if request.args.get("guopian_window"):
            _WINDOW_SEEN["seen"] = True
        if dev:
            # Inject the reload client instead of shipping it in the bundle.
            html = open(os.path.join(web_dir, "index.html"), encoding="utf-8").read()
            inject = '<script src="/dev-reload.js"></script>\n</body>'
            if "</body>" in html:
                html = html.replace("</body>", inject, 1)
            return html, 200, {"Cache-Control": "no-store",
                               "Content-Type": "text/html; charset=utf-8"}
        return send_from_directory(web_dir, "index.html")

    @app.get("/p/<slug>")
    def project_url(slug):
        """Serve the app at /p/<slug>.

        Without this a refresh on a project URL would 404 -- the whole point of
        putting the project in the address bar is that reloading keeps you where
        you were. The slug is not resolved here: the page reads it back and asks
        for the matching project, which keeps this route a dumb file server and
        leaves "which project is this" in one place.
        """
        return send_from_directory(web_dir, "index.html")

    @app.get("/<path:asset>")
    def assets(asset):
        resp = send_from_directory(web_dir, asset)
        if dev:
            resp.headers["Cache-Control"] = "no-store"
        return resp

    if dev:
        @app.get("/dev-reload.js")
        def dev_reload_js():
            return _DEV_RELOAD_JS, 200, {
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-store",
            }

        @app.get("/api/dev/token")
        def dev_token():
            return jsonify({"token": _dev_token()})

    # ---------------------------------------------------------- home
    @app.get("/api/home")
    def home():
        lib = sess.require()
        state = None
        if lib is not None:
            state = {
                "root": lib.root,
                "slug": paths.slug(lib.root),
                "work_dir": lib.work_dir,
                "read_only": bool(lib.read_only),
                "counts": lib.counts(),
                "progress": lib.progress.snap(),
                "issue_summary": _issue_summary(lib),
            }
        return jsonify({
            "version": _version(),
            "generation": sess.generation,
            "recent": session_mod.recent_libraries(),
            "current": state,
            "face_available": _faces_ok(),
            "platform": _platform(),
            "labels": _labels(),
        })

    @app.post("/api/open")
    def open_library():
        body = request.get_json(force=True) or {}
        path = (body.get("path") or "").strip().strip('"')
        if not path:
            return jsonify({"ok": False, "error": "没有指定文件夹"}), 400
        if not os.path.isdir(path):
            return jsonify({"ok": False, "error": "不是有效的文件夹:\n{}".format(path)}), 400
        # 打开时不再问"只读"，也不猜。
        #
        # 那个复选框在选文件夹的那一刻要求用户做一个还没法理解的决定（"只读"
        # 到底是少了什么？），删掉。自动判断也试过：探测文件夹能不能写 —— 但
        # 探测本身会被运行环境误导（进程权限低时明明能写的目录也报只读），
        # 结果会静默把应用切进只读，那是更糟的失败方式。
        # 只保留命令行 --read-only 这条显式入口。
        explicit = body.get("read_only")
        read_only = bool(explicit) if explicit is not None else sess.read_only
        writable = True
        try:
            lib = sess.open(path,
                            work_dir=body.get("work_dir") or None,
                            read_only=read_only,
                            scan=not bool(body.get("no_scan")))
        except Exception as e:
            return jsonify({"ok": False, "error": "{}: {}".format(type(e).__name__, e)}), 500
        return jsonify({"ok": True, "generation": sess.generation,
                        "root": lib.root, "work_dir": lib.work_dir,
                        "slug": paths.slug(lib.root),
                        "read_only": bool(lib.read_only),
                        "writable": writable})

    @app.post("/api/close")
    def close_library():
        sess.close()
        return jsonify({"ok": True, "generation": sess.generation})

    @app.post("/api/reveal")
    def reveal():
        """Show a folder in the OS file manager.

        Only a remembered library can be revealed -- the same allow-list as
        /api/cover. A loopback endpoint that opens an arbitrary path is a way to
        make the machine do something the user did not ask for.
        """
        b = request.get_json(silent=True) or {}
        path = (b.get("path") or "").strip()
        if not path or path not in {r["path"] for r in session_mod.recent_libraries()}:
            return jsonify({"ok": False, "error": "路径不在最近列表里"}), 404
        if not os.path.isdir(path):
            return jsonify({"ok": False, "error": "文件夹不存在"}), 404
        try:
            if sys.platform == "win32":
                os.startfile(path)                     # noqa: S606 - user's own folder
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": True})

    @app.post("/api/forget")
    def forget():
        body = request.get_json(force=True) or {}
        path = body.get("path", "")
        wipe = bool(body.get("delete_data"))
        # 要删数据的话，先把当前打开/挂着的库放掉，否则 Windows 上 SQLite 的
        # 句柄会让目录删不掉。close() 会把当前库挪进 _DETACHED，这里直接取出来。
        live = None
        if wipe:
            with sess.lock:
                if sess.lib is not None and os.path.abspath(sess.lib.root) == os.path.abspath(path):
                    live = sess.lib
                    sess.lib = None
                    sess.generation += 1
        res = session_mod.forget(path, wipe, live_lib=live)
        out = {"ok": True, "freed": res.get("freed", 0),
               "recent": session_mod.recent_libraries()}
        if wipe and not res.get("removed", True):
            out["ok"] = False
            out["error"] = "分析数据删不掉（可能还有别的程序占着），稍后再试一次"
        return jsonify(out)

    @app.get("/api/catalog/size")
    def catalog_size():
        """这个项目的分析数据占多大（确认框里要写清楚代价）。"""
        return jsonify(session_mod.catalog_size(request.args.get("path", "")))

    # ---------------------------------------------------------- fs browser
    @app.get("/api/fs/roots")
    def fs_roots():
        return jsonify({"roots": session_mod.fs_roots(),
                        "home": os.path.expanduser("~")})

    @app.get("/api/fs/list")
    def fs_list():
        return jsonify(session_mod.fs_list(request.args.get("path")))

    @app.get("/api/fs/count")
    def fs_count():
        """一个目录里有多少张照片（递归）。文件夹浏览器按行懒问这个，
        所以列出目录本身不用等任何扫描。"""
        return jsonify(session_mod.fs_count(request.args.get("path")))

    # ---------------------------------------------------------- library state
    @app.get("/api/state")
    def state():
        lib, err = need_lib()
        if err:
            return err
        prog = lib.progress.snap()
        from . import embed as embed_mod
        emb_ok, emb_why = embed_mod.available()
        counts = lib.counts()
        return jsonify({
            "root": lib.root,
            "slug": paths.slug(lib.root),
            "work_dir": lib.work_dir,
            # catalog 的身份。前端用它当"上次看到第几张"的 key —— 删掉数据
            # 重新扫描以后照片 id 会从头分配，用根目录当 key 会把人送到一张
            # 毫无关系的照片上。
            "catalog_key": _catalog_key(lib),
            "read_only": bool(lib.read_only),
            "generation": sess.generation,
            "progress": prog,
            "counts": counts,
            # 该不该先看整页进度：服务端知道得比前端准。
            # 前端曾经用"analyzed < total"判断，可刚打开的库在扫描完成前
            # total 还是 0，于是整页进度被跳过、只剩左上角那条细线。
            "boot_needed": bool(prog.get("running") or
                                (counts["total"] and counts["analyzed"] < counts["total"])),
            "face_available": _faces_ok(),
            "embed": {
                "ok": emb_ok,
                "message": emb_why,
                "model_present": embed_mod.present(),
                "covered": lib.store.vector_count(config.EMBED_MODEL),
                "total": counts["total"],
            },
            "calibration": lib.store.get_meta("calibration"),
            "issue_summary": _issue_summary(lib),
            "labels": _labels(),
            "boot": _boot_block(lib, prog),
        })

    # ---------------------------------------------------------- models
    @app.post("/api/embed")
    def embed_start():
        """补算照片向量（幂等）。有了它，相似组才按"画面内容"分。"""
        lib, err = need_lib()
        if err:
            return err
        from . import embed as embed_mod
        ok, why = embed_mod.available()
        if not ok:
            return jsonify({"ok": False, "error": why,
                            "need_model": not embed_mod.present()})
        if lib.embedding():
            return jsonify({"ok": True, "started": False, "progress": lib.progress.snap()})
        return jsonify({"ok": True, "started": lib.start_embed(),
                        "progress": lib.progress.snap()})

    @app.get("/api/models")
    def models_status():
        from . import models as models_mod
        return jsonify(models_mod.status())

    @app.post("/api/models/fetch")
    def models_fetch():
        """Download a detector model on demand.

        Called automatically when a library opens and faces are unavailable,
        so "faces need a 3.6 MB download" turns into something that waits a few
        seconds rather than something the user has to act on.
        """
        from . import models as models_mod
        body = request.get_json(silent=True) or {}
        name = body.get("name", "face_landmarker.task")
        # faces.available() stats the file every time, so a finished download
        # takes effect on the next call with no cache to clear.
        return jsonify(models_mod.ensure(name))

    # ---------------------------------------------------------- settings
    @app.get("/api/settings")
    def settings_get():
        """The whole settings screen in one request: current values, the
        defaults to offer as "restore", and the named factors the UI shows as
        three-way switches rather than as numbers."""
        return jsonify({"settings": session_mod.get_settings(),
                        "defaults": dict(config.SETTINGS_DEFAULTS),
                        "density": dict(config.DENSITY_FACTOR),
                        "strictness": dict(config.STRICTNESS_FACTOR),
                        "trash_dir_name": config.TRASH_DIR_NAME})

    @app.post("/api/settings")
    def settings_post():
        b = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "settings": session_mod.save_settings(b)})

    @app.post("/api/cache/clear")
    def cache_clear():
        """Drop the generated thumbnails. Never touches a photo and never
        touches the catalog -- decisions and analysis survive, and previews are
        rebuilt on demand."""
        return jsonify({"ok": True, **session_mod.clear_thumb_cache()})

    @app.post("/api/alias")
    def alias():
        """Set (or clear) a library's display name. Does NOT touch the folder."""
        b = request.get_json(silent=True) or {}
        path = (b.get("path") or "").strip()
        if not path:
            return jsonify({"ok": False, "error": "缺少 path"}), 400
        if not session_mod.set_alias(path, b.get("alias") or ""):
            return jsonify({"ok": False, "error": "这个路径不在最近的列表里"}), 404
        return jsonify({"ok": True, "recent": session_mod.recent_libraries()})

    @app.post("/api/scan")
    def scan():
        lib, err = need_lib()
        if err:
            return err
        return jsonify({"started": lib.start(), "progress": lib.progress.snap()})

    @app.post("/api/cancel")
    def cancel():
        lib, err = need_lib()
        if err:
            return err
        lib.cancel()
        return jsonify({"ok": True})

    @app.post("/api/recompute")
    def recompute():
        lib, err = need_lib()
        if err:
            return err
        try:
            return jsonify({"ok": True, "result": lib.recompute()})
        finally:
            # recompute 是同步算完的，别把 progress 留在"正在分组"上 ——
            # 否则顶栏会一直显示一个 0/0 的进度条。
            lib.progress.update(phase="done", message="已重新分组")

    # ---------------------------------------------------------- images
    @app.get("/api/cover")
    def cover():
        """A small thumbnail of the first photo in a remembered library.

        The home screen shows one cover per project, and at that point NO library
        is open -- `/img/<id>/small` needs a live Library, so it cannot serve
        this. Instead the catalog is opened read-only, its first photo is taken,
        and the ordinary thumbnail cache does the rest: built once, cached on
        disk next to the catalog, served from there forever after.

        `root` is checked against the remembered list rather than trusted. This
        is a loopback server, but a query string should never be able to point
        it at an arbitrary directory and have it decode whatever is there.
        """
        root = request.args.get("root", "")
        if not root or root not in {r["path"] for r in session_mod.recent_libraries()}:
            return ("", 404)

        d = paths.catalog_dir(root)
        db = os.path.join(d, "catalog.db")
        if not os.path.exists(db):
            return ("", 404)
        try:
            con = sqlite3.connect("file:{}?mode=ro".format(db.replace("\\", "/")),
                                  uri=True, timeout=2)
            row = con.execute(
                "SELECT path, size, mtime FROM photos WHERE error IS NULL "
                "ORDER BY taken_ts IS NULL, taken_ts, id LIMIT 1").fetchone()
            con.close()
        except Exception:
            return ("", 404)
        if not row:
            return ("", 404)
        try:
            p = imageio.ThumbCache(d).get_or_build(
                row[0], row[1], row[2], config.THUMB_SMALL)
        except Exception:
            return ("", 404)
        return send_file(p, mimetype="image/jpeg", max_age=86400)

    @app.get("/img/<slug>/<int:pid>/<size>")
    def image(slug, pid, size):
        """small = list thumbnail, card = instant preview, full = the real thing.

        `<slug>` is the library's identity, and it is part of the URL for one
        reason: photo ids restart at 1 in every library. Without it, `/img/3/card`
        means "the third photo" forever and the browser happily serves the copy
        it cached for the *previous* project -- the left thumbnails then show one
        shoot while the big picture shows another. Measured, not theorised: with
        `Cache-Control: max-age=2592000` and a slug-less URL, every one of the
        first eight ids came back from cache with a different picture than the
        server's.

        A slug that no longer matches the open library is a 404 rather than a
        guess: a stale page should show a hole, never somebody else's photo.

        For a format the browser renders natively, `full` is the ORIGINAL file
        -- not a re-encode. Guopian is local-first: there is no bandwidth to
        save, and a 1600px preview scaled up to 400% is just a blurry photo.
        RAW and HEIC have to be transcoded once, and `full` gives the largest
        preview we can pull out of them.
        """
        lib, err = need_lib()
        if err:
            return err
        if slug != paths.slug(lib.root):
            return ("not found", 404)
        row = lib.store.conn.execute(
            "SELECT path, size, mtime, ext, width, height FROM photos WHERE id=?",
            (pid,)).fetchone()
        if row is None:
            return ("not found", 404)

        if size == "small":
            edge = config.THUMB_SMALL
        elif size in ("card", "zoom"):
            edge = config.THUMB_CARD
        elif size == "full":
            edge = config.FULL_EDGE
        else:
            return ("bad size", 400)

        direct = (row["ext"] in config.BROWSER_DISPLAYABLE
                  and (row["size"] or 0) <= config.MAX_DIRECT_BYTES)

        if size == "full" and direct:
            try:
                return send_file(row["path"], conditional=True, max_age=3600)
            except Exception:
                pass  # fall through to a generated preview

        try:
            p = lib.thumbs.get_or_build(row["path"], row["size"], row["mtime"], edge)
            return send_file(p, conditional=True, max_age=86400 * 30)
        except Exception as e:
            return ("cannot render: {}".format(e), 500)

    @app.get("/api/media/<int:pid>")
    def media_info(pid):
        """What the UI needs to label zoom levels honestly."""
        lib, err = need_lib()
        if err:
            return err
        row = lib.store.conn.execute(
            "SELECT ext, size, width, height FROM photos WHERE id=?", (pid,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        direct = (row["ext"] in config.BROWSER_DISPLAYABLE
                  and (row["size"] or 0) <= config.MAX_DIRECT_BYTES)
        return jsonify({
            "width": row["width"], "height": row["height"],
            "ext": row["ext"],
            "full_is_original": bool(direct),
            "full_edge": None if direct else config.FULL_EDGE,
        })

    # ---------------------------------------------------------- queue
    @app.get("/api/queue")
    def queue():
        lib, err = need_lib()
        if err:
            return err
        flt = request.args.get("filter", "all")
        sort = request.args.get("sort", "time")
        ids = _select_ids(lib, flt, sort)
        cards = []
        for pid in ids:
            row = lib.store.conn.execute(
                """SELECT p.id, p.name, p.rel_path, p.taken_at, p.taken_ts,
                          p.camera, p.lens, p.width, p.height,
                          p.iso, p.shutter, p.aperture, p.focal,
                          p.pct_high, p.pct_low, p.lap_var_mp, p.noise, p.face_count,
                          p.group_id, p.group_size, p.group_rank, p.group_score,
                          p.suggest, p.suggest_reason, p.suggest_conf, p.decision, p.error
                   FROM photos p WHERE p.id=?""", (pid,)).fetchone()
            if row is None:
                continue
            card = dict(row)
            card["issues"] = [_row_to_card(r) for r in lib.store.conn.execute(
                "SELECT kind, severity, confidence, face_idx, label_zh, detail, evidence "
                "FROM issues WHERE photo_id=? ORDER BY CASE severity "
                "WHEN 'fatal' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 "
                "WHEN 'low' THEN 3 ELSE 4 END", (pid,)).fetchall()]
            cards.append(card)

        # A colour index per similar group.
        #
        # This used to be group_id % 8 computed in the browser, which cannot
        # work: this library has 66 groups, so with 8 colours two unrelated
        # groups always share one and the colour stops telling them apart.
        # The index is a group's ORDINAL among the multi-photo groups -- only
        # 16 of those -- not a hash of its id.
        #
        # Computed here rather than in the list because the list is filtered:
        # ranking groups within the current view would make a group change
        # colour when the user switched filters.
        palette = lib.store.conn.execute(
            "SELECT DISTINCT group_id FROM photos WHERE group_size > 1 "
            "AND group_id IS NOT NULL ORDER BY group_id").fetchall()
        colours = {r[0]: i % GROUP_PALETTE for i, r in enumerate(palette)}
        for card in cards:
            card["group_color"] = colours.get(card.get("group_id"))

        return jsonify({"filter": flt, "sort": sort, "total": len(cards),
                        "items": cards, "palette": GROUP_PALETTE})

    @app.get("/api/photo/<int:pid>")
    def photo(pid):
        lib, err = need_lib()
        if err:
            return err
        row = lib.store.conn.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        d = dict(row)
        d.pop("phash", None)
        d["issues"] = [_row_to_card(r) for r in lib.store.conn.execute(
            "SELECT kind, severity, confidence, face_idx, label_zh, label_en, detail, evidence "
            "FROM issues WHERE photo_id=? ORDER BY CASE severity "
            "WHEN 'fatal' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 "
            "WHEN 'low' THEN 3 ELSE 4 END", (pid,)).fetchall()]
        fcs = []
        for r in lib.store.conn.execute("SELECT * FROM faces WHERE photo_id=? ORDER BY idx", (pid,)):
            f = dict(r)
            if f.get("landmarks"):
                try:
                    f["landmarks"] = json.loads(f["landmarks"])
                except Exception:
                    f["landmarks"] = None
            fcs.append(f)
        d["faces"] = fcs
        nb = lib.store.conn.execute(
            "SELECT id FROM photos WHERE group_id=? AND id<>? ORDER BY group_rank LIMIT 12",
            (d.get("group_id"), pid)).fetchall() if d.get("group_id") else []
        d["group_mates"] = [r["id"] for r in nb]
        return jsonify(d)

    # ---------------------------------------------------------- decisions
    @app.post("/api/decide")
    def decide():
        lib, err = need_lib()
        if err:
            return err
        body = request.get_json(force=True) or {}
        action = body.get("action")
        if action not in config.DECISIONS and action != config.CLEAR:
            return jsonify({"ok": False, "error": "bad action"}), 400
        ids = body.get("ids") or ([body["id"]] if body.get("id") else [])
        batch = body.get("batch")
        prev = []
        for pid in ids:
            prev.append({"id": pid, "prev": lib.store.set_decision(int(pid), action, batch)})
        return jsonify({"ok": True, "action": action, "count": len(ids), "prev": prev})

    @app.post("/api/reset")
    def reset_all():
        """清空这个项目的全部决策。

        需要 confirm: true —— 和归档一样，动全库的动作要用户明确点两次。
        记成一个批次，所以整批可以撤回。
        """
        lib, err = need_lib()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        if not body.get("confirm"):
            return jsonify({"ok": False,
                            "error": "需要确认：这会清掉这个项目的全部决策"}), 409
        from . import decisions as dec_mod
        # 方案 B：连文件一起搬回根目录，那才叫「回到最开始」。
        res = dec_mod.restore_all(lib.store)
        if not res.get("ok"):
            return jsonify(res), 409
        return jsonify({"ok": True, "result": res})

    @app.post("/api/undo")
    def undo():
        lib, err = need_lib()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        batch = body.get("batch")
        if batch:
            # A grid commit decides a whole group at once, so it is undone as
            # one. Reverting only the last row would leave a state the user
            # never chose.
            return jsonify({"ok": True, "batch": batch,
                            "result": lib.store.undo_batch(batch)})
        res = lib.store.undo_last()
        return jsonify({"ok": res is not None, "result": res})

    @app.post("/api/bulk")
    def bulk():
        lib, err = need_lib()
        if err:
            return err
        body = request.get_json(force=True) or {}
        scope = body.get("scope", "reject")
        gid = body.get("group_id")
        con = lib.store.conn
        if scope == "group" and gid:
            rows = con.execute(
                "SELECT id, group_rank FROM photos WHERE group_id=? AND (decision IS NULL OR decision='')",
                (gid,)).fetchall()
            n = 0
            for r in rows:
                lib.store.set_decision(r["id"], "keep" if r["group_rank"] == 1 else "reject", "bulk-group")
                n += 1
            return jsonify({"ok": True, "count": n})

        want = "reject" if scope == "reject" else "keep"
        rows = con.execute(
            "SELECT id FROM photos WHERE suggest=? AND (decision IS NULL OR decision='')",
            (want,)).fetchall()
        for r in rows:
            lib.store.set_decision(r["id"], want, "bulk")
        return jsonify({"ok": True, "count": len(rows)})

    # ---------------------------------------------------------- groups
    @app.get("/api/groups")
    def groups():
        lib, err = need_lib()
        if err:
            return err
        rows = lib.store.conn.execute(
            """SELECT g.id, g.size, g.best_photo_id, p.name AS best_name
               FROM groups g LEFT JOIN photos p ON p.id=g.best_photo_id
               WHERE g.size>1 ORDER BY g.size DESC, g.id LIMIT 500""").fetchall()
        return jsonify({"items": [dict(r) for r in rows]})

    # ---------------------------------------------------------- apply
    @app.get("/api/apply/preview")
    def apply_preview():
        lib, err = need_lib()
        if err:
            return err
        mode = request.args.get("mode", decisions.MODE_QUARANTINE)
        pv = decisions.preview(lib.store, mode)
        # Undo rides along with the plan. The one moment a user wants to take
        # an apply back is the moment they are looking at the apply screen --
        # making them find a separate history view is how an undo button goes
        # unused and a feature gets called "missing" while it exists.
        pv["history"] = [h for h in decisions.history(lib.store) if not h.get("undone")][:3]
        return jsonify(pv)

    @app.post("/api/apply")
    def apply_now():
        lib, err = need_lib()
        if err:
            return err
        body = request.get_json(force=True) or {}
        mode = body.get("mode", decisions.MODE_QUARANTINE)
        confirm = bool(body.get("confirm"))
        pv = decisions.preview(lib.store, mode)
        if not confirm:
            return jsonify({"ok": False, "needs_confirm": True, "preview": pv}), 409
        return jsonify(decisions.apply(lib.store, mode))

    @app.post("/api/rollback")
    def rollback():
        lib, err = need_lib()
        if err:
            return err
        body = request.get_json(force=True) or {}
        return jsonify(decisions.rollback(lib.store, body.get("batch", "")))

    @app.get("/api/applies")
    def applies():
        lib, err = need_lib()
        if err:
            return err
        return jsonify({"items": decisions.history(lib.store)})

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "generation": sess.generation,
                        "library": sess.root is not None})

    # ---------------------------------------------------------- teardown
    @app.teardown_request
    def _release_db(exc=None):
        # A request that raised must not leave an open write transaction
        # behind: in WAL mode that would block every other thread instantly.
        lib = sess.require()
        if lib is not None:
            lib.store.release()

    app.config["GUOPIAN_SESSION"] = sess
    return app


# ------------------------------------------------------------------ helpers

def _version() -> str:
    from . import __version__

    return __version__


def _platform() -> str:
    import sys

    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def _labels() -> dict:
    """The user-facing words for the three decisions, sent to the UI.

    config.DECISION_LABELS is the ONLY place these words are written down. They
    used to be duplicated in app.js (a second LABEL object) and again as bare
    text in index.html, which meant renaming a decision took four edits and
    missing one produced no error at all -- just a screen with two different
    words for the same thing. The frontend now fills them in from here.
    """
    return {"decisions": dict(config.DECISION_LABELS),
            "verdict": dict(config.DECISION_VERDICT),
            "owned": dict(config.DECISION_OWNED)}


def _faces_ok() -> dict:
    from . import faces as faces_mod

    ok, msg = faces_mod.available()
    return {"ok": ok, "message": msg}


def _writable(folder: str) -> bool:
    """这个文件夹我们能不能往里写（决定要不要自动只读打开）。

    用"真建一个临时文件再删掉"来判断，而不是 os.access：Windows 上访问控制
    列表和只读介质都可能让 access 说可以、实际写入却失败。
    """
    probe = os.path.join(folder, ".guopian_write_test")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _catalog_key(lib) -> str:
    """这个 catalog 的身份（数据库文件的创建时间）。

    前端拿它当 localStorage 的 key。照片 id 在新建的 catalog 里从头分配，
    所以"删掉数据重新扫描"以后，用根目录当 key 会把上次记下的 id 套到一张
    完全不相干的照片上 —— 用户看到的就是"它自己选中了一张我没选的图"。
    """
    try:
        st = os.stat(os.path.join(lib.work_dir, "catalog.db"))
        return "{}-{}".format(int(st.st_ctime), int(st.st_size))
    except OSError:
        return "0"


def _boot_block(lib, prog: dict) -> dict:
    """首屏（新文件夹分析中）用的数据：进度 + 分类计数。

    分类来自 pipeline 边分析边统计的 buckets。口径和最终判定不完全一致
    （开头还没有分布可标定，只能按绝对门槛分类），所以它只用来"看着有东西
    在发生"；真正的分类以分析结束后的 issue_summary 为准。
    """
    from . import analyze as analyze_mod

    buckets = prog.get("buckets") or {}
    rows = []
    for key, n in buckets.items():
        if not n:
            continue
        if key == "face":
            rows.append({"key": key, "label": "有人脸", "count": n, "order": 0})
        elif key == "no_face":
            rows.append({"key": key, "label": "没人脸", "count": n, "order": 1})
        elif key.startswith("issue:"):
            kind = key.split(":", 1)[1]
            rows.append({"key": key, "label": analyze_mod.issue_label(kind),
                         "count": n, "order": 2})
    rows.sort(key=lambda r: (r["order"], -r["count"]))
    counts = lib.counts()
    return {
        "rows": rows,
        "analyzed": counts.get("analyzed", 0),
        "total": counts.get("total", 0),
        "active": bool(prog.get("running")),
    }


def _issue_summary(lib) -> list[dict]:
    """Every issue kind present in the library, for the triage chips.

    Deliberately NOT filtered by severity or by decision state.

    Severity: the chips are a *filter* list, not a "worst problems" list.
    "把视线没看镜头的给我看一遍" is a perfectly reasonable thing to ask even
    though looking away is only an info-level hint, and hiding the low/info
    kinds made them impossible to select at all.

    Decision state: the `issue:<kind>` filter does not exclude already-decided
    photos, so a count that did exclude them would disagree with what clicking
    the chip actually returns.
    """
    rows = lib.store.conn.execute(
        """SELECT i.kind, i.label_zh,
                  COUNT(DISTINCT i.photo_id) n,
                  MIN(CASE i.severity WHEN 'fatal'  THEN 0
                                      WHEN 'high'   THEN 1
                                      WHEN 'medium' THEN 2
                                      WHEN 'low'    THEN 3
                                      ELSE 4 END) sev
           FROM issues i
           GROUP BY i.kind
           ORDER BY sev, n DESC""").fetchall()
    return [dict(r) for r in rows]


# Distinct colours available to the similar-group view. Must match the number
# of .listItem.gN rules in style.css -- they are two halves of one contract.
GROUP_PALETTE = 16


def _select_ids(lib, flt: str, sort: str) -> list[int]:
    con = lib.store.conn
    where, params = [], []
    if flt == "pending":
        where.append("(p.decision IS NULL OR p.decision='')")
    elif flt == "keep":
        where.append("p.decision='keep'")
    elif flt == "reject":
        where.append("p.decision='reject'")
    elif flt == "mark":
        where.append("p.decision='mark'")
    elif flt == "issues":
        where.append("EXISTS (SELECT 1 FROM issues i WHERE i.photo_id=p.id AND i.severity IN ('fatal','high'))")
    elif flt == "faces":
        where.append("p.face_count > 0")
    elif flt.startswith("issue:"):
        where.append("EXISTS (SELECT 1 FROM issues i WHERE i.photo_id=p.id AND i.kind=?)")
        params.append(flt.split(":", 1)[1])
    elif flt.startswith("group:"):
        where.append("p.group_id = ?")
        params.append(int(flt.split(":", 1)[1]))
    elif flt == "groups":
        where.append("p.group_size > 1")
    elif flt.startswith("camera:"):
        where.append("p.camera = ?")
        params.append(flt.split(":", 1)[1])

    order = {
        "time": "p.taken_ts IS NULL, p.taken_ts, p.path",
        "name": "p.name",
        "size": "p.size DESC",
        "sharp": "p.lap_var_mp DESC",
        "suggest": "CASE p.suggest WHEN 'reject' THEN 0 WHEN 'maybe' THEN 1 ELSE 2 END, p.taken_ts",
        "group": "p.group_id, p.group_rank",
    }.get(sort, "p.taken_ts IS NULL, p.taken_ts, p.path")

    sql = "SELECT p.id FROM photos p"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + order
    return [r["id"] for r in con.execute(sql, params).fetchall()]


def serve(sess: Session, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = True, window: bool = True,
          dev: bool = False, devtools: bool = False) -> None:
    """Run the server, and present a window to the user.

    Preference order:
      1. a Chromium "app mode" window -- chromeless, own taskbar entry
      2. the user's default browser

    Launching (1) is best-effort and *verified*: if nothing fetches the page
    within a few seconds we fall back, because a windowed app that silently
    shows nothing is far worse than a tab the user did not expect.

    With dev=True we do the opposite on purpose: a normal browser tab (so F12
    opens DevTools the usual way), no asset caching, and the Werkzeug reloader
    so Python edits restart the server by themselves.
    """
    app = create_app(sess, open_browser, port, dev=dev)
    url = "http://{}:{}".format(host, port)
    # 启动时若已经打开了某个库（`guopian.exe "D:\Photos"`），窗口就该直接开在
    # 它的项目地址上。否则地址栏写着首页、屏幕上是项目，一刷新行为说不清。
    start = "/"
    try:
        if sess.lib is not None:
            start = "/p/" + paths.slug(sess.lib.root)
    except Exception:
        start = "/"
    if start != "/":
        url = url + start

    print("\n  过片 Guopian  ->  {}".format(url))
    if dev:
        print("  开发模式：改动 web/ 会自动刷新页面；改动 guopian/ 会自动重启服务")
        print("  在浏览器里按 F12 打开 DevTools（元素检查、断点、Network 都能用）")
    print("  全部本地处理，不会上传任何照片。按 Ctrl+C 退出。\n")

    if open_browser and not dev:
        if _try_app_window(url, port, devtools=devtools):
            paths_log("app window confirmed")
        else:
            import webbrowser

            paths_log("app window not confirmed; opening the default browser")
            webbrowser.open(url)
    elif open_browser and dev:
        # With the reloader, only the *child* process actually serves. Opening
        # from the parent would race the child and land on a refused port, and
        # opening from both would give the user two tabs.
        import threading
        import webbrowser

        if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            t = threading.Timer(0.8, lambda: webbrowser.open(url))
            t.daemon = True
            t.start()

    try:
        app.run(host=host, port=port, debug=dev, threaded=True,
                use_reloader=dev, use_debugger=dev)
    except TypeError:
        app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


def _try_app_window(url: str, port: int, timeout: float = 8.0,
                    devtools: bool = False) -> bool:
    import time

    from . import window as window_mod

    _WINDOW_SEEN["pending"] = True
    _WINDOW_SEEN["seen"] = False

    if not window_mod.open_app_window(url + "?guopian_window=1", port,
                                      devtools=devtools):
        return False

    # Poll our own server: a real window loads the page, which is the only
    # signal we can trust.
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _WINDOW_SEEN["seen"]:
            return True
        time.sleep(0.25)

    window_mod.close_windows(wait=0.5)
    return False


def paths_log(msg: str) -> None:
    try:
        from . import paths

        paths.log(msg)
    except Exception:
        pass
