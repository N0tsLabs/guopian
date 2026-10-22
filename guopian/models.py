"""Getting the model files the detector needs.

They are not in the repository: they are third-party binaries with their own
upstream version, and committing them means every clone carries a copy that may
already be stale. Instead the app fetches them on first use, which is also the
moment the user finds out they are needed -- rather than reading about it in a
README and then running a script.

Nothing here runs at import time. `ensure()` is called when a library opens and
the detector reports a missing model, so an install that only ever looks at
photos never touches the network.
"""
from __future__ import annotations

import os
import sys
import urllib.request

from . import config

# MediaPipe publishes these; the path carries the model version.
MODEL_URLS = {
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
    # MobileNetV3-Small 的特征头（没有分类头），用来判"两张图像不像同一个场景"。
    # 3.7 MB、CPU 0.9 ms/张。由 evaluation/export_mnet_onnx.py 导出，导出后
    # 要放进 release 资产；本地存在就直接用，不会去下载。
    "photo_embed.onnx": (
        "https://github.com/N0tsLabs/guopian/releases/download/models-v1/"
        "photo_embed.onnx"
    ),
}


def model_dir() -> str:
    return os.path.dirname(config.FACE_MODEL) or "models"


def present(name: str = "face_landmarker.task") -> bool:
    p = os.path.join(model_dir(), name)
    return os.path.exists(p) and os.path.getsize(p) > 0


def ensure(name: str = "face_landmarker.task", timeout: int = 120) -> dict:
    """Download one model if it is missing. Safe to call repeatedly.

    Written to a `.part` file first and renamed at the end, so an interrupted
    download cannot leave a half-file that looks present -- `present()` would
    then say yes and MediaPipe would fail to parse it.
    """
    if name not in MODEL_URLS:
        return {"ok": False, "error": "未知模型: " + name}
    dest = os.path.join(model_dir(), name)
    if present(name):
        return {"ok": True, "skipped": True, "path": dest,
                "bytes": os.path.getsize(dest)}

    url = MODEL_URLS[name]
    os.makedirs(model_dir(), exist_ok=True)
    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r, open(tmp, "wb") as f:
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
                    sys.stderr.write("\r  model {}  {}%".format(name, pct))
                    sys.stderr.flush()
        sys.stderr.write("\n")
        if os.path.getsize(tmp) == 0:
            raise IOError("下载到的文件是空的")
        os.replace(tmp, dest)
        return {"ok": True, "path": dest, "bytes": os.path.getsize(dest)}
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "error": str(e), "url": url}


def status() -> dict:
    """What the UI needs to decide whether to offer a download."""
    return {
        "dir": model_dir(),
        "models": {n: {"present": present(n), "url": u}
                   for n, u in MODEL_URLS.items()},
    }
