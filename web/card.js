/* 过片 Guopian — 卡片本身：预览、原图、建议、问题标签、元信息。
 *
 * 为什么单独成模块：这一块是"一张照片怎么显示"，是改动最频繁的地方，
 * 也是唯一需要同时读 S/V/LABEL/VERDICT/OWNED 的地方。把它和网格、对话框、
 * 键位分开，改版式的人就不用经过决策流程。
 *
 * @requires ./state.js      el S V cur LABEL VERDICT OWNED
 * @requires ./core.js       $ api esc
 * @requires ./view.js       fitStage centred updateZoomBadge
 * @requires ./histogram.js  drawHistogram renderOverlay buildZebra
 * @requires ./list.js       highlightCurrent savePos
 *
 * 一处向上的调用用 configure() 注入：render() 开头要清掉上一次"按住预览"
 * 的残留，而那一整套视觉状态（含 hold）的生命周期在 app.js —— 它要跨
 * flyOut / endHold 好几个阶段。为这一个函数 import app.js 会成环。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */

import { el, S, V, cur, LABEL, VERDICT, OWNED } from './state.js';
import { $, api, esc, imgUrl } from './core.js';
import { fitStage, centred, updateZoomBadge } from './view.js';
import { drawHistogram, renderOverlay, buildZebra } from './histogram.js';
import { highlightCurrent, savePos } from './list.js';

/* ═════════════════════════ 卡片 ═════════════════════════ */

function render() {
  const c = cur();
  if (!c) {
    el.photoStage.classList.add('hidden');
    el.emptyState.classList.remove('hidden');
    el.emptyTitle.textContent = S.queue.length === 0
      ? (S.filter === 'all' ? '这个库里还没有照片' : '这个筛选条件下没有照片')
      : '看完了';
    el.emptyHint.innerHTML = S.queue.length === 0
      ? (S.filter === 'all'
          ? '如果刚打开文件夹，稍等它扫描完。'
          : '换个筛选条件看看 —— 试试点上面的「全部」。')
      : '这一批都处理完了。可以换个条件继续，或者点右上角「应用决策」。';
    el.issueTags.innerHTML = el.overlay.innerHTML = '';
    el.metaLine.textContent = '';
    el.verdictBadge.innerHTML = '';
    el.decisionBadge.classList.add('hidden');
    el.histo.style.display = 'none';
    highlightCurrent();
    return;
  }
  el.photoStage.classList.remove('hidden');
  el.emptyState.classList.add('hidden');
  el.histo.style.display = '';
  resetHoldVisual();

  // Set the photo's REAL dimensions BEFORE laying out, and lay out now.
  //
  // fitStage() prefers these over el.photo.naturalWidth precisely so it can
  // run before the preview has loaded. Previously it only ran from onload, so
  // the arriving card kept the PREVIOUS photo's box for the ~250ms the 71 KB
  // preview took to arrive -- and then got resized part-way through its
  // arrival animation. Measured: 4 of every 30 adjacent pairs differ in aspect
  // ratio by more than 0.02, and each of those was a visible jump.
  V.origW = c.width || 0;
  V.origH = c.height || 0;
  fitStage();

  // Arrival: the card rises into the slot from below, every time.
  //
  // There is deliberately NO second element standing in for it any more. A
  // peek of the next photo was laid out in the CURRENT photo's box, so
  // whenever the two had different aspect ratios the peek had to be resized
  // -- instantly, while its position still transitioned -- and that read as a
  // twitch. Portrait to portrait barely changed size, which is why only some
  // turns looked wrong. One element, one animation, nothing to keep in sync.
  el.photoCard.style.visibility = '';
  el.photoCard.classList.remove('entering');
  void el.photoCard.offsetWidth;
  el.photoCard.classList.add('entering');

  el.photo.classList.add('loading');
  el.photo.onload = () => {
    el.photo.classList.remove('loading');
    fitStage();
    // Render it from the image, not from a guess: at this point src was
    // just assigned, so a cache miss means naturalWidth was still 0 and the
    // first draw bailed out. Without this the histogram stayed empty on
    // every cold load and only appeared when the file was already cached.
    drawHistogram();
  };
  el.photo.src = imgUrl(c.id, 'card');

  // The full-resolution layer is rebuilt for every photo.
  el.photoHD.classList.add('hidden');
  el.photoHD.removeAttribute('src');
  V.fullReady = false;

  renderVerdict(c);
  renderDecisionBadge(c);
  renderActionState(c);
  renderIssues(c);
  renderGroup(c);
  renderMeta(c);
  savePos(c.id);

  el.overlay.innerHTML = '';
  el.zebra.classList.add('hidden');
  S.detail = null;
  highlightCurrent();
  drawHistogram();
  loadDetail(c.id);
  loadFullRes(c);
  placeStamp();
  prefetchAhead();
}

function renderVerdict(c) {
  const sug = c.suggest || 'keep';
  // The software's opinion, phrased with the same three words as your own
  // decisions so the two never sound like different vocabularies.
  const main = VERDICT[sug] || '';
  const why = c.suggest_reason && c.suggest_reason !== '未发现明显问题' ? c.suggest_reason : '';
  el.verdictBadge.className = 'verdictBadge ' + sug;
  el.verdictBadge.innerHTML =
    `<span class="vdot"></span><span class="vmain">${esc(main)}</span>` +
    (why ? `<span class="vwhy">${esc(why)}</span>` : '');
}

/** Reflect the current photo's decision on the toolbar itself.
 *
 * Without this the toolbar is stateless: every button looks the same no
 * matter what the photo already is, so nothing tells you that pressing 精选
 * again will TAKE THE MARK BACK rather than add one. The button has to say
 * what it is about to do.
 */
function renderActionState(c) {
  const d = c ? c.decision : null;
  for (const a of ['keep', 'reject', 'mark']) {
    const b = $(`.act[data-act="${a}"]`);
    if (b) b.classList.toggle('on', d === a);
  }
  const label = $('.act[data-act=mark] .al');
  if (label) label.textContent = d === 'mark'
    ? '取消' + LABEL.mark : LABEL.mark;
  const btn = $('.act[data-act=mark]');
  if (btn) btn.title = (d === 'mark' ? '取消' + LABEL.mark : LABEL.mark)
    + '（键盘 空格，按住可先预览）';
}

/** The suggestion above is the software's; this one is yours. */
function renderDecisionBadge(c) {    const d = c.decision;
  if (!d) { el.decisionBadge.classList.add('hidden'); return; }
  const glyph = { keep: '✓', reject: '✕', mark: '★' }[d] || '';
  const label = OWNED[d];
  el.decisionBadge.className = 'decisionBadge ' + d;
  el.decisionBadge.textContent = `${glyph} ${label}`;
  el.decisionBadge.classList.remove('hidden');
}

/** Park the gesture label on the PHOTO, not on the viewport.
 *
 * .previewStamp lives in .photoStage so that it stays visible however the
 * image is panned or zoomed, but the stage is wider than the photo whenever
 * there are letterbox margins. Anchoring it with CSS `right` therefore parked
 * the 精选 star out in the black border, beside the picture instead of on it.
 *
 * 不过 / 过 hang off the photo's left and right edges, vertically centred,
 * because the label should be where the card is going -- your eye is already
 * there. 精选 is a mark ON the photo, so it goes in the top-right corner.
 */
function placeStamp() {
  if (!el.previewStamp || !V.bw) return;
  const o = centred(V.bw, V.bh);
  const s = el.previewStamp.style;
  s.setProperty('--stamp-l', (o.x + 18).toFixed(1) + 'px');
  s.setProperty('--stamp-r', (o.x + V.bw - 18).toFixed(1) + 'px');
  s.setProperty('--stamp-cy', (o.y + V.bh / 2).toFixed(1) + 'px');
  s.setProperty('--stamp-rx', (o.x + V.bw - 14).toFixed(1) + 'px');
  s.setProperty('--stamp-ry', (o.y + 14).toFixed(1) + 'px');
}

/** Warm the cache for the photos about to be shown.
 *
 * The card preview is ~71 KB and measured ~250 ms to fetch on this machine,
 * and for that whole time the arriving card sits at 25% opacity with
 * `loading` on it -- which is why a decision looked like it stuttered and
 * *then* the next photo turned up. Fetching the next two while you judge the
 * current one turns the arrival into a decode instead of a download.
 *
 * Only two are held: the Image objects keep decoded bitmaps alive, and the
 * browser's own cache is what carries the bytes forward.
 */
let _prefetch = [];
function prefetchAhead() {
  _prefetch = [];
  for (let k = 1; k <= 2; k++) {
    const it = S.queue[S.idx + k];
    if (!it) continue;
    const im = new Image();
    im.decoding = 'async';
    im.src = imgUrl(it.id, 'card');
    _prefetch.push(im);
  }
}


function renderIssues(c) {
  const list = (S.detail && S.detail.id === c.id && S.detail.issues) || c.issues || [];
  el.issueTags.innerHTML = list.map(i =>
    `<div class="tag ${i.severity || 'info'}">` +
    (i.face_idx != null ? `<span class="fx">脸${i.face_idx + 1}</span>` : '') +
    `<span>${esc(i.label_zh)}</span>` +
    (i.confidence != null ? `<span class="conf">${Math.round(i.confidence * 100)}%</span>` : '') +
    `</div>`).join('');
}

function renderGroup(c) {
  if (c.group_size > 1) {
    el.groupBadge.classList.remove('hidden');
    el.groupBadge.textContent = `相似组 ${c.group_rank}/${c.group_size}` +
      (c.group_rank === 1 ? ' · 组内最佳' : '');
  } else {
    el.groupBadge.classList.add('hidden');
  }
}

function renderMeta(c) {
  const bits = [c.name];

  // Shooting settings. On a culling pass these decide as much as the picture
  // does -- 1/60s at ISO 6400 tells you why it is soft before you zoom in.
  const shot = [];
  if (c.shutter) shot.push(c.shutter);
  if (c.aperture) shot.push('f/' + (+c.aperture).toFixed(1).replace(/\.0$/, ''));
  if (c.iso) shot.push('ISO ' + c.iso);
  if (c.focal) shot.push(Math.round(c.focal) + 'mm');
  if (shot.length) bits.push(shot.join(' '));

  if (c.taken_at) bits.push(c.taken_at);
  if (c.width) bits.push(`${c.width}×${c.height}`);
  if (c.camera) bits.push(c.camera);

  // Where this frame sits in its own burst, and how long since the previous
  // one -- a 20-minute jump is a different scene, not another take.
  if (c.group_size > 1) bits.push(`连拍 ${c.group_rank}/${c.group_size}`);
  const prev = S.queue[S.idx - 1];
  if (prev && prev.taken_ts && c.taken_ts) {
    const dt = c.taken_ts - prev.taken_ts;
    if (dt >= 0) {
      bits.push(dt < 60 ? `距上一张 ${Math.round(dt)}s`
                        : `距上一张 ${Math.round(dt / 60)}min`);
    }
  }

  el.metaLine.textContent = bits.join('  ·  ');
}

async function loadDetail(id) {
  try {
    const d = await api(`/api/photo/${id}`);
    if (!cur() || cur().id !== id) return;
    S.detail = d;
    const c = cur();
    if (c) renderIssues(c);
    renderOverlay();
  } catch (e) { /* ignore */ }
}

/* ── full resolution ──
   The old code preloaded the original and then threw it away, so zooming
   just upscaled a 1600px preview. Now the full image is fetched in the
   background and layered on top the moment it decodes. */
let fullPre = null;

function loadFullRes(c) {
  if (!c) return;
  const id = c.id;
  const im = new Image();
  fullPre = im;
  if ('decoding' in im) im.decoding = 'async';
  im.onload = () => {
    const now = cur();
    if (!now || now.id !== id) return;      // the user moved on
    if (V.fullReady) return;
    el.photoHD.src = im.src;
    el.photoHD.classList.remove('hidden');
    // NOT gated on el.photoHD.decode(): that promise can stay pending
    // indefinitely in a background tab, which left fullReady false forever
    // and pinned the zoom cap at the 1600px preview (measured 27%, MAD 45+).
    // onload is enough -- verified pixel-identical (MAD 1.26/255) at 100%.
    V.fullReady = true;
    V.natW = im.naturalWidth;
    V.natH = im.naturalHeight;
    updateZoomBadge();
    drawHistogram();
    if (S.showZebra) buildZebra();
  };
  im.onerror = () => { V.fullReady = false; };
  im.src = imgUrl(id, 'full');
}

/* ───────────────────── 注入：清掉上一次按住预览的残留 ─────────────────────

   render() 的第一件事是把舞台恢复成什么都没按的样子，那是 app.js 的
   resetHoldVisual：它要同时管 hold、蒙版进度、印章、卡片偏移，而且必须和
   flyOut / endHold 的节奏一致。为一个函数 import app.js 会成环。 */
let resetHoldVisual = () => {};
function configure(hooks) {
  if (hooks && hooks.resetHoldVisual) resetHoldVisual = hooks.resetHoldVisual;
}


export { render, renderVerdict, renderActionState, renderDecisionBadge,
  placeStamp, prefetchAhead, renderIssues, renderGroup, renderMeta,
  loadDetail, loadFullRes, configure
};
