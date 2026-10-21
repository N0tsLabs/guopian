"""从照片里裁出人脸框 —— 只有这一处，因为裁错一次会毁掉所有结论。

faces 表里的 (x, y, w, h) 是**左上角 + 尺寸**（归一化），不是中心点。
我第一版把它当成中心点用了，于是每张脸都往左上偏了半个框：跑表情模型时
"开心"的 Top32 全是戴墨镜的人（墨镜刚好在偏移后的框里），CLIP 的闭眼测试
也是在同一批偏移的裁切上做的。这个函数就是来堵这个洞的。
"""

from __future__ import annotations

from PIL import Image, ImageOps


def tight_box(box: dict, width: int, height: int, margin: float = 0.15):
    """归一化的 (x,y,w,h) -> 像素 (left, top, right, bottom)，四周留 margin 比例。"""
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    left = x * width
    top = y * height
    fw = w * width
    fh = h * height
    cx = left + fw / 2.0
    cy = top + fh / 2.0
    half_w = fw * (1.0 + margin) / 2.0
    half_h = fh * (1.0 + margin) / 2.0
    return (int(max(0, cx - half_w)), int(max(0, cy - half_h)),
            int(min(width, cx + half_w)), int(min(height, cy + half_h)))


def crop(im: Image.Image, box: dict, margin: float = 0.15) -> Image.Image:
    im = ImageOps.exif_transpose(im).convert("RGB")
    return im.crop(tight_box(box, im.width, im.height, margin))
