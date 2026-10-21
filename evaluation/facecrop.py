"""从照片里裁出人脸框 —— 这里只是转发，实现在 guopian/imageio.py。

为什么只留一份：裁错一次会毁掉所有结论。我第一版把 faces 表的 (x, y, w, h)
当成中心点用了，每张脸往左上偏了半个框，于是表情模型"开心"的 Top32 全是
戴墨镜的人（墨镜刚好落在偏移后的框里），CLIP 的闭眼测试也是在偏移的裁切上
量的。所以裁切只有一个实现，分析流程和评测脚本都走它。
"""

from __future__ import annotations

import os
import sys

ROOT = r"E:\ai project\guopian"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from guopian.imageio import face_crop as crop  # noqa: E402,F401
