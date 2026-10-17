"""Perceptual hash. Pure numpy + PIL, no extra dependency.

pHash = DCT of the 32x32 greyscale image, keep the top-left 8x8 low-frequency
block (excluding the DC term), threshold on the median -> 64 bits.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n).reshape(-1, 1)
    x = np.arange(n).reshape(1, -1)
    return np.cos(np.pi * (2 * x + 1) * k / (2 * n))


_DCT32 = _dct_matrix(32)
_HASH_SIZE = 8


def phash_bytes(img: Image.Image) -> bytes:
    """64-bit perceptual hash as 8 bytes."""
    g = img.convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    return _hash_array(np.asarray(g, dtype=np.float32))


def phash_gray(gray: np.ndarray) -> bytes:
    """Same hash, computed from an already-decoded greyscale array.

    Reusing the greyscale image the metrics pass already produced avoids a
    second RGB resize/convert per photo.
    """
    im = Image.fromarray(gray).resize((32, 32), Image.Resampling.BOX)
    return _hash_array(np.asarray(im, dtype=np.float32))


def _hash_array(a: np.ndarray) -> bytes:
    d = _DCT32 @ a @ _DCT32.T
    low = d[:_HASH_SIZE, :_HASH_SIZE].copy()
    low[0, 0] = 0.0  # drop DC so overall brightness does not dominate
    bits = low > np.median(low)
    return np.packbits(bits.reshape(-1)).tobytes()


def phash_hex(img: Image.Image) -> str:
    return phash_bytes(img).hex()


_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def hamming(a: bytes, b: bytes) -> int:
    """Bit distance between two phash byte strings."""
    if not a or not b or len(a) != len(b):
        return 999
    x = np.frombuffer(a, dtype=np.uint8) ^ np.frombuffer(b, dtype=np.uint8)
    return int(_POPCOUNT[x].sum())
