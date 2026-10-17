"""Download the MediaPipe model files Guopian needs. Run once; safe to re-run."""
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
os.makedirs(MODELS, exist_ok=True)

MODEL_URLS = {
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
}


def fetch(name, url, force=False):
    dest = os.path.join(MODELS, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0 and not force:
        print("  [ok]   {} already present ({:,} bytes)".format(name, os.path.getsize(dest)))
        return True
    print("  [get]  {} <- {}".format(name, url))
    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    sys.stdout.write("\r         {}%  ({:,}/{:,} bytes)".format(pct, done, total))
                    sys.stdout.flush()
        sys.stdout.write("\n")
        os.replace(tmp, dest)
        print("  [ok]   saved {:,} bytes".format(os.path.getsize(dest)))
        return True
    except Exception as e:
        print("\n  [FAIL] {}: {}".format(type(e).__name__, e))
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


if __name__ == "__main__":
    print("Guopian model fetch -> {}".format(MODELS))
    ok = all([fetch(n, u) for n, u in MODEL_URLS.items()])
    sys.exit(0 if ok else 1)
