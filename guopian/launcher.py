"""Native dialogs for the packaged build.

The folder picker used to live here too. It moved into the app itself (see
guopian/session.py for the filesystem browsing and web/ for the UI): a desktop
program should show its own window first and let you browse inside it, rather
than throwing an OS dialog at you before anything is on screen.

What remains is the one job that genuinely needs the OS: making a fatal error
visible. A windowed build has no console, so a crash would otherwise be a
silent nothing-happened.
"""

from __future__ import annotations

import sys
import traceback

from . import paths


def _tk():
    import tkinter as tk

    return tk


def _modal(kind: str, title: str, message: str) -> None:
    tk = _tk()
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    try:
        getattr(messagebox, kind)(title, message)
    finally:
        root.destroy()


def fatal(title: str, message: str) -> None:
    """Show an error and log it. Falls back to stderr when tk is unavailable."""
    paths.log("FATAL {}: {}".format(title, message))
    print("{}: {}".format(title, message), file=sys.stderr or sys.stdout)
    try:
        _modal("showerror", title, message)
    except Exception:
        pass


def info(title: str, message: str) -> None:
    paths.log("INFO {}: {}".format(title, message))
    try:
        _modal("showinfo", title, message)
    except Exception:
        print("{}: {}".format(title, message))


def run_guarded(fn, *args, **kwargs):
    """Run the app and make absolutely sure a crash is visible."""
    try:
        return fn(*args, **kwargs)
    except KeyboardInterrupt:
        return 0
    except SystemExit:
        raise
    except Exception:
        fatal("过片启动失败",
              "{}\n\n详细信息已写入:\n{}".format(traceback.format_exc()[-1400:],
                                                paths.log_path()))
        return 1
