"""Generate a synthetic test set so the pipeline can be smoke-tested offline.

    python evaluation/make_testset.py [outdir]

Covers each detector with a deliberately broken twin:
    sharp vs blurred vs noisy vs flat
    correct exposure vs blown vs crushed
    level vs tilted horizon
    a burst of near-identical frames + one exact duplicate
    one oversized JPEG and one tiny JPEG
    a real human face (scikit-image's "astronaut") and damaged variants

This is a *smoke test*, not an accuracy benchmark. Accuracy has to be measured
on your own photos -- see evaluation/README.md.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

rng = np.random.default_rng(20240812)


def _scene(w=2400, h=1600) -> Image.Image:
    """A textured fake landscape: sky gradient, mountains, ground, detail."""
    y = np.linspace(0, 1, h)[:, None]
    sky = np.zeros((h, w, 3), dtype=np.float32)
    sky[:, :, 0] = 90 + 110 * (1 - y[:, 0])[:, None]
    sky[:, :, 1] = 130 + 100 * (1 - y[:, 0])[:, None]
    sky[:, :, 2] = 200 + 45 * (1 - y[:, 0])[:, None]

    img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    # mountains
    for layer, col in enumerate([(70, 80, 95), (55, 62, 74), (38, 44, 54)]):
        pts = [(0, h)]
        base = h * (0.52 + layer * 0.07)
        x = 0
        while x <= w:
            pts.append((x, base - rng.uniform(20, 190) - layer * 8))
            x += rng.integers(90, 260)
        pts.append((w, h))
        d.polygon(pts, fill=col)
    d.rectangle([0, int(h * 0.72), w, h], fill=(58, 78, 50))
    # ground texture
    for _ in range(2600):
        x, yy = rng.integers(0, w), rng.integers(int(h * 0.72), h)
        r = rng.integers(2, 11)
        g = int(rng.integers(45, 105))
        d.ellipse([x, yy, x + r, yy + r], fill=(g - 14, g, g - 22))
    # a building with hard edges (gives Hough something to find)
    d.rectangle([w * 0.62, h * 0.40, w * 0.86, h * 0.76], fill=(150, 140, 128))
    for i in range(9):
        x0 = w * 0.635 + i * w * 0.024
        d.rectangle([x0, h * 0.44, x0 + w * 0.012, h * 0.52], fill=(40, 50, 66))
    return img


def _exifish(path):
    """PIL saves no EXIF; that is fine, but note it in the filename anyway."""
    return path


def build(outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    base = _scene()

    def save(img: Image.Image, name: str, quality=92):
        p = os.path.join(outdir, name)
        img.convert("RGB").save(p, "JPEG", quality=quality)
        print("  {:<34} {}".format(name, "{}x{}".format(*img.size)))

    # ---- landscape -------------------------------------------------
    save(base, "land_sharp.jpg")

    save(base.filter(ImageFilter.GaussianBlur(9)), "land_blurry.jpg")
    save(base.filter(ImageFilter.GaussianBlur(2.2)), "land_slightly_soft.jpg")

    a = np.asarray(base, dtype=np.float32)
    noisy = np.clip(a + rng.normal(0, 26, a.shape), 0, 255).astype(np.uint8)
    save(Image.fromarray(noisy), "land_noisy.jpg")

    blown = np.clip(a * 1.9 + 60, 0, 255).astype(np.uint8)
    save(Image.fromarray(blown), "land_blown.jpg")

    crushed = np.clip(a * 0.22 - 6, 0, 255).astype(np.uint8)
    save(Image.fromarray(crushed), "land_crushed.jpg")

    flat = (a * 0.12 + 118).astype(np.uint8)
    save(Image.fromarray(flat), "land_flat.jpg")

    save(base.rotate(-3.2, resample=Image.BICUBIC, expand=False), "land_tilted.jpg")

    small = base.resize((900, 600), Image.Resampling.LANCZOS)
    save(small, "land_small.jpg")

    # ---- burst + exact duplicate -----------------------------------
    for i in range(4):
        shifted = base.transform(
            base.size, Image.AFFINE,
            (1, 0, i * 7, 0, 1, i * 4), resample=Image.BICUBIC)
        arr = np.asarray(shifted, dtype=np.float32) * (1.0 + i * 0.012)
        save(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)),
             "burst_{}.jpg".format(i + 1), quality=90 + i)
    save(Image.open(os.path.join(outdir, "burst_1.jpg")), "burst_1_exact_copy.jpg")

    # ---- real face (scikit-image sample: astronaut) -----------------
    try:
        from skimage import data

        face = Image.fromarray(data.astronaut()).convert("RGB")
        face = face.resize((1024, 1024), Image.Resampling.LANCZOS)
        save(face, "face_sharp.jpg")
        save(face.filter(ImageFilter.GaussianBlur(4)), "face_blurry.jpg")
        save(Image.fromarray(np.clip(np.asarray(face, np.float32) * 0.22, 0, 255).astype(np.uint8)),
             "face_dark.jpg")
        save(Image.fromarray(np.clip(np.asarray(face, np.float32) * 2.1, 0, 255).astype(np.uint8)),
             "face_blown.jpg")

        # crude "eyes shut" paint-over, only to check that the blink signal moves
        shut = face.copy()
        dd = ImageDraw.Draw(shut)
        for cx in (0.40, 0.60):
            x, y = 1024 * cx, 1024 * 0.42
            dd.ellipse([x - 42, y - 15, x + 42, y + 15], fill=(205, 168, 142))
            dd.arc([x - 34, y - 12, x + 34, y + 12], 200, 340, fill=(70, 50, 42), width=5)
        save(shut, "face_eyes_painted_shut.jpg")

        # half-size duplicate to exercise the near-duplicate path
        save(face.resize((700, 700), Image.Resampling.LANCZOS), "face_small_dup.jpg")
    except Exception as e:
        print("  [skip] face samples: {}: {}".format(type(e).__name__, e))

    print("\n{} files written to {}".format(len(os.listdir(outdir)), outdir))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "testset")
    print("Building synthetic test set -> {}".format(out))
    build(out)
