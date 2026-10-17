"""Are 468 / 473 really the iris centres? Ask the model, do not assume.

MediaPipe's 478-point mesh appends ten iris points to the 468 face points:
five per eye. The convention is documented as 468 being the centre of the
subject's right iris with 469-472 ringing it, and 473 the centre of the left
with 474-477 ringing it. Every geometric gaze formula on the internet assumes
that. If it is wrong here, the measurement is meaningless -- so this prints the
points and the distances that settle it.
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from guopian import config, faces as faces_mod  # noqa: E402

FOLDER = r"D:\photos\shoot"


def main() -> int:
    import mediapipe as mp
    from guopian.imageio import open_image

    names = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith(".jpg"))
    lm = faces_mod._create_landmarker()
    try:
        for n in names[:60]:
            img, _, _ = open_image(os.path.join(FOLDER, n), max_edge=config.ANALYSIS_EDGE)
            rgb = np.asarray(img.convert("RGB"))
            res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if not res.face_landmarks:
                continue
            pts = np.array([[p.x, p.y] for p in res.face_landmarks[0]])

            print("\n  " + n)
            for label, c, ring in (("subject right", 468, (469, 470, 471, 472)),
                                   ("subject left ", 473, (474, 475, 476, 477))):
                cen = pts[c]
                centroid = pts[list(ring)].mean(axis=0)
                r = np.linalg.norm(pts[list(ring)] - cen, axis=1)
                print("    {} centre {} = ({:.4f}, {:.4f})".format(label, c, cen[0], cen[1]))
                print("         ring centroid     = ({:.4f}, {:.4f})   dist to centre {:.4f}".format(
                    centroid[0], centroid[1], np.linalg.norm(centroid - cen)))
                print("         ring radius        min {:.4f} max {:.4f}".format(r.min(), r.max()))

            # eye corners, to sanity-check the geometry
            for label, a, b in (("right eye 33-133", 33, 133), ("left eye 362-263", 362, 263)):
                w = np.linalg.norm(pts[b] - pts[a])
                print("    {} width {:.4f}".format(label, w))
            return 0
    finally:
        try:
            lm.close()
        except Exception:
            pass
    print("no face found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
