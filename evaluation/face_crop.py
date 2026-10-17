"""Would cropping find the faces that downscaling loses?

Measured so far:
  * the same photos at 1500 / 3000 / full resolution give 5 / 4 / 4 faces --
    MORE resolution does not help, which only makes sense if the detector
    rescales its input to a fixed size internally. It does: BlazeFace runs at
    roughly 256x256, so a face covering 3% of a 6000px frame is still ~8px by
    the time the detector sees it, no matter what we hand it.
  * DSC09891-09893 are a standing woman, unobstructed, unrotated, plainly
    visible -- and come back with no face at all.

If that reading is right, cropping the region the face is in should find it,
because cropping is the only thing that actually increases the face's SHARE of
the detector's input. That is what this checks, and it decides whether the fix
is "tile the image" or "replace the model".
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
    from PIL import Image
    from guopian.imageio import open_image

    names = sys.argv[1:] or ["DSC09891.JPG", "DSC09892.JPG", "DSC09893.JPG",
                             "DSC09869.JPG", "DSC09856.JPG"]
    lm = faces_mod._create_landmarker()

    def count(im):
        rgb = np.asarray(im.convert("RGB"))
        r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        return len(r.face_landmarks or [])

    try:
        print("\n  {:<16} {:>10} {:>12} {:>12}".format(
            "文件", "整图1500", "裁上半身", "裁头部附近"))
        for n in names:
            path = os.path.join(FOLDER, n)
            if not os.path.exists(path):
                continue
            full = Image.open(path)
            W, H = full.size

            whole, _, _ = open_image(path, max_edge=config.ANALYSIS_EDGE)
            c_whole = count(whole)

            # A person standing in a full-body shot sits in the middle column,
            # from roughly the head down. Two crops at different tightness.
            box_body = (int(W * 0.30), int(H * 0.10), int(W * 0.72), int(H * 0.95))
            box_head = (int(W * 0.36), int(H * 0.12), int(W * 0.62), int(H * 0.48))

            c_body = count(full.crop(box_body).resize((1024, 1024), Image.Resampling.LANCZOS))
            c_head = count(full.crop(box_head).resize((1024, 1024), Image.Resampling.LANCZOS))

            flag = "  <-- 裁出来才找到" if (c_body or c_head) and not c_whole else ""
            print("  {:<16} {:>10} {:>12} {:>12}{}".format(
                n[:16], c_whole, c_body, c_head, flag))
    finally:
        try:
            lm.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
