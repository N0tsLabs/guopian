"""Image loading, EXIF, and the on-disk thumbnail cache.

Design rules (see docs/03):
  * never decode at full resolution just to build a thumbnail
  * RAW files are read via their embedded JPEG preview, never demosaiced
  * every preview is cached under <library>/.guopian/thumbs/
"""

from __future__ import annotations

import hashlib
import io
import os
from typing import Any

from PIL import Image, ImageOps

from . import config

try:  # optional: HEIC/HEIF
    import pillow_heif

    pillow_heif.register_heif_opener()
    HAVE_HEIF = True
except Exception:  # pragma: no cover
    HAVE_HEIF = False

try:
    import pillow_avif  # noqa: F401

    HAVE_AVIF = True
except Exception:  # pragma: no cover
    HAVE_AVIF = False


RAW_EXT = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".pef", ".srw"}

# Pillow refuses very large images by default; holiday panoramas exceed it.
Image.MAX_IMAGE_PIXELS = 600_000_000


# ------------------------------------------------------------------ RAW

def extract_embedded_jpeg(path: str, max_bytes: int = 64 << 20) -> bytes | None:
    """Pull the largest JPEG preview out of a RAW container.

    Cheaper and more robust than demosaicing, and it is exactly what culling
    needs. Returns None when the container has no usable preview.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            data = f.read(min(size, max_bytes))
    except OSError:
        return None

    best: bytes | None = None
    i = 0
    n = len(data)
    while True:
        start = data.find(b"\xff\xd8\xff", i)
        if start < 0:
            break
        end = data.find(b"\xff\xd9", start + 3)
        if end < 0:
            break
        seg = data[start:end + 2]
        if best is None or len(seg) > len(best):
            best = seg
        i = end + 2
        if len(best) > 8 << 20:  # good enough, stop scanning
            break
    return best


# ------------------------------------------------------------------ EXIF

_EXIF_TAGS = {
    0x010F: "camera_make", 0x0110: "camera_model", 0x0112: "orientation",
    0x0132: "datetime",
}
_EXIF_IFD_TAGS = {
    0x9003: "datetime_original", 0x9004: "datetime_digitized",
    0x829A: "exposure_time", 0x829D: "fnumber", 0x8827: "iso",
    0x920A: "focal_length", 0xA434: "lens_model",
    0xA002: "pixel_x", 0xA003: "pixel_y",
}


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", "ignore").strip("\x00 ")
        except Exception:
            return None
    if isinstance(v, str):
        return v.strip("\x00 ")
    if isinstance(v, (tuple, list)):
        return v[0] if len(v) == 1 else v
    return v


def read_exif(img: Image.Image) -> dict:
    out: dict[str, Any] = {}
    try:
        exif = img.getexif()
    except Exception:
        return out
    if not exif:
        return out

    for tag, name in _EXIF_TAGS.items():
        v = _clean(exif.get(tag))
        if v is not None:
            out[name] = v

    try:
        from PIL.ExifTags import IFD

        sub = exif.get_ifd(IFD.Exif)
        for tag, name in _EXIF_IFD_TAGS.items():
            v = _clean(sub.get(tag))
            if v is not None:
                out[name] = v
    except Exception:
        pass

    make = out.get("camera_make")
    model = out.get("camera_model")
    if model and make and not str(model).lower().startswith(str(make).lower()[:4]):
        out["camera"] = "{} {}".format(make, model)
    else:
        out["camera"] = model or make

    dt = out.get("datetime_original") or out.get("datetime_digitized") or out.get("datetime")
    out["taken_at"] = str(dt) if dt else None

    et = out.get("exposure_time")
    if et is not None:
        try:
            f = float(et)
            out["shutter"] = "1/{:.0f}".format(1.0 / f) if 0 < f < 1 else "{:.1f}s".format(f)
        except Exception:
            out["shutter"] = str(et)
    fn = out.get("fnumber")
    if fn is not None:
        try:
            out["aperture"] = float(fn)
        except Exception:
            pass
    fl = out.get("focal_length")
    if fl is not None:
        try:
            out["focal"] = float(fl)
        except Exception:
            pass
    iso = out.get("iso")
    if iso is not None:
        try:
            out["iso"] = int(iso)
        except Exception:
            pass
    return out


def _parse_taken_ts(taken_at: str | None) -> float | None:
    if not taken_at:
        return None
    import datetime as _dt

    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S.%f"):
        try:
            return _dt.datetime.strptime(str(taken_at)[:26], fmt).timestamp()
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ open

JPEG_EXT = {".jpg", ".jpeg", ".jpe"}


def open_image(path: str, max_edge: int | None = None) -> tuple[Image.Image, bool, float]:
    """Open any supported file.

    Returns (RGB image, was_raw_preview, decode_scale) where decode_scale is
    decoded_size / original_size. For JPEG we use libjpeg's scaled DCT decode
    (`Image.draft`) so a 6000x4000 file is never fully materialised -- that is
    the single biggest speed win in the whole pipeline.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in RAW_EXT:
        blob = extract_embedded_jpeg(path)
        if blob:
            img = Image.open(io.BytesIO(blob))
            ow, oh = img.size
            if max_edge and max(ow, oh) > max_edge:
                img.draft("RGB", (max_edge, max_edge))
            img.load()
            img = ImageOps.exif_transpose(img).convert("RGB")
            return img, True, max(img.size) / float(max(ow, oh))
        try:  # last resort: rawpy if the user installed it
            import rawpy

            with rawpy.imread(path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=True)
            return Image.fromarray(rgb), True, 0.5
        except Exception as e:
            raise OSError("cannot read RAW {} ({})".format(os.path.basename(path), e))

    img = Image.open(path)
    ow, oh = img.size
    if max_edge and ext in JPEG_EXT and max(ow, oh) > max_edge:
        # libjpeg only supports 1/1, 1/2, 1/4, 1/8; it picks the smallest that
        # still covers the request.
        img.draft("RGB", (max_edge, max_edge))
    img.load()
    img = ImageOps.exif_transpose(img).convert("RGB")
    scale = max(img.size) / float(max(ow, oh)) if ow and oh else 1.0
    return img, False, scale


# ------------------------------------------------------------------ thumbs

class ThumbCache:
    """Thumbnail/preview cache on disk, keyed by (identity, edge)."""

    def __init__(self, work_dir: str):
        self.dir = os.path.join(work_dir, "thumbs")
        os.makedirs(self.dir, exist_ok=True)

    def key(self, path: str, size: int, mtime: float, edge: int) -> str:
        h = hashlib.sha1(
            "{}|{}|{}|{}".format(os.path.abspath(path), size, int(mtime), edge).encode()
        ).hexdigest()[:20]
        return h

    def bucket(self, key: str) -> str:
        return key[:2]

    def path_for(self, key: str, edge: int) -> str:
        b = os.path.join(self.dir, self.bucket(key))
        os.makedirs(b, exist_ok=True)
        return os.path.join(b, "{}_{}.jpg".format(key, edge))

    def get_or_build(self, src_path: str, size: int, mtime: float, edge: int) -> str:
        key = self.key(src_path, size, mtime, edge)
        dest = self.path_for(key, edge)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest
        # Decode straight to (roughly) the target size instead of loading the
        # full-resolution file and shrinking it afterwards.
        img, _, _ = open_image(src_path, max_edge=max(edge, 1024))
        img = img.copy()
        img.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        tmp = dest + ".tmp"
        img.save(tmp, "JPEG", quality=88, optimize=True, progressive=True)
        os.replace(tmp, dest)
        return dest
