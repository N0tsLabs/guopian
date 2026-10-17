#!/usr/bin/env python3
"""Compare the two ways of measuring gaze, on real photographs.

The current signal is eight `eyeLook*` blendshapes. They are regression outputs:
head-relative by construction (good), but noisy and hard to explain (bad -- a
value of 0.7 does not tell anyone how far the eye actually turned).

The obvious replacement is geometry: where the iris sits between the eye
corners, using the 478-point mesh's iris landmarks (468 / 473), which are
already computed and currently thrown away.

But there is a trap. Iris landmarks are in IMAGE space, so turning the head
slides them sideways exactly like looking sideways does. A naive geometric
measure cannot tell those apart, and would report "looking away" for every
turned head -- which is most candid portraits.

So before replacing anything: measure both on the same faces, and see how much
of the geometric signal is just yaw.

    python evaluation/gaze_compare.py "D:\photos\shoot" [limit]
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from guopian import config, faces as faces_mod  # noqa: E402

# MediaPipe FaceMesh iris centres. 468 is the subject's RIGHT iris, 473 the LEFT;
# 469-472 and 474-477 are the rings around them.
R_IRIS, L_IRIS = 468, 473


def iris_axis(pts, corner_a, corner_b, iris) -> float:
    """Iris position along the eye's own corner-to-corner axis.

    0.0 = centred, +1 = at corner_b, -1 = at corner_a. Measured on the 3D
    landmarks but projected onto the eye's own axis, so an eye that is itself
    rotated in the image does not skew the reading.
    """
    a = pts[corner_a, :2]
    b = pts[corner_b, :2]
    c = pts[iris, :2]
    axis = b - a
    L2 = float(axis @ axis)
    if L2 <= 1e-9:
        return 0.0
    t = float((c - a) @ axis / L2)          # 0 at a, 1 at b
    return (t - 0.5) * 2.0


def lid_axis(pts, lid_top, lid_bottom, iris) -> float:
    """Vertical counterpart: +1 = iris at the upper lid, -1 = lower lid."""
    a = pts[lid_top, :2]
    b = pts[lid_bottom, :2]
    c = pts[iris, :2]
    axis = b - a
    L2 = float(axis @ axis)
    if L2 <= 1e-9:
        return 0.0
    t = float((c - a) @ axis / L2)
    return (t - 0.5) * 2.0


def geometric(pts) -> tuple[float, float]:
    """Gaze in image space, averaged over both eyes.

    Both eyes are converted to the SAME image-space sign before averaging: the
    iris drifting toward image-right is image-right in both eyes, whereas
    "toward the inner corner" flips sign between them. Averaging the
    inner-corner convention would cancel a real gaze out to zero.

    +x = toward the subject's left (image right) for a frontal face, matching
    the convention the blendshape version already used.
    """
    # Both eyes must end up in the SAME image-space sign before averaging.
    # iris_axis(a, b, iris) is positive toward `b`, so each pair is ordered
    # left-corner-then-right-corner:
    #   right eye: 33 (image left) -> 133 (image right)
    #   left eye: 362 (image left) -> 263 (image right)
    # Negating one of them -- which this file did on the first run -- makes the
    # two eyes cancel, and a real gaze averages out to nearly zero. Measured:
    # the horizontal values collapsed to 0.03-0.10 while the blendshapes read up
    # to 0.72 on the same faces.
    rx = iris_axis(pts, 33, 133, R_IRIS)
    lx = iris_axis(pts, 362, 263, L_IRIS)
    ry = lid_axis(pts, 145, 159, R_IRIS)    # 145 lower -> 159 upper, so + = up
    ly = lid_axis(pts, 374, 386, L_IRIS)
    return (rx + lx) / 2.0, (ry + ly) / 2.0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 40

    exts = tuple(config.SUPPORTED_EXT)
    names = sorted(f for f in os.listdir(folder) if f.lower().endswith(exts))[:limit]
    if not names:
        print("no photos in", folder)
        return 2

    from guopian.imageio import open_image

    lm = faces_mod._create_landmarker()
    rows = []
    try:
        for n in names:
            path = os.path.join(folder, n)
            try:
                import mediapipe as mp
                img, _, _ = open_image(path, max_edge=config.ANALYSIS_EDGE)
                rgb = np.asarray(img.convert("RGB"))
                res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            except Exception as exc:
                print("  skip {}: {}".format(n, exc))
                continue
            if not res.face_landmarks:
                continue
            fi = 0
            pts = np.array([[p.x, p.y, getattr(p, "z", 0.0)]
                            for p in res.face_landmarks[fi]], dtype=np.float64)
            bs = (faces_mod._bs_map(res.face_blendshapes[fi])
                  if res.face_blendshapes else {})
            g = lambda k: bs.get(k, 0.0)                      # noqa: E731
            old_x = (g("eyeLookOutLeft") + g("eyeLookInRight")
                     - g("eyeLookInLeft") - g("eyeLookOutRight")) / 2.0
            yaw = 0.0
            if res.facial_transformation_matrixes and fi < len(res.facial_transformation_matrixes):
                try:
                    yaw = faces_mod._euler_from_matrix(
                        res.facial_transformation_matrixes[fi])[0]
                except Exception:
                    pass
            new_x, new_y = geometric(pts)
            rows.append((n, old_x, new_x, new_y, yaw))
    finally:
        try:
            lm.close()
        except Exception:
            pass

    if not rows:
        print("no faces found")
        return 1

    import statistics as st
    old = [abs(r[1]) for r in rows]
    new = [abs(r[2]) for r in rows]
    yaws = [abs(r[4]) for r in rows]

    print("\n  {} 张有脸的照片\n".format(len(rows)))
    print("  {:<16} {:>7} {:>8} {:>8} {:>7}".format("文件", "旧|合|", "新x", "新y", "|yaw|"))
    print("  " + "-" * 50)
    for n, ox, nx, ny, yaw in sorted(rows, key=lambda r: -abs(r[2]))[:18]:
        print("  {:<16} {:>7.2f} {:>8.2f} {:>8.2f} {:>7.1f}".format(
            n[:16], abs(ox), nx, ny, abs(yaw)))

    print("\n  分布")
    print("    旧 |gaze_x|  中位 {:.3f}  p90 {:.3f}  最大 {:.3f}".format(
        st.median(old), sorted(old)[int(len(old) * 0.9)], max(old)))
    print("    新 gaze_x   中位 {:.3f}  p90 {:.3f}  最大 {:.3f}".format(
        st.median(new), sorted(new)[int(len(new) * 0.9)], max(new)))

    # The question that decides whether geometry alone is usable.
    if len(rows) > 3:
        cn = np.corrcoef(new, yaws)[0, 1]
        co = np.corrcoef(old, yaws)[0, 1]
        cno = np.corrcoef(new, old)[0, 1]
        print("\n  相关性")
        print("    新 gaze_x  vs |yaw|   r = {:+.3f}   <- 越高说明几何量越被转头污染".format(cn))
        print("    旧 gaze_x  vs |yaw|   r = {:+.3f}".format(co))
        print("    新 vs 旧              r = {:+.3f}".format(cno))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
