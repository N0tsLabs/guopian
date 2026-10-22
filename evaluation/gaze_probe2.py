"""虹膜位置能不能代替 eyeLook* blendshape 判断"视线没看镜头"？

blendshape 版的 gaze 在这批真实照片上误报明显（看着镜头却被判 0.98）。虹膜中心
(468 / 473) 是 478 点里自带的，可以用"虹膜在眼眶里的相对位置"来量：

    水平居中 0.5 = 正对镜头；< 0.35 或 > 0.65 基本就是看向一侧

    python evaluation/gaze_probe2.py <catalog> <id:face,id:face,...>
"""
import os
import sys

import numpy as np

ROOT = r"E:\ai project\guopian"
sys.path.insert(0, ROOT)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

R_OUT, R_IN = 33, 133          # 右眼 外/内 眼角
L_IN, L_OUT = 362, 263         # 左眼 内/外 眼角
R_UP, R_DN = 159, 145
L_UP, L_DN = 386, 374
R_IRIS, L_IRIS = 468, 473


def off(pts, iris, out_i, in_i, up_i, dn_i):
    """虹膜在眼眶内的相对位置（0..1，0.5 = 居中）。水平按外→内，垂直按上→下。"""
    x0, x1 = pts[out_i][0], pts[in_i][0]
    y0, y1 = pts[up_i][1], pts[dn_i][1]
    hx = (pts[iris][0] - x0) / max(1e-9, (x1 - x0))
    vy = (pts[iris][1] - y0) / max(1e-9, (y1 - y0))
    return float(hx), float(vy)


def main():
    cat = sys.argv[1]
    pairs = [x.split(":") for x in sys.argv[2].split(",")]
    import sqlite3

    import mediapipe as mp

    from guopian import config, faces, imageio

    con = sqlite3.connect(os.path.join(cat, "catalog.db"))
    con.row_factory = sqlite3.Row
    lm = faces._create_landmarker()
    print("%-10s %-6s %6s %6s %6s %6s  %s" %
          ("photo", "face", "r_h", "r_v", "l_h", "l_v", "blendshape_gaze"))
    for pid, fi in pairs:
        r = con.execute("SELECT * FROM photos WHERE id=?", (int(pid),)).fetchone()
        img, _raw, _s = imageio.open_image(r["path"], max_edge=config.ANALYSIS_EDGE)
        rgb = np.asarray(img.convert("RGB"))
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not res.face_landmarks or int(fi) >= len(res.face_landmarks):
            print("#%-9s %-6s 没有这张脸" % (pid, fi))
            continue
        pts = np.array([[q.x, q.y] for q in res.face_landmarks[int(fi)]])
        if pts.shape[0] < 478:
            print("#%-9s 只有 %d 个点" % (pid, pts.shape[0]))
            continue
        rh, rv = off(pts, R_IRIS, R_OUT, R_IN, R_UP, R_DN)
        lh, lv = off(pts, L_IRIS, L_OUT, L_IN, L_UP, L_DN)
        bs = {b.category_name: b.score for b in res.face_blendshapes[int(fi)]}
        g = lambda k: bs.get(k, 0.0)
        gx = ((g("eyeLookOutLeft") + g("eyeLookInRight"))
              - (g("eyeLookInLeft") + g("eyeLookOutRight"))) / 2
        gy = ((g("eyeLookUpLeft") + g("eyeLookUpRight"))
              - (g("eyeLookDownLeft") + g("eyeLookDownRight"))) / 2
        print("#%-9s %-6s %6.3f %6.3f %6.3f %6.3f  %.2f" %
              (pid, fi, rh, rv, lh, lv, float(np.hypot(gx, gy))))
    lm.close()


if __name__ == "__main__":
    main()
