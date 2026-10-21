"""轻量表情模型实测：8 MB、112x112、AffectNet 8 类 + 效价/唤醒。

为什么值得单独试：之前证伪的是 CLIP，不是"模型能不能看表情"。这个模型
（mobilefacenet 多任务版）输入就是一张对齐好的人脸，专门干这件事。

没有标注，所以判据还是"能不能被人眼核对 + 和已有信号一致"：
  * 8 类的分布在 969 张近景脸上像不像话；
  * "开心"的分数和 MediaPipe 的 smile blendshape 相关不相关；
  * Top-N 的对照图看一眼。

    python evaluation/fer_probe.py
"""
import json
import os
import sqlite3
import sys

import numpy as np

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")
DB = os.path.join(CAT, "catalog.db")
MODEL = os.path.join(ROOT, ".cache", "emotion_mbf.onnx")
OUT = os.path.join(ROOT, "docs", "img")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guopian import config, imageio  # noqa: E402
import facecrop  # noqa: E402

# AffectNet 的类别顺序。这个顺序不是我猜的：来自官方 ONNX 包
# hsemotion-onnx 的 facial_emotions.py（idx_to_class），8 类就是下面这个。
# 第一版我按"neutral/happiness/..."猜了一遍，结果 84% 的照片被判成"disgust"——
# 那不是模型坏了，是我把标签对错了位（类的下标 5 其实是 Neutral）。
LABELS = ["anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"]
ZH = {"anger": "生气", "contempt": "轻蔑", "disgust": "厌恶", "fear": "害怕",
      "happiness": "开心", "neutral": "中性", "sadness": "难过", "surprise": "惊讶"}


def main():
    import onnxruntime as ort
    from PIL import Image, ImageOps

    sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    iname = sess.get_inputs()[0].name

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM photos")}
    faces = {}
    for r in con.execute("SELECT * FROM faces ORDER BY photo_id, face_px DESC"):
        faces.setdefault(r["photo_id"], dict(r))
    smile = {r["photo_id"]: (r["sm"] or 0.0) for r in con.execute(
        "SELECT photo_id, max(smile) sm FROM faces GROUP BY photo_id")}

    usable = [pid for pid, f in faces.items()
              if (f["face_px"] or 0) >= 90 and pid in rows]
    usable.sort()
    print("可用近景人脸: %d" % len(usable))

    tc = imageio.ThumbCache(CAT)
    crops = []
    for pid in usable:
        p = tc.get_or_build(rows[pid]["path"], rows[pid]["size"], rows[pid]["mtime"],
                            config.THUMB_CARD)
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        # 人脸框是「左上角 + 尺寸」，不是中心点。见 facecrop.py 里记的那次错。
        crops.append(facecrop.crop(im, faces[pid], 0.15)
                     .resize((112, 112), Image.Resampling.BILINEAR))

    # 预处理必须和官方包一致：cv2 读进来是 BGR，/255，再按通道减 ImageNet 均值。
    # 我用 PIL（RGB），所以先反转成 BGR 再套同样的均值，否则通道错位、分数全乱。
    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)   # 对应 B,G,R
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    batch = np.stack([
        ((np.asarray(c, dtype=np.float32)[:, :, ::-1] / 255.0 - MEAN) / STD).transpose(2, 0, 1)
        for c in crops
    ]).astype(np.float32)
    out = sess.run(None, {iname: batch})[0]
    emo = out[:, :8]
    va = out[:, 8:10]
    probs = stem = np.exp(emo - emo.max(axis=1, keepdims=True))
    probs = probs / probs.sum(axis=1, keepdims=True)
    arg = probs.argmax(axis=1)
    sm = np.array([smile[pid] for pid in usable])
    happy = probs[:, LABELS.index("happiness")]
    r = float(np.corrcoef(happy, sm)[0, 1]) if sm.std() else 0.0
    share = {LABELS[k]: round(float((arg == k).mean()), 3) for k in range(8)}
    print("\n各情绪占比: %s" % share)
    print("happy 概率与 smile blendshape 的相关: %.3f" % r)
    print("效价(valence) 区间 %.2f..%.2f 均值 %.2f | 唤醒(arousal) 均值 %.2f"
          % (va[:, 0].min(), va[:, 0].max(), va[:, 0].mean(), va[:, 1].mean()))

    W, H, COLS = 140, 140, 8
    for k in (LABELS.index("happiness"), LABELS.index("neutral"),
              LABELS.index("contempt"), LABELS.index("disgust")):
        idx = np.where(arg == k)[0]
        if not len(idx):
            print("类别 %s 没有样本" % ZH[LABELS[k]])
            continue
        order = idx[np.argsort(-probs[idx, k])][:COLS * 2]
        canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
        for n, i in enumerate(order):
            canvas.paste(crops[i].resize((W - 4, H - 4), Image.Resampling.LANCZOS),
                         ((n % COLS) * W + 2, (n // COLS) * H + 2))
        path = os.path.join(OUT, "_fer_%s.png" % ZH[LABELS[k]])
        canvas.save(path)
        print("saved", path, "(%d 张)" % len(idx))

    # 效价最低的那批：理论上就是"表情最难看"的候选
    low = np.argsort(va[:, 0])[:COLS * 2]
    canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
    for n, i in enumerate(low):
        canvas.paste(crops[i].resize((W - 4, H - 4), Image.Resampling.LANCZOS),
                     ((n % COLS) * W + 2, (n // COLS) * H + 2))
    path = os.path.join(OUT, "_fer_效价最低.png")
    canvas.save(path)
    print("saved", path)


if __name__ == "__main__":
    main()
