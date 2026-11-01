"""The demo photo library the tutorial uses.

The first thing a new user meets should not be their own photos. Making them pick
a real folder to be taught how to use the app is asking them to risk something
before they know what it does.

So the tutorial brings its own pictures. They are **rendered by this file and
committed under `guopian/assets/demo/`**; at runtime the tutorial only copies
them into a temp folder. Drawing them on demand took ~7 s and produced the exact
same bytes every time -- a strange thing to make the user wait for.

They are drawn rather than copied from anywhere, so nothing of the user's is
involved, and each one is built to land on one common problem -- too dark, blown
out, soft, colour-shifted -- so each screen of the tour has something real to
point at.

IMPORTANT: every photo is a DIFFERENT scene, except the burst pair which is
deliberately two identical frames. The first version derived all eight from one
base image and the grouping correctly put seven of them in a single "similar"
group -- which would have taught the user that grouping is broken.

Faces are deliberately NOT faked: a drawn face is not detected, and a tutorial
that drew a face box over a cartoon would be teaching a lie.

Two things this file learned the hard way:

  * "Blown highlights" means all three channels saturate together. Masking
    `img > 90` on an (H,W,3) array clips each CHANNEL separately, which turns a
    blue sky into cyan and leaves the grey level around 200 -- the picture then
    measures 1.5% clipped pixels and the app rightly says nothing is wrong. The
    mask has to be built from luminance.
  * Thresholds are relative to the shoot, so a demo of 8 photos cannot show a
    colour cast at all: `cast_ctx` needs at least 12 samples before a median
    means anything. The set is 12 for that reason, not for variety.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

import numpy as np
from PIL import Image, ImageFilter

# Above MIN_LONG_EDGE (2000) so the "resolution too low" check stays quiet, and
# small enough that the whole set stays a couple of megabytes in the repository:
# these images are committed under guopian/assets/demo/ and copied into a temp
# folder by the tutorial, instead of being drawn at runtime.
W, H = 2048, 1365

LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)

# One fixed sky and one fixed ground for the whole set.
#
# These used to be `base + rng.integers(-40, 41, 3)` -- a *per-channel* random
# offset, i.e. a random colour temperature per scene. The colour-cast check is
# judged against the median of the shoot, so with twelve photos those offsets
# spread "neutral" scenes across a range wide enough that the plainest photo in
# the set was flagged 偏冷 (measured: cast_b 1.42 against a median of 1.10, and
# a magnitude of 0.31 -- six times the 0.055 threshold). Scenes are told apart by
# their composition and brightness instead; only the two cast demos change
# colour, through `tint`.
SKY = np.array([84, 132, 196], np.float32)
GROUND = np.array([74, 96, 62], np.float32)


def _scene(seed: int, tint=(1.0, 1.0, 1.0), brightness=1.0,
           structure=3, grain: float = 2.5) -> np.ndarray:
    """A distinct outdoor-ish scene.

    `structure` matters more than it looks: perceptual hashing is a DCT of a
    downscaled grayscale image, and large flat areas make unrelated pictures
    hash to the same thing. Two earlier versions of this file produced that --
    a seven-photo "similar group" out of eight unrelated scenes. Varying the
    horizon, the sun and the number of dark blobs is what actually separates
    them now.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W]

    jitter = rng.uniform(-10, 10, 3).astype(np.float32)
    sky = (SKY + jitter) * np.array(tint, np.float32)
    ground = (GROUND + jitter) * np.array(tint, np.float32)
    horizon = 0.28 + 0.50 * rng.random()

    blend = np.clip((yy / H - horizon) / 0.14, 0, 1)[:, :, None]
    img = sky[None, None, :] * (1 - blend) + ground[None, None, :] * blend

    gx, gy = rng.uniform(0.12, 0.88), rng.uniform(0.10, 0.42)
    glow = np.exp(-(((xx - W * gx) ** 2) / (2 * (W * rng.uniform(.06, .16)) ** 2) +
                    ((yy - H * gy) ** 2) / (2 * (H * rng.uniform(.06, .16)) ** 2)))
    img += glow[:, :, None] * np.array([95, 84, 58], np.float32)

    # structure: dark ellipses, placed differently per scene
    for _ in range(structure):
        cx, cy = rng.uniform(0, 1) * W, rng.uniform(horizon * 0.9, 1) * H
        r = rng.uniform(0.03, 0.11) * min(W, H)
        rx, ry = r * rng.uniform(0.55, 1.8), r * rng.uniform(0.55, 1.8)
        m = (((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2) < 1.0
        img[m] *= rng.uniform(0.35, 0.85)

    img = img * brightness + rng.normal(0, grain, img.shape)

    # 低频"细节"。真实照片的细节不会接近零，而这些合成图是纯渐变 —— 于是 8×8
    # 块效应那个指标的分母只剩量化噪声，一张完全正常的照片会被判成
    # 「压缩痕迹明显」（实测 blockiness 1.7–2.0，阈值 1.6）。加一层波长几十像素、
    # 幅度几个灰阶的起伏，让它有真实照片量级的梯度，同时几乎不动逐像素差分
    # （噪点那个指标量的就是逐像素差分）。
    tex = (np.sin(xx / rng.uniform(26, 60) + rng.uniform(0, 6.28))
           + np.sin(yy / rng.uniform(30, 70) + rng.uniform(0, 6.28)))
    img = img + (tex * rng.uniform(2.5, 4.5))[:, :, None]
    return np.clip(img, 0, 255).astype(np.uint8)


def build(folder: str, quality: int = 94) -> dict:
    """Write the demo photos into `folder` and return what each one demonstrates.

    This is a **build-time** tool: the images in `guopian/assets/demo/` were made
    with it, and that folder is what the tutorial actually serves. Rendering them
    at runtime took ~7 s on a fast machine, which is a long time to stare at
    "正在准备演示照片…" for something that never changes.
    """
    os.makedirs(folder, exist_ok=True)
    made = []

    def add(name, arr, note, q=quality):
        # subsampling=2 (4:2:0) keeps the set small; these are flat synthetic
        # gradients, so the chroma loss is invisible and the colour-cast metric
        # is a global mean, which chroma subsampling barely touches.
        Image.fromarray(np.asarray(arr, dtype=np.uint8)).save(
            os.path.join(folder, name), quality=q, subsampling=2)
        made.append({"name": name, "note": note})

    # Each scene gets its own tint so the twelve cannot hash to the same thing.
    good = _scene(11, tint=(1.00, 1.00, 1.00), structure=5)
    add("DEMO_01_good.jpg", good, "曝光正常、清晰 —— 这张该过")

    # Blow the highlights **by luminance**, all three channels together, and at a
    # level between ground and sky.
    #
    # Two earlier versions got this wrong in ways that only a measurement showed:
    #   * `img > 90` on an (H,W,3) array clips each CHANNEL separately -- the blue
    #     sky turns cyan and its grey level stays around 200, which is not an
    #     overexposure by any measure (measured 1.6% of the frame clipped).
    #   * clipping the brightest N% of *pixels* puts the cut inside the sky's own
    #     narrow luminance band, so the mask is dithered by the film grain; the
    #     analysis downscales by 2.3x, which averages that dither back down to
    #     ~200 grey (measured: 25% of pixels were 255, but only 4.5% survived the
    #     resize as "highlight").
    # A fixed level well inside the gap between ground (~86) and sky (~125) gives
    # a solid white sky that survives both the encode and the resize.
    b = good.astype(np.float32)
    b[b @ LUMA >= 108] = 255.0
    add("DEMO_02_blown.jpg", b, "高光溢出 —— 天空糊成一片白")

    add("DEMO_03_dark.jpg",
        np.clip(_scene(23, tint=(0.85, 0.90, 1.10), structure=2).astype(np.float32) * 0.035,
                0, 255),
        "严重欠曝 —— 暗部死黑")

    add("DEMO_04_blurry.jpg",
        np.array(Image.fromarray(_scene(37, tint=(1.10, 0.97, 0.90), structure=6))
                 .filter(ImageFilter.GaussianBlur(radius=9))),
        "失焦 —— 整张软掉")

    noisy = _scene(43, tint=(0.97, 1.00, 1.03), structure=4).astype(np.float32)
    # Grain is the one thing JPEG cannot compress, and this file alone was half
    # the set's size at 26. 16 still measures as clearly noisy (the threshold is
    # ~1.2 and the rest of the set reads 0).
    noisy += np.random.default_rng(43).normal(0, 16, noisy.shape)
    add("DEMO_05_noisy.jpg", noisy, "噪点高 —— 暗处一片颗粒")

    # 色温只在这两张上偏移：蓝 = 压低红、抬高蓝，黄 = 反过来。
    # 其余场景共用同一个天和地，彼此的色偏差异在阈值以下。
    e = _scene(41, tint=(0.72, 0.92, 1.30), structure=4).astype(np.float32)
    add("DEMO_06_blue.jpg", e, "白平衡偏蓝 —— 阴天设成了白炽灯")

    f = _scene(53, tint=(1.78, 1.00, 0.60), structure=3).astype(np.float32)
    add("DEMO_07_warm.jpg", f, "白平衡偏黄 —— 室内设成了晴天")

    # Flat: pull everything towards mid-grey, which is what a hazy day looks like.
    flat = _scene(59, tint=(1.02, 1.02, 0.98), structure=3).astype(np.float32)
    flat = flat * 0.35 + 128 * 0.65
    add("DEMO_08_flat.jpg", flat, "发灰、对比度低 —— 雾霾天")

    # The burst pair is an EXACT copy on purpose. A near-copy still hashed
    # differently from two different scenes, so the tutorial showed the wrong
    # two photos grouped together. An exact duplicate cannot be ambiguous, and
    # "these two are the same shot" is the thing worth demonstrating anyway.
    burst = _scene(67, tint=(1.04, 1.08, 0.98), structure=7)
    add("DEMO_09_burst_a.jpg", burst, "连拍第一张")
    add("DEMO_10_burst_b.jpg", burst, "连拍第二张 —— 和上一张完全相同")

    # Two more scenes twice over: the colour-cast check is judged against the
    # median of the shoot and refuses to run below 12 samples.
    add("DEMO_11_scene.jpg", _scene(71, tint=(0.97, 1.02, 1.0), structure=5),
        "普通一张 —— 用来凑够同场比较的样本")
    add("DEMO_12_scene.jpg", _scene(79, tint=(1.02, 1.00, 0.97), structure=4),
        "普通一张 —— 用来凑够同场比较的样本")

    return {"folder": folder, "count": len(made), "photos": made}


def assets_dir() -> str:
    """The pre-rendered set that ships with the app."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "demo")


def copy_to_temp() -> str:
    """Copy the shipped demo photos into a fresh temp folder and return it.

    Copying twelve files is a few milliseconds; drawing them is ~7 s, and this
    is the same set every time. The library's catalog is written inside the same
    folder, so one `shutil.rmtree` removes photos, catalog and thumbnails
    together -- nothing is written to the user's data directory and nothing can
    end up in "recent".
    """
    src = assets_dir()
    names = [n for n in sorted(os.listdir(src)) if n.lower().endswith(".jpg")] \
        if os.path.isdir(src) else []
    if not names:
        raise FileNotFoundError("演示照片不见了: {}".format(src))
    folder = tempfile.mkdtemp(prefix="guopian-demo-")
    for name in names:
        shutil.copy2(os.path.join(src, name), os.path.join(folder, name))
    return folder


def cleanup(path: str | None) -> bool:
    """Delete a demo folder. Returns True when it is really gone.

    The retry loop is not decoration: the analysis thread opens its own sqlite
    connection per thread, and on Windows a connection that has not been
    collected yet keeps `catalog.db` locked. A single `rmtree` then fails
    silently, and the folder -- photos, catalog, thumbnails -- stays behind in
    %TEMP% after the user was told the demo had been deleted. Measured: the very
    first run left `guopian-demo-*` behind every time without this loop.
    """
    if not path:
        return True
    name = os.path.basename(os.path.abspath(path))
    if not name.startswith("guopian-demo-"):
        return False                 # never delete anything that is not ours
    import gc

    for attempt in range(5):
        gc.collect()
        try:
            shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(0.15 * (attempt + 1))
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.exists(path)


def cleanup_stale(max_age_hours: float = 12.0) -> int:
    """Remove demo folders left behind by a crash or a closed window."""
    root = tempfile.gettempdir()
    now = time.time()
    gone = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        if not name.startswith("guopian-demo-"):
            continue
        p = os.path.join(root, name)
        try:
            if not os.path.isdir(p) or now - os.path.getmtime(p) < max_age_hours * 3600:
                continue
        except OSError:
            continue
        shutil.rmtree(p, ignore_errors=True)
        gone += 1
    return gone


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else ".cache/demo"
    info = build(out)
    print("  wrote {} photos into {}".format(info["count"], info["folder"]))
    for p in info["photos"]:
        print("    {:<24} {}".format(p["name"], p["note"]))
