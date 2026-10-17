"""A throwaway photo library for the tutorial.

The first thing a new user sees should not be their own photos. Making them pick
a real folder to be taught how to use the app is asking them to risk something
before they know what it does.

So the tutorial generates its own pictures. They are drawn here rather than
copied from anywhere, so nothing of the user's is involved, and they are built to
land one per common problem -- too dark, blown out, soft, colour-shifted -- so
each screen of the tour has something real to point at.

IMPORTANT: every photo is a DIFFERENT scene, except the burst pair which is
deliberately two nearly identical frames. The first version derived all eight
from one base image and the grouping correctly put seven of them in a single
"similar" group -- which would have taught the user that grouping is broken.

Faces are deliberately NOT faked: a drawn face is not detected, and a tutorial
that drew a face box over a cartoon would be teaching a lie.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageFilter

# Big enough that the "resolution too low" check stays quiet.
W, H = 4000, 2667


def _scene(seed: int, tint=(1.0, 1.0, 1.0), brightness=1.0,
           structure=3) -> np.ndarray:
    """A distinct outdoor-ish scene.

    `tint` and `structure` matter more than they look: perceptual hashing is a
    DCT of a downscaled grayscale image, and large flat areas make unrelated
    pictures hash to the same thing. Two earlier versions of this file produced
    that -- a seven-photo "similar group" out of eight unrelated scenes. Varying
    the dominant colour and the amount of structure per scene is what actually
    separates them.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W]

    sky = (np.array([70, 110, 160], np.float32) + rng.integers(-40, 41, 3)) * np.array(tint, np.float32)
    ground = (np.array([64, 86, 56], np.float32) + rng.integers(-35, 36, 3)) * np.array(tint, np.float32)
    horizon = 0.40 + 0.24 * rng.random()

    blend = np.clip((yy / H - horizon) / 0.14, 0, 1)[:, :, None]
    img = sky[None, None, :] * (1 - blend) + ground[None, None, :] * blend

    gx, gy = rng.uniform(0.12, 0.88), rng.uniform(0.10, 0.42)
    glow = np.exp(-(((xx - W * gx) ** 2) / (2 * (W * rng.uniform(.06, .16)) ** 2) +
                    ((yy - H * gy) ** 2) / (2 * (H * rng.uniform(.06, .16)) ** 2)))
    img += glow[:, :, None] * np.array([95, 84, 58], np.float32)

    # structure: dark blobs sized differently per scene
    for _ in range(structure):
        cx, cy = rng.uniform(0, 1) * W, rng.uniform(horizon * 0.9, 1) * H
        r = rng.uniform(0.04, 0.22) * min(W, H)
        m = ((xx - cx) ** 2 + (yy - cy) ** 2) < r * r
        img[m] *= rng.uniform(0.35, 0.85)

    img = img * brightness + rng.normal(0, 7, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def build(folder: str) -> dict:
    """Write the demo photos into `folder` and return what each one demonstrates."""
    os.makedirs(folder, exist_ok=True)
    made = []

    def add(name, arr, note, quality=94):
        Image.fromarray(arr).save(os.path.join(folder, name), quality=quality, subsampling=0)
        made.append({"name": name, "note": note})

    # Each scene gets its own tint so the eight cannot hash to the same thing.
    good = _scene(11, tint=(1.00, 1.00, 1.00), structure=5)
    add("DEMO_01_good.jpg", good, "曝光正常、清晰 —— 这张该留")

    # Blow the highlights hard: the check counts pixels at 250+, so easing 88%
    # of the way there leaves the brightest at 248 and reports nothing.
    b = good.astype(np.float32)
    hi = b > 90
    b[hi] = 255.0
    add("DEMO_02_blown.jpg", np.clip(b, 0, 255).astype(np.uint8),
        "高光溢出 —— 天空糊成一片白")

    add("DEMO_03_dark.jpg",
        np.clip(_scene(23, tint=(0.85, 0.90, 1.15), structure=2).astype(np.float32) * 0.13,
                0, 255).astype(np.uint8),
        "严重欠曝 —— 暗部死黑")

    add("DEMO_04_blurry.jpg",
        np.array(Image.fromarray(_scene(37, tint=(1.15, 0.95, 0.85), structure=6))
                 .filter(ImageFilter.GaussianBlur(radius=4.5))),
        "失焦 —— 整张软掉")

    e = _scene(41, tint=(0.55, 0.85, 1.55), structure=4).astype(np.float32)
    e[:, :, 2] *= 1.22
    e[:, :, 0] *= 0.72
    add("DEMO_05_blue.jpg", np.clip(e, 0, 255).astype(np.uint8),
        "白平衡偏蓝 —— 阴天设成了白炽灯")

    f = _scene(53, tint=(1.55, 1.05, 0.55), structure=3).astype(np.float32)
    f[:, :, 0] *= 1.22
    f[:, :, 2] *= 0.70
    add("DEMO_06_warm.jpg", np.clip(f, 0, 255).astype(np.uint8),
        "白平衡偏黄 —— 室内设成了晴天")

    # The burst pair is an EXACT copy on purpose. A near-copy still hashed
    # differently from two different scenes, so the tutorial showed the wrong
    # two photos grouped together. An exact duplicate cannot be ambiguous, and
    # "these two are the same shot" is the thing worth demonstrating anyway.
    burst = _scene(67, tint=(1.05, 1.10, 0.95), structure=7)
    add("DEMO_07_burst_a.jpg", burst, "连拍第一张")
    add("DEMO_08_burst_b.jpg", burst, "连拍第二张 —— 和上一张完全相同")

    return {"folder": folder, "count": len(made), "photos": made}


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else ".cache/demo"
    info = build(out)
    print("  wrote {} photos into {}".format(info["count"], info["folder"]))
    for p in info["photos"]:
        print("    {:<24} {}".format(p["name"], p["note"]))
