"""Why does an obvious face come back as "no face"?

Walks the same path analysis does, but reports what each gate decided instead of
just the final yes/no. A detector that silently drops a face is worse than one
that never finds it, because the screen then claims there was nothing to find.
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
    names = sys.argv[1:] or ["DSC09856.JPG", "DSC09860.JPG", "DSC09871.JPG"]
    import mediapipe as mp
    from guopian.imageio import open_image

    lm = faces_mod._create_landmarker()
    try:
        for n in names:
            path = os.path.join(FOLDER, n)
            if not os.path.exists(path):
                print("  missing", n)
                continue
            img, _, _ = open_image(path, max_edge=config.ANALYSIS_EDGE)
            rgb = np.asarray(img.convert("RGB"))
            h, w = rgb.shape[:2]
            print("\n  {}  分析尺寸 {}x{}".format(n, w, h))

            # 1. raw detection
            res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            nf = len(res.face_landmarks or [])
            print("    MediaPipe 检出人脸: {}".format(nf))
            if not nf:
                # try harder: the model is scale-sensitive, so try a larger input
                for edge in (2200, 3000):
                    img2, _, _ = open_image(path, max_edge=edge)
                    rgb2 = np.asarray(img2.convert("RGB"))
                    r2 = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb2))
                    print("      放大到 {}px 再试 -> {}".format(edge, len(r2.face_landmarks or [])))
                    if r2.face_landmarks:
                        pts = np.array([[p.x, p.y] for p in r2.face_landmarks[0]])
                        hh = r2.face_landmarks[0]
                        ys = [p.y for p in hh]; xs = [p.x for p in hh]
                        print("      脸框(归一化) x {:.3f}..{:.3f}  y {:.3f}..{:.3f}".format(
                            min(xs), max(xs), min(ys), max(ys)))
                        print("      脸框(像素)   宽 {:.0f}  高 {:.0f}".format(
                            (max(xs) - min(xs)) * rgb2.shape[1],
                            (max(ys) - min(ys)) * rgb2.shape[0]))
                        break
                continue

            # 2. which gate would have dropped it
            pts = np.array([[p.x, p.y, getattr(p, "z", 0.0)]
                            for p in res.face_landmarks[0]], dtype=np.float64)
            face_px = float(np.linalg.norm(pts[152, :2] - pts[10, :2]) * h)
            print("    脸框高度(像素) {:.0f}   阈值 FACE_MIN_PIXELS = {}".format(
                face_px, config.FACE_MIN_PIXELS))
    finally:
        try:
            lm.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
