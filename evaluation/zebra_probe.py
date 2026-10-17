import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shot  # noqa: E402

# Loads the REAL stylesheet, so this tests the shipped .zebra rule rather than a
# copy of it. The left panel re-applies the old mix-blend-mode inline.
PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/style.css">
<style>
  body{margin:0;background:#0b0c0e;font:12px var(--ui);color:#a2a7ae;padding:16px}
  .pair{display:flex;gap:18px}
  .box{width:300px}
  .frame{position:relative;width:300px;height:170px;background:#fbfbfb;border-radius:6px;overflow:hidden}
  .cap{margin:7px 0 0}
  .old{mix-blend-mode:screen}
</style></head><body>
<div class="pair">
  <div class="box"><div class="frame" id="f1"><canvas id="c1" class="zebra"></canvas></div>
    <div class="cap">旧：mix-blend-mode: screen</div></div>
  <div class="box"><div class="frame" id="f2"><canvas id="c2" class="zebra"></canvas></div>
    <div class="cap">新：不改混合模式</div></div>
</div>
<script>
// Exactly what buildZebra() paints: yellow stripes, alpha 210.
function paint(id) {
  const c = document.getElementById(id);
  c.width = 300; c.height = 170;
  const x = c.getContext('2d');
  x.fillStyle = 'rgba(255,190,40,0.82)';
  for (let y = 0; y < 170; y++)
    for (let px = 0; px < 300; px++)
      if ((px + y) % 12 < 6) x.fillRect(px, y, 1, 1);
}
paint('c1'); paint('c2');
// put the old blend mode back on the left panel only
document.getElementById('c1').classList.add('old');
</script></body></html>"""


def main() -> int:
    b = shot.find_browser()
    if not b:
        print("no browser")
        return 2
    dest = os.path.join(shot.ROOT, "web", "_zp.html")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(PAGE)
    try:
        out = os.path.abspath(os.path.join(shot.ROOT, "docs", "img", "zebra.png"))
        ok = shot.shoot(b, "http://127.0.0.1:8765/_zp.html", out, 700, 260)
        if not ok:
            print("  screenshot failed")
            return 1
        from PIL import Image
        im = Image.open(out).convert("RGB")
        # sample inside a stripe in each frame
        left = im.getpixel((40, 40))
        right = im.getpixel((370, 40))
        print("\n  背景 #fbfbfb，等于一条过曝高光")
        print("  旧（screen）  取到的像素 RGB{}".format(left))
        print("  新（不混合）  取到的像素 RGB{}".format(right))
        d = sum(abs(a - b) for a, b in zip(left, right))
        print("\n  差异 {}".format(d))
        print("  " + ("screen 把黄色洗掉了 —— 这就是看不见的原因"
                      if d > 60 else "两者接近，混合模式不是原因"))
    finally:
        os.remove(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
