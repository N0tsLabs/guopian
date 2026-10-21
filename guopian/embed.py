"""CLIP 视觉编码器：把一张照片变成 512 维向量。

运行时只有这一半模型。文本那一半不需要 —— 场景词表是固定的，词向量已经
一次算好放在 guopian/data/tag_vecs.npy 里了（见 guopian/tags.py）。

为什么是 ONNX 而不是 torch：torch 装完 2.5 GB，而这里只需要一个前向。
int8 量化后 96 MB，单张 20 ms（CPU）。实测和 fp32 的余弦一致性 0.984，
top-10 检索结果基本重合 —— 数字在 docs/clip-research.md 里。

nothing here runs at import time: onnxruntime is imported when the first
thumbnail actually needs embedding, so a library that never uses search never
pays for it.
"""
from __future__ import annotations

import os
import threading

import numpy as np

from . import config, models, tags

_N_PX = 224
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

_SESSION = None
_LOCK = threading.Lock()


def model_path() -> str:
    """The int8 graph if it is there, otherwise whatever was exported last."""
    base, ext = os.path.splitext(config.SCENE_MODEL)
    for p in (config.SCENE_MODEL, base + ".int8" + ext):
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return p
    return config.SCENE_MODEL


def present() -> bool:
    p = model_path()
    return os.path.exists(p) and os.path.getsize(p) > 0


def available() -> tuple[bool, str]:
    """(can embed, why not). Mirrors faces.available() so the UI can use one shape."""
    if not present():
        return False, "场景模型还没下载（96 MB）"
    if tags.vectors() is None:
        return False, "场景词表向量缺失（guopian/data/tag_vecs.npy）"
    try:
        import onnxruntime  # noqa: F401
    except Exception as e:
        return False, "onnxruntime 不可用：{}".format(e)
    return True, ""


def ensure() -> dict:
    """Download the scene model on demand, same contract as models.ensure()."""
    return models.ensure("clip_vision.onnx")


def session():
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    with _LOCK:
        if _SESSION is None:
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _SESSION = ort.InferenceSession(model_path(), sess_options=so,
                                            providers=["CPUExecutionProvider"])
    return _SESSION


def preprocess(im) -> np.ndarray:
    """CLIP's own transform, without torchvision.

    Resize(shorter side 224, bicubic) -> CenterCrop(224) -> Normalize. It has to
    match the export exactly: a different resize filter moves the embedding
    enough that thresholds measured on one pipeline stop working on the other.
    """
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(im).convert("RGB")
    w, h = im.size
    s = _N_PX / max(1, min(w, h))
    im = im.resize((max(_N_PX, int(round(w * s))), max(_N_PX, int(round(h * s)))),
                   Image.Resampling.BICUBIC)
    w, h = im.size
    left, top = (w - _N_PX) // 2, (h - _N_PX) // 2
    im = im.crop((left, top, left + _N_PX, top + _N_PX))
    a = np.asarray(im, dtype=np.float32) / 255.0
    a = (a - _MEAN) / _STD
    return a.transpose(2, 0, 1)


def encode(pil_images: list) -> np.ndarray:
    """(N, 512) L2-normalised float32."""
    if not pil_images:
        return np.zeros((0, 512), dtype=np.float32)
    batch = np.stack([preprocess(im) for im in pil_images]).astype(np.float32)
    v = session().run(None, {"pixels": batch})[0]
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.maximum(n, 1e-8)


def score_vectors(vectors: np.ndarray, tag: str) -> np.ndarray:
    """余弦：每个向量和某个场景词的相似度。"""
    tv = tags.vectors()
    if tv is None:
        return np.zeros(len(vectors), dtype=np.float32)
    names = tags.names()
    if tag not in names:
        resolved, _ = tags.resolve(tag)
        if not resolved:
            return np.zeros(len(vectors), dtype=np.float32)
        tag = resolved
    k = names.index(tag)
    return np.asarray(vectors @ tv[k], dtype=np.float32)
