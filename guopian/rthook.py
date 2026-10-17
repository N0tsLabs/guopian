"""PyInstaller runtime hook.

Runs before the app's own imports. A frozen build has no writable "home" we
can assume, and matplotlib (a hard dependency of mediapipe) insists on
creating a font cache the first time it is imported.
"""

import os
import sys
import tempfile


def _writable_dir(name: str) -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = os.path.join(base, "guopian", name)
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".writable")
        with open(probe, "w") as fh:
            fh.write("1")
        os.remove(probe)
        return path
    except Exception:
        return tempfile.mkdtemp(prefix="guopian-")


# We never plot anything; Agg is the only backend that must exist.
os.environ.setdefault("MPLBACKEND", "Agg")
if not os.environ.get("MPLCONFIGDIR"):
    os.environ["MPLCONFIGDIR"] = _writable_dir("mplcache")

# Keep BLAS/OpenMP from oversubscribing when the analysis pool is busy.
for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(var, "1")
