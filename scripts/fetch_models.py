"""Download the MediaPipe model files Guopian needs. Run once; safe to re-run.

Thin wrapper over guopian.models so there is one download implementation rather
than two that can drift apart.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from guopian import models  # noqa: E402


def main() -> int:
    print("  models -> {}".format(models.model_dir()))
    bad = 0
    for name in models.MODEL_URLS:
        r = models.ensure(name)
        if r.get("ok"):
            print("  [ok]   {}  {:,} bytes{}".format(
                name, r.get("bytes") or 0, "  (already there)" if r.get("skipped") else ""))
        else:
            print("  [FAIL] {}  {}".format(name, r.get("error")))
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
