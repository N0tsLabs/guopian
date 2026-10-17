"""How many pixels does an eye actually occupy at analysis resolution?

If the iris landmarks only span ~16 px, then a one-pixel error in a landmark is
a ~6% error in the gaze reading before any real gaze movement is measured -- the
metric would be sitting on its own noise floor. That decides whether geometry
can replace the blendshapes at all, and it is a question about the pipeline, not
about the formula.
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from guopian import config, faces as faces_mod  # noqa: E402

FOLDER = r"D:\image cache\川西\100MSDCF"


def main() -> int:
    import mediapipe as mp
    from guopian.imageio import open_image

    names = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith(".jpg"))[:60]
    lm = faces_mod._create_landmarker()
    widths, irises, faces_px = [], [], []
    try:
        for n in names:
            img, _, _ = open_image(os.path.join(FOLDER, n), max_edge=config.ANALYSIS_EDGE)
            rgb = np.asarray(img.convert("RGB"))
            res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if not res.face_landmarks:
                continue
            pts = np.array([[p.x, p.y] for p in res.face_landmarks[0]])
            w = np.linalg.norm(pts[133] - pts[33])
            r = np.linalg.norm(pts[[469, 470, 471, 472]] - pts[468], axis=1).mean()
            widths.append(w * rgb.shape[1])
            irises.append(r * 2 * rgb.shape[1])
            # face box height, in decoded pixels: 10 (forehead) to 152 (chin)
            faces_px.append(np.linalg.norm(pts[152] - pts[10]) * rgb.shape[0])
    finally:
        try:
            lm.close()
        except Exception:
            pass

    if not widths:
        print("no faces")
        return 1

    def stat(name, a, unit="px"):
        a = sorted(a)
        print("  {:<16} 中位 {:>6.1f}{}   最小 {:>6.1f}   最大 {:>6.1f}".format(
            name, a[len(a) // 2], unit, a[0], a[-1]))

    print("\n  {} 张有脸的照片，分析分辨率 ANALYSIS_EDGE = {}px\n".format(
        len(widths), config.ANALYSIS_EDGE))
    stat("眼睛宽", widths)
    stat("虹膜直径", irises)
    stat("脸高", faces_px)

    med_eye = sorted(widths)[len(widths) // 2]
    print("\n  结论")
    print("    一只眼睛只有 ~{:.0f} 像素宽。虹膜中心的一个像素误差，".format(med_eye))
    print("    在我的归一化单位里就是 {:.3f} —— 而真实视线偏移通常只有 0.2~0.4。".format(2 / med_eye))
    print("    也就是说：几何视线在这个分辨率上量的是自己的噪声。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
