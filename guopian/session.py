"""One running Guopian session: the currently open photo library, plus the
ability to switch to a different folder without restarting the program.

The old design bound a Library to the Flask app at startup, which forced the
folder picker to happen *before* any window existed. A desktop app should show
itself first and let you browse inside it, so the library is now swappable.
"""

from __future__ import annotations

import json
import os
import shutil
import string
import threading
import time

from . import config, paths
from .pipeline import Library

PREFS = "prefs.json"


# ------------------------------------------------------------------ prefs

def _prefs_path() -> str:
    return os.path.join(paths.prefs_dir(), PREFS)


def load_prefs() -> dict:
    try:
        with open(_prefs_path(), encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_prefs(p: dict) -> None:
    try:
        with open(_prefs_path(), "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
    except Exception as e:
        paths.log("could not save prefs: {}".format(e))


def recent_libraries() -> list[dict]:
    """Recently opened folders that still exist, newest first."""
    p = load_prefs()
    out, seen = [], set()
    for entry in p.get("recent", []):
        path = entry.get("path") if isinstance(entry, dict) else entry
        if not path or path in seen or not os.path.isdir(path):
            continue
        seen.add(path)
        real = os.path.basename(path.rstrip("\\/")) or path
        alias = (entry.get("alias") or "").strip() if isinstance(entry, dict) else ""
        rec = {"path": path, "name": alias or real, "real_name": real,
               # The same stable id the catalog directory uses: folder name plus
               # a hash of the path. It is what goes in the URL, so it must not
               # change when someone renames the alias.
               "slug": paths.slug(path),
               "alias": alias or None,
               "at": entry.get("at") if isinstance(entry, dict) else None}
        rec.update(_catalog_stats(path))
        out.append(rec)
    return out


def set_alias(path: str, alias: str) -> bool:
    """Give a remembered library a display name.

    Deliberately an ALIAS, not a rename: the folder on disk keeps its name and
    nothing about the photo directory is touched. Guopian's whole safety story is
    that it never rearranges a user's files, and renaming a directory out from
    under a catalog -- whose key is derived from that path -- would invalidate
    every thumbnail and decision stored against it.
    """
    p = load_prefs()
    hit = False
    for r in p.get("recent", []):
        if isinstance(r, dict) and r.get("path") == path:
            alias = (alias or "").strip()
            if alias:
                r["alias"] = alias
            else:
                r.pop("alias", None)          # empty clears it back to the folder name
            hit = True
    if hit:
        save_prefs(p)
    return hit



# ------------------------------------------------------------------ settings

def session_from_settings(**kw) -> "Session":
    """A Session whose defaults come from the settings the user saved.

    read_only and workers are constructor defaults, so they have to be read
    before the Session exists rather than applied to it afterwards.
    """
    s = get_settings()
    ro = bool(s.get("read_only"))
    w = int(s.get("workers") or 0) or None
    return Session(read_only=ro, workers=w, **kw)


def get_settings() -> dict:
    """Current settings, defaults filled in for anything unset.

    Merged rather than replaced, so a prefs.json written by an older version --
    or one a user hand-edited and got slightly wrong -- still comes back as a
    complete, valid dict instead of a half-populated one.
    """
    stored = load_prefs().get("settings") or {}
    out = dict(config.SETTINGS_DEFAULTS)
    out.update({k: v for k, v in stored.items() if k in config.SETTINGS_DEFAULTS})
    return out


def save_settings(patch: dict) -> dict:
    """Merge a patch, persist it, and make it take effect immediately.

    Unknown keys are dropped rather than stored: a typo in the UI would
    otherwise accumulate junk in prefs.json that never does anything and is
    impossible to notice.
    """
    before = get_settings()
    current = get_settings()
    for k in config.SETTINGS_DEFAULTS:
        if k in patch and patch[k] is not None:
            current[k] = patch[k]
    p = load_prefs()
    p["settings"] = current
    save_prefs(p)

    # Renaming a decision folder has to move what is already filed into it,
    # otherwise the same decision ends up split across two folders.
    renames = []
    for key in ("dir_keep", "dir_reject", "dir_mark"):
        old, new = (before.get(key) or "").strip(), (current.get(key) or "").strip()
        if old and new and old != new:
            renames.append((key, old, new))

    config.apply_settings(current)
    if renames:
        current["_renamed"] = rename_decision_folders(renames)
    return current



# ------------------------------------------------------- folder-name changes

def rename_decision_folders(renames: list[tuple[str, str, str]]) -> list[dict]:
    """Rename already-filed decision folders and keep the catalogs in step.

    Without this, changing the folder name in settings splits one decision into
    two folders on disk: the 74 photos already in `过` stay there, and the next
    archive creates `保留`. The setting would then be a way to lose track of
    your own photos.

    `renames` is a list of (setting_key, old_name, new_name). Every remembered
    library is checked, not just the open one, because the setting is global.

    Nothing is ever merged or deleted. If the destination already exists the
    rename is skipped and reported, because silently merging two folders is the
    one outcome that cannot be undone.
    """
    out: list[dict] = []
    if not renames:
        return out

    for rec in recent_libraries():
        root = rec.get("path") or ""
        if not root or not os.path.isdir(root):
            continue

        db = os.path.join(paths.catalog_dir(root), "catalog.db")
        con = None
        if os.path.exists(db):
            try:
                import sqlite3
                con = sqlite3.connect(db)
            except Exception:
                con = None

        for key, old, new in renames:
            if not old or not new or old == new:
                continue
            src = os.path.join(root, old)
            dst = os.path.join(root, new)
            item = {"root": root, "key": key, "old": old, "new": new}
            if not os.path.isdir(src):
                continue                      # that library never used this folder
            if os.path.exists(dst):
                item["error"] = "目标文件夹已存在，跳过（不合并）"
                out.append(item)
                continue
            try:
                os.rename(src, dst)
            except OSError as e:
                item["error"] = str(e)
                out.append(item)
                continue

            moved = 0
            if con is not None:
                try:
                    rows = con.execute(
                        "SELECT id, rel_path, path FROM photos WHERE rel_path LIKE ? "
                        "OR path LIKE ?",
                        (old + os.sep + "%", old + os.sep + "%")).fetchall()
                    pre_rel, pre_abs = old + os.sep, os.path.join(root, old) + os.sep
                    new_rel, new_abs = new + os.sep, os.path.join(root, new) + os.sep
                    for pid, rel, absolute in rows:
                        con.execute(
                            "UPDATE photos SET rel_path=?, path=? WHERE id=?",
                            ((new_rel + rel[len(pre_rel):]) if rel and rel.startswith(pre_rel) else rel,
                             (new_abs + absolute[len(pre_abs):]) if absolute and absolute.startswith(pre_abs) else absolute,
                             pid))
                        moved += 1
                    con.commit()
                except Exception as e:
                    item["error"] = "文件夹改名了，但 catalog 更新失败：{}".format(e)

            item["photos"] = moved
            out.append(item)

        if con is not None:
            try:
                con.close()
            except Exception:
                pass

    return out

def clear_thumb_cache() -> dict:
    """Delete every remembered library's thumbnail cache.

    Only the generated cache, never a photo and never the catalog itself --
    decisions and analysis survive, and the thumbnails are rebuilt on demand.
    """
    import shutil

    freed = 0
    dirs = 0
    for r in recent_libraries():
        d = os.path.join(paths.catalog_dir(r["path"]), "thumbs")
        if not os.path.isdir(d):
            continue
        try:
            for dirpath, _dirnames, filenames in os.walk(d):
                for f in filenames:
                    try:
                        freed += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
            shutil.rmtree(d, ignore_errors=True)
            dirs += 1
        except Exception:
            pass
    return {"dirs": dirs, "bytes": freed}

def remember(path: str) -> None:
    p = load_prefs()
    entry = {"path": path, "at": time.time()}
    rest = [r for r in p.get("recent", [])
            if (r.get("path") if isinstance(r, dict) else r) != path]
    p["recent"] = ([entry] + rest)[:12]
    p["last_folder"] = path
    save_prefs(p)


def forget(path: str, delete_data: bool = False, live_lib=None) -> dict:
    """Drop a library from the home list, optionally deleting its data.

    "从列表移除" and "删掉这个项目" 是两件事，以前只有前者，而且名字叫 ✕，
    看起来像后者 —— 用户点了 ✕ 以为数据没了，重新打开却发现"秒开、还带着
    上次的分析结果"，自然会怀疑是不是缓存没清。

    所以这里拆成两个动作：
      delete_data=False  只从最近列表拿掉，catalog（分析结果 + 缩略图）保留，
                         下次打开仍然秒开。
      delete_data=True   连 catalog 一起删掉。下次打开会重新扫描、重新分析，
                         也就是用户说的"删掉全部数据"。

    Windows 上目录里有打开的 SQLite 句柄就删不掉，所以删之前必须先把连接放掉：
    调用方传进来的 live_lib（当前打开的那个）、后台挂着的分析线程，都先关。
    rmtree 之后还要确认目录真的没了 —— 否则界面会说"已删除"而数据还在，
    那比不删更糟。
    """
    freed = 0
    removed = True
    if delete_data:
        catalog = paths.catalog_dir(path)

        if live_lib is not None:
            try:
                live_lib.cancel()
                live_lib.store.close()
            except Exception:
                pass

        for key, lib in list(_DETACHED.items()):
            try:
                if os.path.abspath(getattr(lib, "root", "")) == os.path.abspath(path):
                    lib.cancel()
                    lib.store.close()
                    _DETACHED.pop(key, None)
            except Exception:
                _DETACHED.pop(key, None)

        if os.path.isdir(catalog):
            try:
                freed = _dir_size(catalog)
            except OSError:
                freed = 0
            _rmtree_retry(catalog)
            removed = not os.path.exists(catalog)

    p = load_prefs()
    p["recent"] = [r for r in p.get("recent", [])
                   if (r.get("path") if isinstance(r, dict) else r) != path]
    if p.get("last_folder") == path:
        p["last_folder"] = None
    save_prefs(p)
    return {"freed": freed, "removed": removed}


def _rmtree_retry(path: str, attempts: int = 4) -> None:
    """刚关掉的 sqlite 句柄在 Windows 上要几毫秒才真正释放，删早了会 PermissionError。"""
    import gc

    for i in range(attempts):
        gc.collect()
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.12 * (i + 1))
    shutil.rmtree(path, ignore_errors=True)


def catalog_size(path: str) -> dict:
    """这个项目的分析数据占了多大（数据库 + 缩略图）。"""
    d = paths.catalog_dir(path)
    if not os.path.isdir(d):
        return {"bytes": 0, "exists": False}
    try:
        return {"bytes": _dir_size(d), "exists": True}
    except OSError:
        return {"bytes": 0, "exists": True}


def _dir_size(root: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _catalog_stats(photo_root: str) -> dict:
    """How far along is this library, and what is in it? Read straight from its
    catalog db, read-only. The home screen shows this without opening the
    library, so it must never take a write lock or build anything."""
    import sqlite3

    empty = {"analyzed": 0, "total": 0, "decided": 0, "has_catalog": False,
             "camera": None, "lens": None, "first_ts": None, "last_ts": None,
             "issue_photos": 0}
    d = paths.catalog_dir(photo_root)
    db = os.path.join(d, "catalog.db")
    if not os.path.exists(db):
        return empty
    try:
        con = sqlite3.connect("file:{}?mode=ro".format(db.replace("\\", "/")), uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        total = con.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        analyzed = con.execute(
            "SELECT COUNT(*) FROM photos WHERE analysis_version>=?",
            (config.ANALYSIS_VERSION,)).fetchone()[0]
        decided = con.execute(
            "SELECT COUNT(*) FROM photos WHERE decision IS NOT NULL AND decision<>''"
        ).fetchone()[0]
        # The most common body and lens, not the first one seen: a library can
        # hold two bodies, and the album is better described by the one that
        # actually shot most of it.
        def top(col):
            r = con.execute(
                "SELECT {} v, COUNT(*) n FROM photos WHERE {} IS NOT NULL AND {}<>'' "
                "GROUP BY v ORDER BY n DESC LIMIT 1".format(col, col, col)).fetchone()
            return r["v"] if r else None
        span = con.execute(
            "SELECT MIN(taken_ts) a, MAX(taken_ts) b FROM photos WHERE taken_ts IS NOT NULL"
        ).fetchone()
        try:
            issue_photos = con.execute(
                "SELECT COUNT(DISTINCT photo_id) FROM issues").fetchone()[0]
        except sqlite3.Error:
            issue_photos = 0        # no analysis yet, or an older schema
        # Every query must run BEFORE the connection is closed. Calling top()
        # inside the returned dict literal evaluated it after con.close(), which
        # threw "Cannot operate on a closed database" -- and the bare except below
        # turned that into a project that looked empty.
        camera, lens = top("camera"), top("lens")
        first_ts = span["a"] if span else None
        last_ts = span["b"] if span else None
        con.close()
        return {"analyzed": analyzed, "total": total, "decided": decided,
                "has_catalog": True, "camera": camera, "lens": lens,
                "first_ts": first_ts, "last_ts": last_ts,
                "issue_photos": issue_photos}
    except Exception:
        import traceback
        paths.log("catalog stats failed for {}:\n{}".format(
            photo_root, traceback.format_exc()))
        return dict(empty, has_catalog=True)


# ------------------------------------------------------------------ filesystem

def _photo_count(path: str, cap: int = 5000) -> int:
    """Photos in a folder, counting subfolders.

    This counted only the files sitting directly in `path`. That was right until
    archiving arrived: applying decisions files everything into 过 / 不过 /
    精选, so a library the user just finished sorting showed "0 张" in the folder
    browser -- the one number they would look at to check it worked.

    The quarantine folder is skipped, so the count reflects what you would
    actually open, not what has already been set aside.

    This walks the tree, so it is NEVER called inline while listing a folder:
    listing D:\\ used to walk D:\\ *and* every child (SteamLibrary alone was
    154 ms warm, seconds cold), which is why clicking a drive looked like it was
    scanning. See photo_count_cached / fs_count.
    """
    n = 0
    # Only the quarantine folder. The three decision folders ARE the photos --
    # skipping them too made a freshly-sorted library count as zero.
    skip = {config.TRASH_DIR_NAME}
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames
                       if d not in skip and not d.startswith(".")]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in config.SUPPORTED_EXT:
                n += 1
                if n >= cap:
                    return n
    return n


_COUNT_CACHE: dict[str, tuple[float, int]] = {}
_COUNT_CACHE_TTL = 300.0          # 5 分钟：够挡住来回点，又不至于看不到新导入的照片
_COUNT_CACHE_LOCK = threading.Lock()


def photo_count_cached(path: str) -> int:
    """_photo_count with a short cache. Called once per folder row, on demand."""
    now = time.time()
    with _COUNT_CACHE_LOCK:
        hit = _COUNT_CACHE.get(path)
        if hit and now - hit[0] < _COUNT_CACHE_TTL:
            return hit[1]
    try:
        n = _photo_count(path)
    except OSError:
        n = 0
    with _COUNT_CACHE_LOCK:
        _COUNT_CACHE[path] = (now, n)
        if len(_COUNT_CACHE) > 4000:          # 别让缓存自己变成内存泄漏
            for k in list(_COUNT_CACHE)[:1000]:
                _COUNT_CACHE.pop(k, None)
    return n


def fs_count(path: str | None) -> dict:
    """How many photos are in this folder (recursive). Asked lazily, per row."""
    if not path:
        return {"path": "", "photos": 0}
    p = os.path.abspath(os.path.expanduser(path))
    return {"path": p, "photos": photo_count_cached(p)}


# 这些目录要么是系统的，要么是回收站/缓存：列出来只会让人误点
_SKIP_DIRS = {
    "$RECYCLE.BIN", "$Recycle.Bin", "System Volume Information", "$WinREAgent",
    "Recovery", "Config.Msi", "node_modules", "__pycache__",
}


def fs_list_fast(path: str | None, with_counts: bool = False) -> dict:
    """Directory listing for the in-app folder browser.

    Deliberately cheap: names and paths only. Counting photos is a recursive
    walk, so it is asked for separately per row (fs_count) and filled in as the
    answers arrive. `with_counts=True` is kept for tests and for callers that
    really do want one blocking pass.
    """
    if not path:
        return fs_list_fast(os.path.expanduser("~"), with_counts)

    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        path = os.path.dirname(path)

    result: dict = {
        "path": path,
        "name": os.path.basename(path.rstrip("\\/")) or path,
        "parent": None,
        "photos": None if not with_counts else 0,
        "dirs": [],
        "error": None,
    }

    parent = os.path.dirname(path.rstrip("\\/"))
    if parent and parent != path and os.path.isdir(parent):
        result["parent"] = parent

    t0 = time.time()
    try:
        entries = list(os.scandir(path))
    except PermissionError:
        result["error"] = "没有权限读取这个文件夹"
        return result
    except OSError as e:
        result["error"] = str(e)
        return result

    dirs = []
    for e in entries:
        try:
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if e.name.startswith(".") or e.name in _SKIP_DIRS:
            continue
        if e.name == config.TRASH_DIR_NAME:
            continue
        dirs.append(e.name)

    if with_counts:
        result["photos"] = photo_count_cached(path)

    detailed = []
    for name in sorted(dirs, key=str.lower):
        full = os.path.join(path, name)
        detailed.append({"name": name, "path": full,
                         "photos": photo_count_cached(full) if with_counts else None})
    if with_counts:
        # folders that actually contain photos float to the top
        detailed.sort(key=lambda d: (0 if d["photos"] else 1, d["name"].lower()))
    result["dirs"] = detailed
    result["list_ms"] = round((time.time() - t0) * 1000, 1)
    return result


def fs_roots() -> list[dict]:
    """Handy starting points: every drive on Windows, the usual mounts elsewhere."""
    out: list[dict] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            d = "{}:\\".format(letter)
            if os.path.exists(d):
                label = ""
                try:
                    import ctypes

                    buf = ctypes.create_unicode_buffer(261)
                    if ctypes.windll.kernel32.GetVolumeInformationW(
                            d, buf, 260, None, None, None, None, 0):
                        label = buf.value
                except Exception:
                    pass
                out.append({"name": "{}:".format(letter), "label": label, "path": d})
        for name, sub in (("图片", "Pictures"), ("桌面", "Desktop"), ("下载", "Downloads")):
            p = os.path.join(os.path.expanduser("~"), sub)
            if os.path.isdir(p):
                out.append({"name": name, "label": "", "path": p})
    else:
        out.append({"name": "主目录", "label": "", "path": os.path.expanduser("~")})
        for p in ("/Volumes", "/media", "/mnt", "/"):
            if os.path.isdir(p):
                out.append({"name": p, "label": "", "path": p})
    return out


def fs_list(path: str | None, with_counts: bool = False) -> dict:
    """Directory listing for the in-app folder browser.

    这是便宜的那一个：只 scandir，不数照片（数照片是递归走树，见 fs_count）。
    曾经它内部递归数照片，点一下盘符就要把整个盘连子目录数一遍，看着像在扫描。
    """
    return fs_list_fast(path, with_counts)


# ------------------------------------------------------------------ session

# 关掉一个库以后，分析任务不跟着停 —— 用户回首页了，但扫描还在跑。
# 放在这里按 catalog 目录索引，再次打开同一个库时接上它，而不是新建一个
# 从零开始的 Library（那样进度会归零、工作白做）。
#
# 只保留最近几个：一直切库的话，每个都留一个线程池会把 CPU 和内存吃光。
_DETACHED: dict[str, object] = {}
_DETACHED_MAX = 2


def _drop_oldest() -> None:
    while len(_DETACHED) > _DETACHED_MAX:
        k = next(iter(_DETACHED))
        try:
            _DETACHED.pop(k).cancel()
        except Exception:
            pass


class Session:
    def __init__(self, read_only: bool = False, workers: int | None = None):
        self.lock = threading.RLock()
        self.read_only = read_only
        self.workers = workers
        self.lib: Library | None = None
        self.generation = 0

    @property
    def root(self) -> str | None:
        with self.lock:
            return self.lib.root if self.lib else None

    def open(self, folder: str, work_dir: str | None = None,
             read_only: bool | None = None, scan: bool = True) -> Library:
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            raise NotADirectoryError(folder)
        with self.lock:
            wd = work_dir or paths.catalog_dir(folder)
            # 这个库刚被放下、分析还在跑 —— 接回来，别从零开始。
            # 新建一个 Library 会让进度归零，前面扫过的全白做。
            prev = _DETACHED.pop(wd, None)
            if prev is not None and getattr(prev, "root", None) == folder:
                if self.lib is not None and self.lib is not prev:
                    self.lib.cancel()
                self.lib = prev
                self.generation += 1
                remember(folder)
                return prev
            if self.lib is not None:
                self.lib.cancel()
            ro = self.read_only if read_only is None else read_only
            lib = Library(folder, workers=self.workers, work_dir=wd, read_only=ro)
            self.lib = lib
            self.generation += 1
            remember(folder)
            if scan:
                lib.start()
            return lib

    def close(self) -> None:
        with self.lock:
            if self.lib is not None:
                # 不取消：用户只是回首页，扫描该继续跑完。
                # 放进 _DETACHED，下次打开同一个库时 open() 会把它接回来。
                wd = getattr(self.lib, "work_dir", None) or paths.catalog_dir(self.lib.root)
                _DETACHED[wd] = self.lib
                _drop_oldest()
                self.lib = None
                self.generation += 1

    def require(self) -> Library | None:
        with self.lock:
            return self.lib


