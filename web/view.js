/* 过片 Guopian — 视口几何：适应窗口、缩放、平移、滚轮与双击手势。
 *
 * 为什么单独成模块：这一整块只依赖 V（尺寸/比例/缩放）和 DOM 的边框盒，
 * 是纯几何，和队列、决策、卡片内容都没有关系。把它和渲染混在一起，
 * 就会出现"改一下缩放下限，结果碰到了列表"这种耦合。
 *
 * @requires ./state.js   el V cur —— 读 DOM 缓存、读写视口几何
 *
 * 唯一一条向上的线是 placeStamp()：fitStage() 算完盒子之后要把手势印章
 * 重新贴到照片上，而 placeStamp 住在 card.js。card.js 反过来过 import
 * fitStage()，直接互相 import 就成环了，所以用 configure() 注入。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */

import { el, V, cur } from './state.js';

/* ═════════════════════════ 缩放 / 平移 ═════════════════════════ */

function fitStage() {
  const wrap = el.cardWrap.getBoundingClientRect();
  const nw = el.photo.naturalWidth, nh = el.photo.naturalHeight;
  // Prefer the catalogue's dimensions over the loaded preview's.
  //
  // Two reasons, and both matter. The original is the right aspect ratio:
  // 1600x1067 and 6000x4000 differ in the third decimal, and that is enough
  // for object-fit:contain to letterbox by a fraction of a pixel, which makes
  // the compositor resample the entire photo (measured 0.85x edge energy with
  // the preview's aspect, 1.00x with the original's). And unlike naturalWidth
  // they are known the moment a photo is RENDERED, so this can lay out before
  // the preview arrives -- otherwise the arriving card kept the previous
  // photo's box for the ~250ms the preview took to load, and then got resized
  // part-way through its arrival animation.
  const ow = V.origW || nw, oh = V.origH || nh;
  if (!ow || !oh) return;
  const aw = Math.max(80, wrap.width - 40), ah = Math.max(80, wrap.height - 40);
  V.areaW = Math.max(1, wrap.width); V.areaH = Math.max(1, wrap.height);
  V.aspect = ow / oh;
  let bw = Math.min(aw, ah * V.aspect);
  let bh = bw / V.aspect;
  if (bh > ah) { bh = ah; bw = bh * V.aspect; }
  V.bw = Math.max(40, bw); V.bh = Math.max(40, bh);
  if (!V.fullReady && nw && nh) { V.natW = nw; V.natH = nh; }
  if (!V.origW && nw && nh) { V.origW = nw; V.origH = nh; }
  resetView(false);
  // render() runs before the image has decoded, so V.bw is still 0 at that
  // point and the stack peek would never get sized. This is the first moment
  // the geometry is actually known.
  placeStamp();
}

/** Offset that centres content of size (w,h) inside the viewport. */
function centred(w, h) {
  return { x: (V.areaW - w) / 2, y: (V.areaH - h) / 2 };
}

/** Size of the image layer at scale s. Height always follows from the exact
    aspect so the box can never disagree with the photo's ratio. */
function layerSize(s) {
  const w = V.bw * s;
  return { w, h: w / (V.aspect || 1) };
}

/* Pan is symmetric around centre: at scale s the content is bw*s wide and
   the viewport areaW, so it may travel (bw*s - areaW)/2 either way before an
   edge would show. Zero when the content already fits. */
function clampPan(tx, ty, s) {
  const z = layerSize(s);
  const mx = Math.max(0, (z.w - V.areaW) / 2);
  const my = Math.max(0, (z.h - V.areaH) / 2);
  return {
    tx: Math.min(mx, Math.max(-mx, tx)),
    ty: Math.min(my, Math.max(-my, ty)),
  };
}

/** Largest scale at which the loaded file still has real pixels to show. */
function nativeScaleCap() {
  if (!V.bw || !V.natW) return 10;
  return Math.max(1, V.natW / V.bw);
}

function updateZoomBadge() {
  if (V.s <= 1.02) { el.zoomBadge.classList.add('hidden'); return; }
  el.zoomBadge.classList.remove('hidden');
  const pct = V.origW ? Math.round((V.bw * V.s) / V.origW * 100)
                      : Math.round(V.s * 100);
  const parts = [`${pct}%`];
  if (V.origW && V.natW && V.natW < V.origW * 0.98) {
    // RAW/HEIC: we are showing the largest preview we could extract, so say so
    parts.push(V.fullReady ? '预览' : '预览加载中');
  }
  parts.push('双击复位');
  el.zoomBadge.textContent = parts.join('  ·  ');
}

function applyView(instant) {
  if (!V.bw) return;
  // Height is derived from width through the exact aspect, never rounded
  // independently -- the box must match the photo's ratio precisely or
  // object-fit resamples.
  const w = V.bw * V.s, h = w / (V.aspect || (V.origW / V.origH) || 1);
  const o = centred(w, h);
  el.photoLayer.classList.toggle('nofx', !!instant);
  el.photoLayer.style.width = w.toFixed(3) + 'px';
  el.photoLayer.style.height = h.toFixed(3) + 'px';
  el.photoLayer.style.transform =
    `translate(${(o.x + V.tx).toFixed(2)}px,${(o.y + V.ty).toFixed(2)}px)`;
  el.photoStage.classList.toggle('zoomed', V.s > 1.02);
  updateZoomBadge();
}

function resetView(instant) {
  V.s = 1; V.tx = 0; V.ty = 0;
  applyView(instant === undefined ? true : instant);
}

/** Cap: never scale past 1 image pixel = 1 screen pixel. Zooming into
    interpolation is just a blur with extra steps. */
function maxScale() {
  return Math.max(1.02, nativeScaleCap());
}

function zoomAt(cx, cy, factor, animate) {
  if (!V.bw) return;
  const ns = Math.min(maxScale(), Math.max(1, V.s * factor));
  if (Math.abs(ns - V.s) < 1e-4) return;
  const a = el.cardWrap.getBoundingClientRect();
  const sx = cx - a.left, sy = cy - a.top;      // viewport-local
  const z0 = layerSize(V.s);
  const o0 = centred(z0.w, z0.h);
  const ux = (sx - o0.x - V.tx) / V.s;           // image-local, 0..bw
  const uy = (sy - o0.y - V.ty) / V.s;
  const z1 = layerSize(ns);
  const o1 = centred(z1.w, z1.h);
  const p = clampPan(sx - o1.x - ux * ns, sy - o1.y - uy * ns, ns);
  V.s = ns; V.tx = p.tx; V.ty = p.ty;
  applyView(!animate);
}

/** Current resting transform of the image layer, plus an extra screen offset. */
function layerTransform(dx, dy, rot) {
  const z = layerSize(V.s);
  const o = centred(z.w, z.h);
  const x = (o.x + V.tx + (dx || 0)).toFixed(2);
  const y = (o.y + V.ty + (dy || 0)).toFixed(2);
  return `translate(${x}px,${y}px)` + (rot ? ` rotate(${rot}deg)` : '');
}

function setCardOffset(dx, rot) {
  el.photoCard.style.setProperty('--sx', (dx || 0).toFixed(1) + 'px');
  el.photoCard.style.setProperty('--sr', (rot || 0).toFixed(2) + 'deg');
}

function onWheel(e) {
  if (!cur() || !V.bw) return;
  e.preventDefault();
  zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0016), false);
}

function onDblClick(e) {
  if (!cur()) return;
  if (V.s > 1.02) { resetView(true); return; }
  // 100% means one pixel of the ORIGINAL photo per screen pixel.
  const target = V.origW ? (V.origW / V.bw) : maxScale();
  zoomAt(e.clientX, e.clientY, Math.min(target, maxScale()) / V.s, true);
}

/* ───────────────────── 注入：布局完成之后要把印章贴回去 ─────────────────────

   fitStage() 的最后一行调用 placeStamp()，而它住在 card.js；card.js 又必须
   import 这里的 fitStage()。两个模块互相 import 就是循环依赖 —— 浏览器会
   允许，但它让求值顺序变得不可预测，而顺序正是这次重构要消灭的东西。

   所以这里留一个同名占位符（名字不变，fitStage 的函数体就一个字都不用改），
   由 app.js 在装配时注入真正的实现。装之前是空的：加载期不会有人调用
   fitStage()，只有渲染之后才会。 */
let placeStamp = () => {};
function configure(hooks) {
  if (hooks && hooks.placeStamp) placeStamp = hooks.placeStamp;
}


export { fitStage, centred, layerSize, clampPan, nativeScaleCap,
  updateZoomBadge, applyView, resetView, maxScale, zoomAt, layerTransform,
  setCardOffset, onWheel, onDblClick, configure
};
