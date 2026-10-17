"""Does the face detector do better at full resolution?

Only 18 of 93 photos in the test library come back with a face. Two explanations:
the faces really are hard (occlusion, profile, night), or the detector is being
fed too small an image. ANALYSIS_EDGE is 1500px, which is a deliberate speed
choice for blur and exposure -- but a face detector has its own idea of what
"big enough" means, and it may not agree.

This runs the same photos through at 1500 / 3000 / full and counts.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from guopian import config, faces as faces_mod  # noqa: E402

FOLDER = r"D:\photos\shoot"


def main() -> int:
    import mediapipe as mp
    from guopian.imageio import open_image

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    names = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith(".jpg"))[:n]

    print("\n  {} 张照片，三种分辨率下的人脸检出数\n".format(n))
    print("  {:<16} {:>7} {:>7} {:>7}".format("文件", "1500", "3000", "原始"))

    lm = faces_mod._create_landmarker()
    try:
        totals = {1500: 0, 3000: 0, 0: 0}
        for name in names:
            path = os.path.join(FOLDER, name)
            row = {}
            for edge in (1500, 3000, 0):
                img, _, _ = open_image(path, max_edge=edge if edge else 99999)
                rgb = np.asarray(img.convert("RGB"))
                r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                c = len(r.face_landmarks or [])
                row[edge] = c
                totals[edge] += c
            flag = ""
            if row[0] > row[1500]:
                flag = "  <-- 只有原始分辨率才找得到"
            print("  {:<16} {:>7} {:>7} {:>7}{}".format(
                name[:16], row[1500], row[3000], row[0], flag))
        print("\n  合计   1500px {}   3000px {}   原始 {}".format(
            totals[1500], totals[3000], totals[0]))
    finally:
        try:
            lm.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
