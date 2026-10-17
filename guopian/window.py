"""Present the UI as a real application window.

Chromium's `--app=` mode gives a window with no address bar, no tab strip and
its own taskbar entry -- it reads as an application, not as "a browser tab you
have to find". Edge, Chrome, Brave, Chromium and Vivaldi all support it, which
covers effectively every desktop we ship to.

Why not pywebview (an embedded WebView2 host)? Because it depends on pythonnet,
which fails to load its runtime DLL in a venv built with --system-site-packages
-- and a window that silently does not appear is the worst possible outcome.
`--app=` needs no extra dependency at all.

The window gets its own --user-data-dir so it cannot disturb the user's normal
browsing profile, and is launched as a tracked child process so we can shut it
down cleanly when the server exits.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

from . import paths

# Launched windows, so we can close them when the app exits.
_children: list[subprocess.Popen] = []
_profile_dir: str | None = None


def _candidates() -> list[str]:
    """Browsers that support --app, most preferred first."""
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        return [
            os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.join(pf, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.join(pf, r"Vivaldi\Application\vivaldi.exe"),
        ]
    if sys.platform == "darwin":
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    return [
        p for p in (
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("microsoft-edge"),
            shutil.which("microsoft-edge-stable"),
            shutil.which("brave-browser"),
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ) if p
    ]


def find_browser() -> str | None:
    for c in _candidates():
        if c and os.path.exists(c):
            return c
    return None


def _window_profile() -> str:
    """A private Chromium profile, so the app window is not the user's session."""
    global _profile_dir
    if _profile_dir:
        return _profile_dir
    d = os.path.join(paths.user_data_dir(), "window-profile")
    os.makedirs(d, exist_ok=True)
    _profile_dir = d
    return d


def open_app_window(url: str, port: int, width: int = 1320, height: int = 880,
                    devtools: bool = False) -> bool:
    """Open `url` in a chromeless application window.

    Returns True when a window was launched; False means the caller should fall
    back to the default browser.
    """
    exe = find_browser()
    if not exe:
        paths.log("no --app capable browser found; falling back to default browser")
        return False

    args = [
        exe,
        "--app={}".format(url),
        "--user-data-dir={}".format(_window_profile()),
        "--window-size={},{}".format(width, height),
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-extensions",
        "--metrics-recording-only",
        "--no-service-autorun",
        "--password-store=basic",
        "--app-auto-launched",
    ]
    if devtools:
        # App-mode windows have no menu bar, so this is the only way to get
        # the inspector inside the packaged shell.
        args.insert(1, "--auto-open-devtools-for-tabs")
    try:
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                  "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(args, **kwargs)
        _children.append(proc)
        paths.log("app window launched: {} (pid {})".format(os.path.basename(exe), proc.pid))
        return True
    except Exception as e:
        paths.log("failed to launch app window: {}: {}".format(type(e).__name__, e))
        return False


def close_windows(wait: float = 3.0) -> None:
    """Ask the app window(s) to close. Used on shutdown."""
    for p in list(_children):
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    deadline = time.time() + wait
    for p in list(_children):
        try:
            while p.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    _children.clear()
