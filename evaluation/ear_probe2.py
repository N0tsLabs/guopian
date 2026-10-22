"""用几何量（EAR / MAR）替代 blendshape 判断睁眼/张嘴 —— 验证脚本。

背景：MediaPipe 的 blendshape 在真实照片上不稳定。同一张照片，分析时存进库里
的 blink 是 0.71/0.85，换一个解码尺寸再跑一次读到 0.07/0.13。既然同一个模型
对同一张图能给两套完全不同的数，"眼睛闭合"这种 fatal 判定就不该只靠它。

478 个关键点是同一次推理顺带拿到的，可以算尺度无关的几何量：

    EAR = 上下眼睑距离 / 眼宽     闭眼约 0.10–0.18，睁眼 0.25–0.40
    MAR = 上下内唇距离 / 眼距     闭嘴约 0.00–0.05，张嘴 0.10+

必须用分析时同一条解码路径（imageio.open_image + ANALYSIS_EDGE），否则比的不
是同一次输入，得不出结论。

    python evaluation/ear_probe2.py <catalog> <id,id,...>
"""
import os
import sys

import numpy as np

ROOT = r"E:\ai project\guopian"
sys.path.insert(0, ROOT)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

R_V = [(159, 145), (158, 153), (160, 144)]
R_H = (33, 133)
L_V = [(386, 374), (385, 380), (387, 373)]
L_H = (362, 263)
LIP_V = (13, 14)


def _d(pts, a, b, w, h):
    return float(np.hypot((pts[a][0] - pts[b][0]) * w, (pts[a][1] - pts[b][1]) * h))


def ear(pts, vpairs, horiz, w, h):
    v = np.mean([_d(pts, a, b, w, h) for a, b in vpairs])
    return float(v / max(1e-6, _d(pts, horiz[0], horiz[1], w, h)))


def mar(pts, w, h):
    return float(_d(pts, LIP_V[0], LIP_V[1], w, h) / max(1e-6, _d(pts, 33, 263, w, h)))


def main():
    cat = sys.argv[1]
    ids = [int(x) for x in sys.argv[2].split(",")]
    import sqlite3

    import mediapipe as mp

    from guopian import config, faces, imageio

    con = sqlite3.connect(os.path.join(cat, "catalog.db"))
    con.row_factory = sqlite3.Row
    lm = faces._create_landmarker()

    print("%-6s %-14s %6s %6s %6s %6s %6s %6s %5s" %
          ("id", "name", "EARr", "EARl", "MAR", "blinkR", "blinkL", "jaw", "yaw"))
    for pid in ids:
        r = con.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
        img, _raw, scale = imageio.open_image(r["path"], max_edge=config.ANALYSIS_EDGE)
        rgb = np.asarray(img.convert("RGB"))
        h, w = rgb.shape[:2]
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not res.face_landmarks:
            print("#%-5d %-14s 没有检出脸（scale %.2f）" % (pid, r["name"], scale))
            continue
        best, area = 0, -1
        for fi, lms in enumerate(res.face_landmarks):
            p = np.array([[q.x, q.y] for q in lms])
            a = (p[:, 0].max() - p[:, 0].min()) * (p[:, 1].max() - p[:, 1].min())
            if a > area:
                best, area = fi, a
        pts = np.array([[q.x, q.y] for q in res.face_landmarks[best]])
        bs = {b.category_name: b.score for b in res.face_blendshapes[best]}
        yaw = 0.0
        try:
            yaw = abs(faces._euler_from_matrix(res.facial_transformation_matrixes[best])[0])
        except Exception:
            pass
        print("#%-5d %-14s %6.3f %6.3f %6.3f %6.2f %6.2f %6.2f %5.1f" % (
            pid, r["name"], ear(pts, R_V, R_H, w, h), ear(pts, L_V, L_H, w, h),
            mar(pts, w, h), bs.get("eyeBlinkRight", 0), bs.get("eyeBlinkLeft", 0),
            bs.get("jawOpen", 0), yaw))
    lm.close()


if __name__ == "__main__":
    main()

