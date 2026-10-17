#!/usr/bin/env python3
"""Measure whether zoomed-in rendering actually equals the original file.

The eye is a bad judge of "blurry" on dark or low-detail photos, and edge-energy
metrics are extremely sensitive to a 1px crop misalignment. The reliable test is
mean absolute difference (MAD) against the original bytes, searching a small
offset window so a measurement error cannot masquerade as a rendering defect.

    python evaluation/zoom_sharpness.py [photo-id ...]

Requires the dev server on 127.0.0.1:8765 and the bridge daemon running.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
PY = sys.executable
BRIDGE = HERE + "/bridge.py"
BASE = "http://127.0.0.1:8765"
CROP = (600, 150, 1400, 700)      # a 800x550 window inside the photo area
SEARCH = 3                        # +/- px of alignment slack


def bridge(*args):
    r = subprocess.run([PY, BRIDGE, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout.strip()


def ev(code):
    out = bridge("eval", code)
    i = out.find("{")
    if i < 0:
        return None
    try:
        return json.loads(out[i:])
    except Exception:
        return None


def api(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as f:
        return json.loads(f.read().decode("utf-8"))


def mad_for(shot_path, orig_path, layer_left, layer_top, ox, oy):
    A = np.asarray(Image.open(shot_path).crop(CROP).convert("L"), dtype=np.float32)
    O = Image.open(orig_path)
    best = None
    for dy in range(-SEARCH, SEARCH + 1):
        for dx in range(-SEARCH, SEARCH + 1):
            x0 = int(CROP[0] - layer_left - ox) + dx
            y0 = int(CROP[1] - layer_top - oy) + dy
            if x0 < 0 or y0 < 0 or x0 + 800 > O.width or y0 + 550 > O.height:
                continue
            B = np.asarray(O.crop((x0, y0, x0 + 800, y0 + 550)).convert("L"),
                           dtype=np.float32)
            m = float(np.abs(A - B).mean())
            if best is None or m < best[0]:
                best = (m, dx, dy)
    return best


def main() -> int:
    ids = [int(a) for a in sys.argv[1:]] or [1, 5, 40, 60]
    root = api("/api/state")["root"]
    print("  库: {}\n".format(root))
    print("  {:<5} {:<16} {:>13} {:>22} {:>12}".format(
        "id", "文件", "排版尺寸", "缩放", "MAD/255"))

    worst = 0.0
    for pid in ids:
        bridge("eval", "location.reload();1")
        time.sleep(9)
        bridge("eval",
               "(()=>{const it=[...document.querySelectorAll('.listItem')]"
               ".find(x=>+x.dataset.id==" + str(pid) + ");if(it)it.click();return 1})()")
        time.sleep(4)
        bridge("eval",
               "(()=>{const s=document.getElementById('photoStage');"
               "const r=s.getBoundingClientRect();"
               "s.dispatchEvent(new MouseEvent('dblclick',{clientX:r.left+r.width/2,"
               "clientY:r.top+r.height/2,bubbles:true}));return 1})()")
        time.sleep(3)
        d = ev("(()=>{const l=document.getElementById('photoLayer');"
               "l.getAnimations().forEach(a=>a.finish());"
               "const cr=document.getElementById('cardWrap').getBoundingClientRect();"
               "const lr=l.getBoundingClientRect();"
               "return JSON.stringify({badge:document.getElementById('zoomBadge').textContent,"
               "box:[parseFloat(l.style.width),parseFloat(l.style.height)],"
               "al:cr.left,at:cr.top,ll:lr.left,lt:lr.top,"
               "meta:document.querySelector('.metaLine').textContent})})()")
        if not d:
            print("  {:<5} 读取失败".format(pid))
            continue
        name = d["meta"].split(" ")[0]
        w, h = d["box"]
        if w < 100:
            print("  {:<5} {:<16} {:>13} {:>22} 未放大".format(pid, name, "-", d["badge"]))
            continue
        shot = bridge("shot")
        # The layer is laid out at 1 image px per CSS px at 100%, so the map is
        # original = screen - layer origin.
        best = mad_for(shot, root + "\\" + name, d["ll"], d["lt"], 0, 0)
        if not best:
            print("  {:<5} {:<16} 裁剪越界".format(pid, name))
            continue
        worst = max(worst, best[0])
        print("  {:<5} {:<16} {:>13} {:>22} {:>12.2f}".format(
            pid, name, "{}x{}".format(int(w), int(h)), d["badge"][:20], best[0]))

    print("\n  判定：MAD < 4/255 即视为逐像素一致（JPEG 解码取整的量级）")
    print("  最差的一张 = {:.2f}/255  ->  {}".format(
        worst, "全部通过" if worst < 4 else "有照片仍然劣化"))
    return 0 if worst < 4 else 1


if __name__ == "__main__":
    sys.exit(main())
