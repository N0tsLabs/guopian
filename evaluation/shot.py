#!/usr/bin/env python3
"""Take README screenshots without touching the user's browser.

Why this exists: the project's screenshots have to be re-taken whenever the UI
changes, and the obvious way -- drive the user's own browser via bridge.py --
is both intrusive and unreliable. bridge.py only ever acts on the ACTIVE tab, so
if the user has switched to anything else it (correctly) refuses, and the
screenshots silently do not happen.

A headless Chromium with its own throwaway profile has none of those problems.
It is a separate process on a separate user-data-dir, it never looks at the
user's tabs, and it can run while they are working.

    python evaluation/shot.py                       # both views into docs/img/
    python evaluation/shot.py --out /tmp/shots
    python evaluation/shot.py --only home

Needs a dev server already running (python run.py --dev). This script does NOT
start one: the server holds the open library, and starting a second would fight
over the port and the catalog.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_browser() -> str | None:
    for c in CANDIDATES:
        if os.path.exists(c):
            return c
    for name in ("msedge", "google-chrome", "chromium", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.load(r)


def shoot(browser: str, url: str, out: str, w: int, h: int) -> bool:
    """One headless capture.

    Three things here are not obvious and each cost real time to find:

    * `--virtual-time-budget` is what lets fetch and image decoding finish.
      Without it the shot is taken before the first /api/home resolves and every
      screenshot is an empty shell.

    * We do NOT wait for the browser to exit. From a shell this command returns
      in about four seconds; under subprocess.run the same command never returns
      at all -- stdout=DEVNULL, stderr=DEVNULL and inherited stdio all hang.
      Chromium is being waited on for its whole process group. The PNG is written
      well before that, so this polls for the file and then kills the process.
      Waiting on exit would also make the script hostage to whatever the page is
      still polling in the background (dev-reload.js never stops).

    * The profile lives under .cache/, not tempfile.gettempdir(): in this
      environment TEMP points inside the working tree, so mkdtemp litters the
      repository with browser profiles.

    * `--no-sandbox` is required. Without it Chromium's own sandbox fails to
      start -- it reports "C:\\Users\\...\\AppData\\Local\\Temp is not writable"
      and then runs forever without ever writing the PNG. The page being
      captured is this machine's own loopback server, so dropping the renderer
      sandbox costs nothing here.
    """
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    cache = os.path.join(ROOT, ".cache")
    os.makedirs(cache, exist_ok=True)
    prof = tempfile.mkdtemp(prefix="shot-", dir=cache)

    proc = subprocess.Popen(
        [browser, "--headless=new", "--no-sandbox", "--disable-gpu",
         "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
         "--user-data-dir=" + prof,
         "--window-size={},{}".format(w, h),
         "--virtual-time-budget=12000",
         "--screenshot=" + out, url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + 90
    ok = False
    try:
        while time.time() < deadline:
            # The file appears in one write, but a half-written PNG would be
            # worse than none -- hence the size floor rather than `exists`.
            if os.path.exists(out) and os.path.getsize(out) > 5000:
                ok = True
                break
            if proc.poll() is not None and not ok:
                break
            time.sleep(0.3)
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
        shutil.rmtree(prof, ignore_errors=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "img"))
    ap.add_argument("--only", choices=["home", "card"], default=None)
    ap.add_argument("--folder", default=None,
                    help="library to open for the card shot (default: the most recent one)")
    args = ap.parse_args()

    browser = find_browser()
    if not browser:
        print("找不到 Chromium 内核的浏览器（Edge / Chrome），无法截图。")
        return 2
    print("  浏览器: {}".format(browser))

    try:
        home = get(args.base, "/api/home")
    except Exception as exc:
        print("  连不上 {}：{}".format(args.base, exc))
        print("  先起一个开发服务器： python run.py --dev --no-open")
        return 2

    sizes = {"home": (1600, 900), "card": (1600, 900)}
    wanted = [args.only] if args.only else ["home", "card"]
    ok = 0

    for which in wanted:
        if which == "card":
            # The card view only renders when a library is open, and the home
            # screen does the opposite. Drive that through the API rather than
            # trying to click things in a headless page.
            folder = args.folder
            if not folder and home.get("recent"):
                folder = home["recent"][0]["path"]
            if not folder:
                print("  card  跳过：没有可打开的项目")
                continue
            try:
                post(args.base, "/api/open", {"path": folder, "read_only": True})
            except Exception as exc:
                print("  card  打不开库：{}".format(exc))
                continue
        else:
            try:
                post(args.base, "/api/close", {})
            except Exception:
                pass

        w, h = sizes[which]
        dest = os.path.join(args.out, "{}.png".format(which))
        if shoot(browser, args.base + "/", dest, w, h):
            print("  {:<5} -> {}  ({:.0f} KB)".format(
                which, os.path.relpath(dest, ROOT), os.path.getsize(dest) / 1024))
            ok += 1
        else:
            print("  {:<5} 失败".format(which))

    # Leave the app as we found it: home view, no library held open.
    try:
        post(args.base, "/api/close", {})
    except Exception:
        pass

    return 0 if ok == len(wanted) else 1


if __name__ == "__main__":
    raise SystemExit(main())
