"""Can this machine write to the photo folder?

Run by 诊断.bat (double-click it in Explorer). It lives in Python rather than in
the .bat because the paths contain Chinese: a .bat is read by CMD with the
console code page, so it must stay ASCII, while Python reads UTF-8 correctly.

The integrity level is the whole point of this script. Windows' Mandatory
Integrity Control says a process may write to an object only if the process's
integrity level is >= the object's, and an UNLABELLED object counts as Medium.
A process dropped to LOW therefore cannot write to any ordinary folder -- no
matter what its ACLs say, and no matter that its children inherit the same
restriction, which is why cmd and robocopy fail too when Python starts them.
"""
from __future__ import annotations

import ctypes
import getpass
import re
import os
import sys

PHOTO_DIR = r"D:\image cache\川西\100MSDCF"
CONTROL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       ".cache")

LEVELS = {0x0000: "Untrusted", 0x1000: "Low", 0x2000: "Medium",
          0x3000: "Medium-Plus", 0x4000: "High", 0x5000: "System"}


def integrity() -> str:
    """The process's own integrity level.

    Read from `whoami /groups` rather than through the token API: the ctypes
    route needs GetCurrentProcess's pseudo-handle restyped to c_void_p, and
    getting that wrong fails silently as "cannot open token" -- which is the
    same shape of unhelpful answer this whole script exists to avoid.
    """
    try:
        import subprocess
        out = subprocess.run(["whoami", "/groups"], capture_output=True,
                             text=True, encoding="gbk", errors="replace").stdout or ""
        for ln in out.split("\n"):
            if "Mandatory Label" in ln:
                m = re.search(r"S-1-16-(\d+)", ln)
                rid = int(m.group(1)) if m else 0
                return "{} (S-1-16-{})".format(LEVELS.get(rid, "?"), rid)
        return "(no mandatory label reported)"
    except Exception as e:
        return "(error: {})".format(e)


def parent_chain() -> str:
    """Who launched this process, back a couple of steps.

    Integrity level is INHERITED, so "why am I Low" is answered by "what
    launched me". A double-click in Explorer gives explorer.exe -> cmd.exe ->
    python.exe, all Medium. A Low integrity here means the shell that ran the
    .bat was already Low, which is the thing worth fixing.
    """
    try:
        import subprocess
        ps = ("$p = Get-CimInstance Win32_Process -Filter \"ProcessId=$PID\";"
              " $out = @();"
              " for ($i=0; $i -lt 4 -and $p; $i++) {"
              "   $out += $p.Name;"
              "   $p = Get-CimInstance Win32_Process -Filter \"ProcessId=$($p.ParentProcessId)\";"
              " }; $out -join ' <- '")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, encoding="gbk",
                           errors="replace", timeout=30)
        return (r.stdout or "").strip() or "(unknown)"
    except Exception as e:
        return "(error: {})".format(e)


def attempt(label, fn):
    try:
        fn()
        print("  {:<44} OK".format(label))
        return True
    except Exception as e:
        print("  {:<44} FAILED".format(label))
        print("      {}: {}".format(type(e).__name__, e))
        return False


def main() -> int:
    print()
    print("  " + "=" * 62)
    print("  Can THIS machine write to the photo folder?")
    print("  " + "=" * 62)
    print()
    print("  user       : {}".format(getpass.getuser()))
    print("  python     : {}".format(sys.executable))
    print("  integrity  : {}".format(integrity()))
    print("  elevated   : {}".format(_admin()))
    print("  photo dir  : exists={}".format(os.path.isdir(PHOTO_DIR)))
    print()
    print("  started by : {}".format(parent_chain()))
    print()

    def mkdir_photo():
        p = os.path.join(PHOTO_DIR, "_gtest")
        os.makedirs(p, exist_ok=True)
        os.rmdir(p)

    def mkdir_control():
        p = os.path.join(CONTROL, "_gtest")
        os.makedirs(p, exist_ok=True)
        os.rmdir(p)

    photo_ok = attempt("os.makedirs into the photo folder", mkdir_photo)
    ctrl_ok = attempt("os.makedirs into the workspace (control)", mkdir_control)

    print()
    if photo_ok:
        print("  VERDICT: writing works here. If the app still fails, it is")
        print("           running as a different process than this one.")
    elif ctrl_ok:
        print("  VERDICT: this process can write to the workspace but not to the")
        print("           photo folder. Look at integrity above: if it says Low,")
        print("           this shell was started from inside the agent session.")
        print("           Double-click the .bat in Explorer instead.")
    else:
        print("  VERDICT: cannot write anywhere. Not about the photo folder.")
    print()
    return 0


def _admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
