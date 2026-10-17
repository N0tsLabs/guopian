/* 过片 Guopian — 照片上的三种叠加信息：人脸框、直方图、过曝斑马纹。
 *
 * 为什么单独成模块：它们都从"用户真正在看的那张位图"出发（visibleImage），
 * 都是只读的绘图，都不改变任何状态。三块放一起是因为它们共享同一个前提：
 * 全分辨率层没到之前，画的是预览层 —— 这个判断只写一次。
 *
 * @requires ./state.js   el S V
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */

import { el, S, V } from './state.js';

/* ═════════════════════════ overlays ═════════════════════════ */

function renderOverlay() {
  if (!S.showOverlay || !S.detail || !S.detail.faces) {
    el.overlay.innerHTML = '';
    el.overlay.classList.add('hidden');
    return;
  }
  el.overlay.classList.remove('hidden');
  const parts = [];
  for (const f of S.detail.faces) {
    const yaw = Math.abs(f.yaw || 0);
    const closed = Math.max(f.blink_l || 0, f.blink_r || 0) >= 0.55;
    const col = closed ? '#ff5c57' : (yaw > 32 ? '#8b949e' : '#58a6ff');
    parts.push(`<rect x="${f.x}" y="${f.y}" width="${f.w}" height="${f.h}" fill="none"
      stroke="${col}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>`);
    const lm = f.landmarks || {};
    for (const [key, bv] of [['r_eye', f.blink_r], ['l_eye', f.blink_l]]) {
      const b = lm[key];
      if (!b) continue;
      const v = bv || 0;
      const c = v >= 0.55 ? '#ff5c57' : (v >= 0.30 ? '#e3b341' : '#7ee787');
      parts.push(`<rect x="${b[0]}" y="${b[1]}" width="${b[2]}" height="${b[3]}" fill="none"
        stroke="${c}" stroke-width="1.4" vector-effect="non-scaling-stroke"/>`);
    }
  }
  el.overlay.innerHTML = parts.join('');
}

/** The image the user is actually looking at (HD layer when it has landed). */
function visibleImage() {
  return (V.fullReady && el.photoHD.naturalWidth) ? el.photoHD : el.photo;
}

function drawHistogram() {
  const cv = el.histoCanvas, ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);
  const img = visibleImage();
  if (!img.naturalWidth) return;
  const sw = 220, sh = Math.max(1, Math.round(sw * img.naturalHeight / img.naturalWidth));
  const tmp = document.createElement('canvas');
  tmp.width = sw; tmp.height = sh;
  const tc = tmp.getContext('2d');
  tc.drawImage(img, 0, 0, sw, sh);
  let data;
  try { data = tc.getImageData(0, 0, sw, sh).data; } catch (e) { return; }
  const bins = new Array(64).fill(0);
  for (let i = 0; i < data.length; i += 4) {
    const y = (data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) | 0;
    bins[y >> 2]++;
  }
  const max = Math.max(1, ...bins);
  for (let i = 0; i < 64; i++) {
    const h = bins[i] / max * (H - 6);
    let color = '#7d8590';
    if (i >= 62) color = '#f0883e';
    if (i <= 1) color = '#58a6ff';
    ctx.fillStyle = color;
    ctx.fillRect(i / 64 * W, H - h, Math.max(1, W / 64 - 0.6), h);
  }
}

function buildZebra() {
  const img = visibleImage();
  if (!img.naturalWidth) return;
  const sw = Math.min(1000, img.naturalWidth);
  const sh = Math.max(1, Math.round(sw * img.naturalHeight / img.naturalWidth));
  const tmp = document.createElement('canvas');
  tmp.width = sw; tmp.height = sh;
  const tc = tmp.getContext('2d', { willReadFrequently: true });
  tc.drawImage(img, 0, 0, sw, sh);
  let d;
  try { d = tc.getImageData(0, 0, sw, sh); } catch (e) { return; }
  const px = d.data, out = tc.createImageData(sw, sh), o = out.data;
  for (let y = 0; y < sh; y++) {
    for (let x = 0; x < sw; x++) {
      const i = (y * sw + x) * 4;
      const lum = px[i] * 0.299 + px[i + 1] * 0.587 + px[i + 2] * 0.114;
      const blow = lum >= 250, crush = lum <= 5;
      if ((blow || crush) && ((x + y) % 12 < 6)) {
        o[i] = blow ? 255 : 40; o[i + 1] = blow ? 190 : 120;
        o[i + 2] = blow ? 40 : 255; o[i + 3] = 210;
      }
    }
  }
  const z = el.zebra;
  z.width = sw; z.height = sh;
  z.getContext('2d').putImageData(out, 0, 0);
  z.classList.remove('hidden');
}

export { renderOverlay, visibleImage, drawHistogram, buildZebra
};
