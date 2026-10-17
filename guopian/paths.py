"""Where things live, in both "run from source" and "frozen exe" mode.

Rules:
  * bundled read-only assets (web/, models/) come from the PyInstaller bundle
  * catalogs and thumbnails go to the user data dir, so a photo folder is
    never written to unless the user asks for it
  * a `guopian.portable` marker file next to the executable switches to
    fully portable mode (everything beside the exe) -- useful on a USB stick
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile

APP_NAME = "guopian"
PORTABLE_MARKER = "guopian.portable"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> str:
    """Read-only asset root: the PyInstaller temp dir, or the project root."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_dir() -> str:
    """Folder holding the executable (frozen) or the project (source)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _try_makedirs(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".writable")
        with open(probe, "w") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


_CACHE: dict[str, str] = {}


def _base_dir(kind: str) -> str:
    """A writable base directory, with graceful fallbacks.

    A locked-down profile, a read-only home, or a sandboxed run must not stop
    the app from starting -- it just means we keep data somewhere else.
    """
    if kind in _CACHE:
        return _CACHE[kind]

    candidates: list[str] = []
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        candidates.append(os.path.join(base, APP_NAME))
        candidates.append(os.path.join(tempfile.gettempdir(), APP_NAME))
    elif sys.platform == "darwin":
        candidates.append(os.path.expanduser("~/Library/Application Support/" + APP_NAME))
        candidates.append(os.path.join(tempfile.gettempdir(), APP_NAME))
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        candidates.append(os.path.join(base, APP_NAME))
        candidates.append(os.path.join(tempfile.gettempdir(), APP_NAME))

    for c in candidates:
        if _try_makedirs(c):
            _CACHE[kind] = c
            return c

    d = tempfile.mkdtemp(prefix=APP_NAME + "-")
    _CACHE[kind] = d
    return d


def user_data_dir() -> str:
    return _base_dir("data")


def prefs_dir() -> str:
    """Where prefs.json lives.

    Portable means it sits beside the app: a copied folder that had forgotten
    which projects it had opened would look exactly like data loss.
    """
    if is_portable():
        d = app_dir()
        if _try_makedirs(d):
            return d
    return user_data_dir()


def is_portable() -> bool:
    """Portable by default: every generated file lives beside the app.

    Zip the folder, copy it to a USB stick, run it on another machine -- the
    recent list, the settings and every library's catalog come with it, and
    nothing is left behind in %APPDATA%. "Uninstall" is "delete the folder",
    and "move it elsewhere" is "copy the folder".

    This used to be opt-in behind a marker file, which meant the default build
    scattered its data through the user profile and could not be moved. The only
    reason to want that is a read-only install location such as Program Files,
    and catalog_dir() already falls back to the per-user directory by itself
    when the app folder turns out not to be writable.
    """
    # Explicit opt-out, for anyone who genuinely wants the per-user location.
    if os.environ.get("GUOPIAN_DATA_DIR"):
        return False
    return True



def migrate_legacy_data() -> list[str]:
    """Move prefs and catalogs out of the old per-user location.

    Portable used to be opt-in, so every installation made before that change
    kept its data in the user data directory. Switching the default without this
    would make a correctly-upgraded app look like it had lost every library the
    user had ever opened -- the files would still be there, just somewhere the
    new code no longer looks.

    Runs once, is a no-op when there is nothing to move, and never overwrites a
    file that already exists in the new location.
    """
    import shutil

    moved: list[str] = []
    if not is_portable():
        return moved

    app = app_dir()
    old = user_data_dir()
    if os.path.abspath(old) == os.path.abspath(app) or not os.path.isdir(old):
        return moved

    # catalogs
    src = os.path.join(old, "catalogs")
    dst = os.path.join(app, "catalogs")
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for name in sorted(os.listdir(src)):
            a, b = os.path.join(src, name), os.path.join(dst, name)
            if not os.path.isdir(a):
                continue
            # shutil.move puts src INSIDE dst when dst is an existing directory
            # rather than replacing it, which produced catalogs/<slug>/<slug>/
            # from nothing worse than a leftover empty folder. If the target is
            # already there, the new location wins and the old one is left for
            # the user to delete -- never merged, never nested.
            if os.path.exists(b):
                continue
            try:
                shutil.move(a, b)
                moved.append("catalogs/" + name)
            except Exception:
                pass
        try:
            os.rmdir(src)
        except OSError:
            pass

    # prefs.json
    a = os.path.join(old, "prefs.json")
    b = os.path.join(app, "prefs.json")
    if os.path.exists(a) and not os.path.exists(b):
        try:
            shutil.move(a, b)
            moved.append("prefs.json")
        except Exception:
            pass
    # Nothing else: a leftover prefs.json in the old location is harmless and
    # is left alone rather than deleted behind the user's back.

    return moved


def slug(path: str) -> str:
    """Stable, readable folder name for one photo library."""
    p = os.path.abspath(path)
    digest = hashlib.sha1(p.lower().encode("utf-8")).hexdigest()[:10]
    base = os.path.basename(p.rstrip("\\/")) or "library"
    safe = "".join(c for c in base if c.isalnum() or c in "-_")[:40] or "library"
    return "{}-{}".format(safe, digest)


def catalog_dir(photo_root: str) -> str:
    """Default location of a library's catalog + thumbnail cache."""
    if is_portable():
        root = os.path.join(app_dir(), "catalogs")
        if not _try_makedirs(root):
            root = os.path.join(user_data_dir(), "catalogs")
    else:
        root = os.path.join(user_data_dir(), "catalogs")
    d = os.path.join(root, slug(photo_root))
    if not _try_makedirs(d):
        d = os.path.join(tempfile.mkdtemp(prefix=APP_NAME + "-cat-"))
        os.makedirs(d, exist_ok=True)
    return d


def log_path() -> str:
    return os.path.join(user_data_dir(), "guopian.log")


def log(msg: str) -> None:
    """Append to a log file. A windowed exe has no console, so this is the
    only way a user can tell us what went wrong."""
    try:
        import datetime

        with open(log_path(), "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(datetime.datetime.now().isoformat(timespec="seconds"), msg))
    except Exception:
        pass
