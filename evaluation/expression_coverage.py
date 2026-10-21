"""如果按 blendshape 补几条表情规则，会多标出多少张？

CLIP 判表情这条路已经证伪（见 clip_face_eval.py：闭眼提示词的 Top12 里
一张闭眼的都没有）。所以问题变成：现有 blendshape 里有没有被浪费的信号？

现在的代码只用了 blink（双眼中位数阈值）、jaw_open、brow_down、gaze、smile。
没用上的：squint（算了存了，config.SQUINT_GOOD 是个死常量）、左右眼不对称、
嘴角不对称、以及"半眨眼"这个中间态（0.25-0.6，正是最难看的那种瞬间）。

这个脚本不产物、不改代码，只回答一个问题：加上这几条，覆盖会从
27/969（2.8%）变成多少，而且逐个看一眼是不是真的"表情不好"。

    python evaluation/expression_coverage.py [--sheet]
"""
import os
import sqlite3
import sys

ROOT = r"E:\ai project\guopian"
CAT = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")
DB = os.path.join(CAT, "catalog.db")
OUT = os.path.join(ROOT, "docs", "img")
sys.path.insert(0, ROOT)

from guopian import config, imageio  # noqa: E402


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM photos")}

    face = {}
    for r in con.execute("""SELECT photo_id,
                                   max(blink_l) bl, max(blink_r) br,
                                   max(smile) sm, max(jaw_open) jo,
                                   max(squint) sq, max(brow_down) bd,
                                   max(face_px) fp, max(eye_px) ep
                            FROM faces GROUP BY photo_id"""):
        face[r["photo_id"]] = dict(r)

    # 现有的标记（这些已经在界面上了）
    flagged_now = set()
    for r in con.execute("SELECT DISTINCT photo_id FROM issues WHERE kind IN "
                         "('eye_closed','eye_maybe_closed','mouth_open','frowning')"):
        flagged_now.add(r[0])

    judgeable = [pid for pid, f in face.items()
                 if (f["fp"] or 0) >= config.FACE_MIN_PIXELS
                 and (f["ep"] or 0) >= config.EYE_MIN_PIXELS * 2]

    half_blink, squint_odd, asymmet = set(), set(), set()
    for pid in judgeable:
        f = face[pid]
        bl, br = f["bl"] or 0.0, f["br"] or 0.0
        sm, sq = f["sm"] or 0.0, f["sq"] or 0.0
        lo = min(bl, br)
        # 半眨眼：两只眼都在"半闭"区间，比"闭合"更常见、也更难看
        if 0.25 <= lo < config.EYE_BLINK_CLOSED:
            half_blink.add(pid)
        # 眯眼且不是在笑 —— eyeSquint 在笑的时候也会高，所以必须和 smile 一起看
        if sq >= config.SQUINT_GOOD and sm < 0.2:
            squint_odd.add(pid)
        # 左右眼差太多：不是眨眼，是模型偏向或一只眼被挡，值得看一眼
        if abs(bl - br) >= 0.35:
            asymmet.add(pid)

    new = (half_blink | squint_odd | asymmet) - flagged_now
    print("有人脸的照片            : %d" % sum(1 for r in rows.values() if (r["face_count"] or 0) > 0))
    print("人脸/眼睛够大可判的     : %d" % len(judgeable))
    print("现在被标出表情类问题的  : %d（%.1f%%）"
          % (len(flagged_now), 100.0 * len(flagged_now) / max(1, len(judgeable))))
    print("  半眨眼 0.25-0.60      : %3d" % len(half_blink))
    print("  眯眼且没在笑          : %3d" % len(squint_odd))
    print("  左右眼差 ≥0.35        : %3d" % len(asymmet))
    print("三条加起来是新的        : %3d（合计覆盖 %.1f%%）"
          % (len(new), 100.0 * len(flagged_now | new) / max(1, len(judgeable))))

    if "--sheet" in sys.argv:
        from PIL import Image, ImageOps
        tc = imageio.ThumbCache(CAT)
        W, H, COLS = 200, 150, 5
        groups = [("半眨眼", half_blink - flagged_now), ("眯眼", squint_odd - flagged_now),
                  ("不对称", asymmet - flagged_now)]
        for label, pids in groups:
            pids = sorted(pids)[:COLS * 2]
            if not pids:
                continue
            canvas = Image.new("RGB", (W * COLS, H * 2), (18, 18, 18))
            for n, pid in enumerate(pids):
                r = rows[pid]
                p = tc.get_or_build(r["path"], r["size"], r["mtime"], config.THUMB_CARD)
                im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
                im.thumbnail((W - 6, H - 6), Image.Resampling.LANCZOS)
                canvas.paste(im, ((n % COLS) * W + 3, (n // COLS) * H + 3))
            path = os.path.join(OUT, "_expr_new_%s.png" % label)
            canvas.save(path)
            print("saved", path)


if __name__ == "__main__":
    main()
