"""照片向量：MobileNetV3-Small 的 576 维特征，用来判"像不像同一个场景"。

为什么不是 pHash：pHash 只看低频结构。实测同一个库、相邻 60 秒内的照片对，
pHash 距离中位数 26（阈值 10），也就是同一秒拍的同一个人它大多判"不像"。
换成这个模型后，同样的照片对余弦中位数 0.87，人眼核对过的分组没有错并。

为什么不是 CLIP：那个 92 MB，对"找照片"这个用途收益不够（见提交历史）。
这个模型导出后 **3.7 MB**、CPU **0.9 ms/张**、每张只存 576 个 float16（1.1 KB）。
分类头（1000 类 ImageNet）在导出时就扔了 —— 我们要的是"这张图长什么样"，
不是"这是不是金毛"。

模型文件按需下载（models.ensure），不在仓库里。
"""
from __future__ import annotations

import os
import threading

import numpy as np

from . import config, models

_DIM = 576
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_SESSION = None
_LOCK = threading.Lock()


def model_path() -> str:
    return config.EMBED_MODEL_FILE


def present() -> bool:
    p = model_path()
    return os.path.exists(p) and os.path.getsize(p) > 0


def available() -> tuple[bool, str]:
    if not present():
        return False, "照片向量模型还没下载（3.7 MB）"
    try:
        import onnxruntime  # noqa: F401
    except Exception as e:
        return False, "onnxruntime 不可用：{}".format(e)
    return True, ""


def ensure() -> dict:
    return models.ensure(os.path.basename(model_path()))


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
    """和 torchvision 训练时一致：短边缩到 256、中心裁 224、ImageNet 归一化。

    这套预处理必须和导出时用的完全一致 —— 差一点不会报错，只会让相似度
    悄悄变钝。见 evaluation/mnet_onnx_check.py 里的对照。
    """
    from PIL import Image

    im = im.convert("RGB")
    w, h = im.size
    scale = 256.0 / min(w, h)
    if scale < 1.0:
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                       Image.Resampling.BICUBIC)
    w, h = im.size
    left, top = (w - 224) // 2, (h - 224) // 2
    im = im.crop((left, top, left + 224, top + 224))
    a = np.asarray(im, dtype=np.float32) / 255.0
    return ((a - _MEAN) / _STD).transpose(2, 0, 1)


def encode(images: list) -> np.ndarray:
    """N 张 PIL 图 -> (N, 576) 单位向量。"""
    if not images:
        return np.zeros((0, _DIM), dtype=np.float32)
    batch = np.stack([preprocess(im) for im in images]).astype(np.float32)
    out = np.asarray(session().run(None, {"input": batch})[0], dtype=np.float32)
    norm = np.linalg.norm(out, axis=1, keepdims=True) + 1e-9
    return out / norm
