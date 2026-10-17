#!/usr/bin/env python3
"""Talk to the Kimi WebBridge daemon (drives the user's real browser).

    python evaluation/bridge.py status
    python evaluation/bridge.py tabs
    python evaluation/bridge.py go http://127.0.0.1:8765/
    python evaluation/bridge.py shot                 # screenshot -> prints the path
    python evaluation/bridge.py eval  "document.title"
    python evaluation/bridge.py eval-file  some.js   # evaluate a file
    python evaluation/bridge.py text                 # readable page text
    python evaluation/bridge.py close                # close the tab we opened
    python evaluation/bridge.py close-all

Exists because PowerShell's JSON quoting mangles anything non-trivial, and
because the AGENTS.md usage snippet predates the current tool names.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("KIMI_WEBBRIDGE", "http://127.0.0.1:10086/command")

# Only ever drive pages on this machine. The extension acts on whichever tab is
# ACTIVE, so the moment the user switches tabs every eval, screenshot and
# keypress silently lands on their page instead -- reloading a signed-in site,
# typing into its forms. Cheap to check; expensive to get wrong.
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")

# Tabs this script opened, so `close` only ever closes our own.
_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bridge_state.json")


def call(action: str, args: dict | None = None, timeout: int = 60):
    body = json.dumps({"action": action, "args": args or {}}).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "body": e.read().decode("utf-8", "ignore")[:400]}
    except Exception as e:
        return {"ok": False, "error": "{}: {}".format(type(e).__name__, e)}


def _load_state() -> dict:
    try:
        with open(_STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(d: dict) -> None:
    try:
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def _track(tab_id) -> None:
    if tab_id in (None, ""):
        return
    s = _load_state()
    tabs = s.setdefault("tabs", [])
    if tab_id not in tabs:
        tabs.append(tab_id)
    _save_state(s)


def _untrack(tab_id) -> None:
    s = _load_state()
    tabs = [t for t in s.get("tabs", []) if t != tab_id]
    s["tabs"] = tabs
    _save_state(s)


def _guard() -> str | None:
    """Return the offending URL if the active tab is not one of ours.

    Raises nothing and touches nothing: it only reads location.href, so a stray
    attachment costs one request instead of a reload of somebody's web app.
    """
    href = _unwrap(cmd_eval("location.href"))
    if not isinstance(href, str) or not href:
        return "无法读取 location.href"
    host = urllib.parse.urlsplit(href).hostname or ""
    if host not in ALLOWED_HOSTS:
        return href
    return None


def cmd_status():
    return call("list_tabs")


def cmd_go(url: str, new_tab: bool = True):
    r = call("navigate", {"url": url, "newTab": new_tab})
    if r.get("ok"):
        _track((r.get("data") or {}).get("tabId"))
    return r


def cmd_shot():
    r = call("screenshot", {"format": "png"})
    if r.get("ok"):
        return (r["data"] or {}).get("path")
    return r


def cmd_eval(code: str):
    return call("evaluate", {"code": code})


def cmd_text():
    return call("read_page", {})


def cmd_close(tab_id=None):
    """Close only tabs this helper opened, unless an id is given."""
    closed = []
    targets = [tab_id] if tab_id else list(_load_state().get("tabs", []))
    for t in targets:
        r = call("close_tab", {"tabId": t})
        if r.get("ok"):
            closed.append(t)
            _untrack(t)
        else:
            # it may already be gone; stop tracking so the list cannot grow
            _untrack(t)
    return {"ok": True, "closed": closed}


def _unwrap(out):
    """`evaluate` returns {"data":{"type":"string","value":"<json>"}}; make it readable."""
    if not isinstance(out, dict):
        return out
    d = out.get("data")
    if isinstance(d, dict) and isinstance(d.get("value"), str):
        try:
            parsed = json.loads(d["value"])
            return parsed
        except Exception:
            return d["value"]
    return out


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]

    # Everything that reads or drives the page goes through the guard first.
    if cmd in ("eval", "eval-file", "shot", "text", "keys", "type",
               "rawfile", "raw"):
        stray = _guard()
        if stray:
            print("拒绝执行：当前活动标签页不是本机页面，而是\n  {}".format(stray))
            print("扩展只作用于「当前活动标签页」，所以你现在操作的可能是用户自己的页面。")
            print("先运行：  python evaluation/bridge.py go http://127.0.0.1:8765/")
            return 3

    if cmd == "status":
        out = cmd_status()
    elif cmd == "tabs":
        out = call("list_tabs")
    elif cmd == "go":
        if not rest:
            print("usage: bridge.py go <url>")
            return 2
        out = cmd_go(rest[0])
    elif cmd == "shot":
        out = cmd_shot()
    elif cmd == "eval":
        out = _unwrap(cmd_eval(rest[0] if rest else "document.title"))
    elif cmd == "eval-file":
        with open(rest[0], encoding="utf-8") as f:
            out = _unwrap(cmd_eval(f.read()))
    elif cmd == "text":
        out = _unwrap(cmd_text())
    elif cmd == "keys":
        # the extension wants one string: "Enter", "Mod+A", "Shift+Tab", "Enter Escape"
        out = call("send_keys", {"keys": " ".join(rest) if rest else "Tab"})
    elif cmd == "type":
        out = call("key_type", {"key": rest[0] if rest else "Tab"})
    elif cmd == "rawfile":
        # bridge.py rawfile <action> <file.json>  -- dodges shell quoting.
        # utf-8-sig because PowerShell's -Encoding UTF8 writes a BOM.
        with open(rest[1], encoding="utf-8-sig") as f:
            out = call(rest[0], json.load(f))
    elif cmd == "close":
        out = cmd_close(rest[0] if rest else None)
    elif cmd == "close-all":
        out = cmd_close(None)
    elif cmd == "raw":
        out = call(rest[0], json.loads(rest[1]) if len(rest) > 1 else {})
    else:
        print("unknown command:", cmd)
        print(__doc__)
        return 2

    if isinstance(out, str):
        print(out)
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if (not isinstance(out, dict) or out.get("ok", True)) else 1


if __name__ == "__main__":
    sys.exit(main())
