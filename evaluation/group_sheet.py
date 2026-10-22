"""把生产库里某个相似组摊成一张对照图，人眼确认这个组对不对。

    python evaluation/group_sheet.py <catalog 目录> <group_id> [group_id...]
"""
import os
import sys

from PIL import Image, ImageDraw, ImageOps

ROOT = r"E:\ai project\guopian"
sys.path.insert(0, ROOT)

from guopian import config, imageio  # noqa: E402


def main():
    cat = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "catalogs", "101MSDCF-61e11b7294")
    gids = [int(x) for x in sys.argv[2:]] or [1]
    import sqlite3
    con = sqlite3.connect(os.path.join(cat, "catalog.db"))
    con.row_factory = sqlite3.Row
    tc = imageio.ThumbCache(cat)
    W, H, PAD = 200, 150, 16
    rows_total = sum(len(con.execute(
        "SELECT 1 FROM photos WHERE group_id=?", (g,)).fetchall()) for g in gids)
    canvas = Image.new("RGB", (W * 8, (H + PAD) * len(gids)), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    for r, g in enumerate(gids):
        members = list(con.execute(
            "SELECT * FROM photos WHERE group_id=? ORDER BY taken_ts", (g,)))
        draw.text((4, r * (H + PAD) + 2), "group %d  %d 张" % (g, len(members)),
                  fill=(220, 220, 220))
        for c, ph in enumerate(members[:8]):
            p = tc.get_or_build(ph["path"], ph["size"], ph["mtime"], config.THUMB_SMALL)
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            im.thumbnail((W - 4, H - 4), Image.Resampling.LANCZOS)
            canvas.paste(im, (c * W + 2, r * (H + PAD) + PAD))
    out = os.path.join(ROOT, "docs", "img", "_prod_groups.png")
    canvas.save(out)
    print("%d 张照片 -> %s" % (rows_total, out))


if __name__ == "__main__":
    main()
