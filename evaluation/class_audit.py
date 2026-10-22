"""分类抽查：把某一类判定命中的照片摊出来，人眼判断判得对不对。

人脸类的判定（闭眼、看别处、嘴张开…）必须看**脸**，看全身照判断不了，
所以有 face_idx 的判定会自动裁出那张脸。

    python evaluation/class_audit.py <catalog 目录> <kind> [张数]
"""
import os
import sys

from PIL import Image, ImageDraw, ImageOps

ROOT = r"E:\ai project\guopian"
sys.path.insert(0, ROOT)

from guopian import config, imageio  # noqa: E402

OUT = os.path.join(ROOT, "docs", "img")


def main():
    cat = sys.argv[1]
    kinds = sys.argv[2].split(",")
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    import sqlite3
    con = sqlite3.connect(os.path.join(cat, "catalog.db"))
    con.row_factory = sqlite3.Row
    tc = imageio.ThumbCache(cat)

    W, H, PAD = 320, 260, 20
    canvas = Image.new("RGB", (W * 4, (H + PAD) * len(kinds)), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    row = 0
    for kind in kinds:
        rows = list(con.execute(
            "SELECT i.photo_id, i.face_idx, i.severity, p.name, p.path, p.size, p.mtime "
            "FROM issues i JOIN photos p ON p.id = i.photo_id WHERE i.kind = ? "
            "ORDER BY i.confidence DESC, p.id LIMIT ?", (kind, n)))
        print("%-18s %d 张" % (kind, len(rows)))
        for c, r in enumerate(rows):
            p = tc.get_or_build(r["path"], r["size"], r["mtime"], config.THUMB_CARD)
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            if r["face_idx"] is not None:
                f = con.execute("SELECT x,y,w,h FROM faces WHERE photo_id=? AND idx=?",
                                (r["photo_id"], r["face_idx"])).fetchone()
                if f and f["w"]:
                    iw, ih = im.size
                    pad = 0.25
                    box = (max(0, (f["x"] - f["w"] * pad)) * iw,
                           max(0, (f["y"] - f["h"] * pad)) * ih,
                           min(1, (f["x"] + f["w"] * (1 + pad))) * iw,
                           min(1, (f["y"] + f["h"] * (1 + pad))) * ih)
                    im = im.crop(tuple(int(v) for v in box))
            im.thumbnail((W - 4, H - 4), Image.Resampling.LANCZOS)
            canvas.paste(im, (c * W + 2, row * (H + PAD) + PAD))
            draw.text((c * W + 4, row * (H + PAD) + 3),
                      "#%d %s %s" % (r["photo_id"], r["name"], r["severity"]),
                      fill=(200, 200, 200))
        row += 1
    path = os.path.join(OUT, "_audit_%s.png" % kinds[0])
    canvas.save(path)
    print("saved", path)


if __name__ == "__main__":
    main()
