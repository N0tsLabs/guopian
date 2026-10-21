"""表情：8 类情绪 + 效价/唤醒，跑在已经检测好的人脸上。

模型是 mbf_va_mtl（MobileFaceNet 多任务，AffectNet 训练），7.9 MB、输入
112x112、CPU 上 3 ms 一张。它和 CLIP 是两种东西：CLIP 看整张图讲什么，
这个只看一张脸长什么样。

为什么值得接进来（实测，见 docs/clip-research.md）：
    "开心"概率 与 MediaPipe smile blendshape 的相关 r = 0.51
    对照图里 "开心" Top32 全是真在笑的，"效价最低" 的 16 张是严肃/走神/半闭眼
    而同样这批裁切给 CLIP，只有 ρ=0.25（只能看出在笑）

**但绝对判断不可信**：AffectNet 8 类的公开准确率是 61%–63%。所以这里存的是
原始分数，判断交给"组内相对排名"（group.rank_groups），不比谁的脸色"难看"，
只比同一个连拍里谁的表情更好 —— 同一个人同一束光，误差会互相抵消。

接这个模型踩过的两个坑，都写在这儿，因为下次换模型还会踩：
  1. faces 表里的 (x,y,w,h) 是**左上角 + 尺寸**，不是中心点（见 evaluation/facecrop.py）
  2. 标签顺序不能猜：0生气 1轻蔑 2厌恶 3害怕 4开心 5中性 6难过 7惊讶
     猜错一遍的结果是 84% 的照片被"判"成厌恶。
"""
from __future__ import annotations

import os
import threading

import numpy as np

from . import config, models

# AffectNet 8 类，顺序来自 hsemotion-onnx 的 idx_to_class，不是猜的
LABELS = ("anger", "contempt", "disgust", "fear",
          "happiness", "neutral", "sadness", "surprise")
LABEL_ZH = {"anger": "生气", "contempt": "轻蔑", "disgust": "厌恶", "fear": "害怕",
            "happiness": "开心", "neutral": "中性", "sadness": "难过",
            "surprise": "惊讶"}

_SIZE = 112
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)   # B, G, R
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_SESSION = None
_LOCK = threading.Lock()


def present() -> bool:
    p = config.EMOTION_MODEL
    return os.path.exists(p) and os.path.getsize(p) > 0


def available() -> tuple[bool, str]:
    if not present():
        return False, "表情模型还没下载（8 MB）"
    try:
        import onnxruntime  # noqa: F401
    except Exception as e:
        return False, "onnxruntime 不可用：{}".format(e)
    return True, ""


def ensure() -> dict:
    return models.ensure("emotion.onnx")


def session():
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    with _LOCK:
        if _SESSION is None:
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _SESSION = ort.InferenceSession(config.EMOTION_MODEL, sess_options=so,
                                            providers=["CPUExecutionProvider"])
    return _SESSION


def preprocess(crop) -> np.ndarray:
    """和官方包一致：cv2 是 BGR，/255，再按通道减 ImageNet 均值。

    PIL 给的是 RGB，所以先反转通道再套同样的均值 —— 通道错位不会报错，
    只会让分数悄悄变成另一回事。
    """
    from PIL import Image

    im = crop.convert("RGB").resize((_SIZE, _SIZE), Image.Resampling.BILINEAR)
    a = np.asarray(im, dtype=np.float32)[:, :, ::-1] / 255.0
    return ((a - _MEAN) / _STD).transpose(2, 0, 1)


def predict(crops: list) -> list[dict]:
    """每张脸 -> {'probs': {label: p}, 'valence': v, 'arousal': a, 'emotion': label}

    valence/arousal 是模型多任务头输出的两个连续值（大致 -1..1）。
    效价高 = 情绪正面；唤醒高 = 情绪强烈。
    """
    if not crops:
        return []
    batch = np.stack([preprocess(c) for c in crops]).astype(np.float32)
    out = np.asarray(session().run(None, {"input": batch})[0], dtype=np.float32)
    emo, va = out[:, :8], out[:, 8:10]
    p = np.exp(emo - emo.max(axis=1, keepdims=True))
    p = p / p.sum(axis=1, keepdims=True)
    res = []
    for i in range(len(crops)):
        k = int(p[i].argmax())
        res.append({
            "probs": {LABELS[j]: round(float(p[i, j]), 4) for j in range(8)},
            "emotion": LABELS[k],
            "valence": round(float(va[i, 0]), 4),
            "arousal": round(float(va[i, 1]), 4),
        })
    return res
