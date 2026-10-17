"""Generate the application icon (PNG + ICO + ICNS-less source sizes).

    python scripts/make_icon.py

Design: three fanned cards (the one-at-a-time flow) with a green keep-arrow
and a red reject-arrow, on the same near-black the UI uses.
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "guopian", "assets")

BG = (11, 12, 14, 255)
CARD = (232, 234, 237, 255)
CARD_DIM = (139, 148, 158, 255)
KEEP = (46, 160, 67, 255)
REJECT = (229, 72, 77, 255)


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def make(size: int) -> Image.Image:
    S = 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # background squircle
    rounded(d, (0, 0, S - 1, S - 1), int(S * 0.22), BG)

    # three fanned cards
    cw, ch = int(S * 0.44), int(S * 0.56)
    cx, cy = S // 2, int(S * 0.50)
    for i, (dx, dy, ang, col) in enumerate([
        (-int(S * 0.20), int(S * 0.02), -13, (60, 66, 76, 255)),
        (int(S * 0.20), int(S * 0.02), 13, (60, 66, 76, 255)),
        (0, 0, 0, CARD),
    ]):
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        rounded(cd, (0, 0, cw - 1, ch - 1), int(cw * 0.10), col)
        if i == 2:  # inner detail on the front card only
            cd.rounded_rectangle(
                (int(cw * 0.14), int(ch * 0.13), int(cw * 0.86), int(ch * 0.50)),
                radius=int(cw * 0.06), fill=(70, 78, 90, 255))
            cd.rounded_rectangle(
                (int(cw * 0.14), int(ch * 0.60), int(cw * 0.60), int(ch * 0.68)),
                radius=int(cw * 0.04), fill=CARD_DIM)
            cd.rounded_rectangle(
                (int(cw * 0.14), int(ch * 0.75), int(cw * 0.44), int(ch * 0.83)),
                radius=int(cw * 0.04), fill=(90, 98, 110, 255))
        card = card.rotate(ang, resample=Image.BICUBIC, expand=True)
        img.alpha_composite(card, (cx - card.width // 2 + dx, cy - card.height // 2 + dy))

    # keep (right) and reject (left) arrows
    ay = int(S * 0.50)
    aw, ah = int(S * 0.11), int(S * 0.13)
    d.polygon([(S * 0.055, ay - ah * 0.5), (S * 0.055 + aw, ay),
               (S * 0.055, ay + ah * 0.5)], fill=REJECT)
    d.polygon([(S * 0.945, ay - ah * 0.5), (S * 0.945 - aw, ay),
               (S * 0.945, ay + ah * 0.5)], fill=KEEP)

    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
    imgs = {s: make(s) for s in sizes}

    png = os.path.join(OUT, "guopian.png")
    imgs[512].save(png)
    print("  wrote", png)

    ico = os.path.join(OUT, "guopian.ico")
    imgs[256].save(ico, format="ICO",
                   sizes=[(s, s) for s in sizes if s <= 256])
    print("  wrote", ico)

    # macOS wants a real .icns; if Pillow can't write it, the build script
    # falls back to iconutil on a macOS runner.
    icns = os.path.join(OUT, "guopian.icns")
    try:
        imgs[512].save(icns, format="ICNS")
        print("  wrote", icns)
    except Exception as e:
        print("  skipped icns ({})".format(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
