"""Find the highest-detail region of a photo, so an A/B zoom test is meaningful.

Comparing a 1600px preview against the 6000px original only shows a difference
where the photo actually HAS fine detail. Smooth night bokeh looks the same
either way, which makes a naive A/B test misleading.

    python evaluation/find_detail.py <image> [--root DIR] [--win 600]
"""
from __future__ import annotations

import argparse
import json
import sys

from PIL import Image, ImageFilter

Image.MAX_IMAGE_PIXELS = None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--win", type=int, default=600, help="window size in original pixels")
    ap.add_argument("--stage-w", type=int, default=1093, help="fitted stage width in CSS px")
    ap.add_argument("--stage-h", type=int, default=697)
    ap.add_argument("--view-w", type=int, default=1046, help="cardWrap width in CSS px")
    ap.add_argument("--view-h", type=int, default=697)
    ap.add_argument("--view-x", type=int, default=342, help="cardWrap left on screen")
    ap.add_argument("--view-y", type=int, default=88)
    args = ap.parse_args()

    im = Image.open(args.image)
    im = im.convert("L")
    W, H = im.size
    print("image      : {}  {}x{}".format(args.image, W, H))

    # detail map on a reduced copy -- edges survive downscaling well enough to rank
    scale = 1200.0 / max(W, H)
    small = im.resize((max(1, int(W * scale)), max(1, int(H * scale))), Image.LANCZOS)
    edges = small.filter(ImageFilter.FIND_EDGES)

    win_s = max(4, int(args.win * scale))
    best, best_xy = -1.0, (0, 0)
    step = max(2, win_s // 4)
    px = edges.load()
    for y in range(0, small.height - win_s, step):
        for x in range(0, small.width - win_s, step):
            s = 0.0
            for yy in range(y, y + win_s, 3):
                for xx in range(x, x + win_s, 3):
                    s += px[xx, yy]
            if s > best:
                best, best_xy = s, (x, y)

    sx, sy = best_xy
    cx = int((sx + win_s / 2) / scale)      # centre in ORIGINAL pixels
    cy = int((sy + win_s / 2) / scale)
    print("detail peak: edge-sum {:.0f} at original ({}, {})".format(best, cx, cy))

    # scale so that 1 original pixel == 1 CSS pixel
    s = args.stage_w / W
    u = cx * s
    v = cy * s
    tx = args.stage_w / 2 - u * s
    ty = args.stage_h / 2 - v * s

    # where that centre lands on screen, so the crop box can be computed
    stage_left = args.view_x + (args.view_w - args.stage_w) / 2
    stage_top = args.view_y + (args.view_h - args.stage_h) / 2
    screen_x = stage_left + tx + u * s
    screen_y = stage_top + ty + v * s
    half = args.win / 2 * s

    out = {
        "transform": "translate({:.1f}px,{:.1f}px) scale({:.5f})".format(tx, ty, s * s * 0 + (W / args.stage_w) * 0 + (args.stage_w / W) * 0 + (W / args.stage_w)),
        "scale": W / args.stage_w,
        "crop": [int(screen_x - half), int(screen_y - half),
                 int(screen_x + half), int(screen_y + half)],
    }
    # transform must use scale = W/stage_w so 1 image px == 1 css px
    sc = W / args.stage_w
    tx = args.stage_w / 2 - (cx * args.stage_w / W) * sc
    ty = args.stage_h / 2 - (cy * args.stage_h / H) * sc
    out["transform"] = "translate({:.1f}px,{:.1f}px) scale({:.5f})".format(tx, ty, sc)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
