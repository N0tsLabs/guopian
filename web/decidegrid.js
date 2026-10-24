/* 过片 Guopian — 多张一起决定（决策网格）
 *
 * @requires web/core.js         G ( $ $$ esc api toast )
 * @requires web/state.js        S
 * @requires web/gridlayout.js   computeGridLayout
 *
 * 左边多选几张，右边把它们并排摊开，你点哪几张就留下哪几张。
 *
 * 这个模式替代的不是"看得更快"，而是**按键次数**。逐张过的时候，八张同场景
 * 要回答八次；在这里你点两下、按回车，八张就都定了。因为"要不要"这个问题
 * 对这八张其实是同一个问题：**这几张里留哪几张。**
 *
 * 没点的就是不要 —— 这是你定的规则：要的话你肯定会点。所以这个模式下没有
 * "向左滑"和"向右滑"，只有一个动作：挑出活下来的。
 *
 * 提交时全部照片共用同一个 batch id，所以 ⌫ 能整批撤回，而不是只撤最后一张。
 */

import { G } from './core.js';
import { S } from './state.js';
import { computeGridLayout, GAP } from './gridlayout.js';

const DecideGrid = (() => {
  const { $, esc, api, toast, imgUrl } = G;

  let root = null;
  let zoomEl = null;
  let ids = [];
  let tiles = new Map();   // id -> element
  let cards = new Map();   // id -> 队列里的那张照片
  let focus = 0;
  let onDone = null;

  const ACTIONS = { keep: 'keep', mark: 'mark', reject: 'reject' };

  function build() {
    if (root) return root;
    root = document.createElement('div');
    root.className = 'decideGrid hidden';
    root.innerHTML = `
      <div class="dgHead">
        <span class="dgTitle">一起决定 <b id="dgCount"></b></span>
        <span class="dgHint">点一下＝留下，不点的＝不过</span>
        <span class="sp"></span>
        <button class="linkbtn" id="dgCancel">取消 (Esc)</button>
      </div>
      <div class="dgBody" id="dgBody"></div>
      <div class="dgFoot">
        <span id="dgSummary"></span>
        <span class="sp"></span>
        <button class="btn ghost" id="dgEsc">取消</button>
        <button class="btn primary" id="dgCommit">留下这两张</button>
      </div>`;
    document.body.appendChild(root);

    $('#dgCancel', root).onclick = () => close();

    // 放大层：单独一个元素，盖住整个窗口
    zoomEl = document.createElement('div');
    zoomEl.className = 'dgZoom hidden';
    zoomEl.innerHTML = '<img alt="" draggable="false">'
      + '<div class="dgZoomBadge"></div>'
      + '<div class="dgZoomHint">← → 切换 · K 留下 · S 精选 · 空格 / Esc 关闭</div>';
    document.body.appendChild(zoomEl);
    // 点空白处关闭 —— 但放大/拖动之后不能一松手就关掉，双击也不能先关再还原
  // （click 事件总在 dblclick 之前来）。所以只在"没放大、刚才是单击、且没拖"
  // 的情况下关。
  let downAt = null, moved = false;
  zoomEl.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; moved = false; });
  zoomEl.addEventListener('pointermove', (e) => {
    if (downAt && (Math.abs(e.clientX - downAt[0]) > 4 || Math.abs(e.clientY - downAt[1]) > 4)) moved = true;
  });
  zoomEl.addEventListener('click', () => {
    if (zs <= 1.01 && !moved) closeZoom();
    downAt = null;
  });
    $('#dgEsc', root).onclick = () => close();
    $('#dgCommit', root).onclick = () => commit();

    root.addEventListener('click', (e) => {
      const t = e.target.closest('.dgTile');
      if (!t) return;
      const id = +t.dataset.id;
      const btn = e.target.closest('.dgActions button');
      if (btn) {
        // 按钮标记：点同一个第二次是取消
        toggle(id, btn.dataset.act);
        paint();
        return;
      }
      // 点图片＝放大看，永远不改状态
      focus = ids.indexOf(id);
      openZoom();
    });
    root.addEventListener('mousemove', (e) => {
      const t = e.target.closest('.dgTile');
      if (!t) return;
      const i = ids.indexOf(+t.dataset.id);
      if (i >= 0 && i !== focus) { focus = i; paint(); }
    });
    return root;
  }

  /** 在 keep / mark 之间切换；点同一个动作第二次就是取消。 */
  function stateOf(id) {
    const c = cards.get(id);
    return (c && c.__gridPick) || null;
  }

  function toggle(id, action) {
    const c = cards.get(id);
    if (!c) return;
    c.__gridPick = (c.__gridPick === action) ? null : action;
  }

  function chooseLayout() {
    // 量根的可用区域，不量 .dgBody 自己 —— 刚设过 grid-template-columns 以后，
    // 它的宽度会被列数反向约束，越量越小，最后掉到 96px 下限。
    const body = $('#dgBody', root);
    const r = root.getBoundingClientRect();
    const cs = getComputedStyle(body);
    const padX = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
    const padY = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const headEl = root.querySelector('.dgHead');
    const headH = headEl ? headEl.offsetHeight : 0;
    // 底栏只有 class 没有 id（我当初在模板里没写 id），用选择器取。
    const footEl = root.querySelector('.dgFoot');
    const footH = footEl ? footEl.offsetHeight : 0;
    return computeGridLayout(
      ids.length,
      Math.max(1, r.width - padX),
      Math.max(1, r.height - padY - headH - footH));
  }

  function paint() {
    const picks = ids.filter((id) => stateOf(id));
    const nMark = ids.filter((id) => stateOf(id) === 'mark').length;
    const nKeep = picks.length - nMark;

    $('#dgCount', root).textContent = `${ids.length} 张`;
    tiles.forEach((el, id) => {
      const p = stateOf(id);
      el.classList.toggle('dgKeepOn', p === 'keep');
      el.classList.toggle('dgMarkOn', p === 'mark');
      const flag = el.querySelector('.dgFlag');
      if (flag) flag.textContent = p === 'mark' ? '★' : (p ? '✓' : '');
    });

    const rest = ids.length - picks.length;
    $('#dgSummary', root).textContent = picks.length
      ? `留下 ${picks.length} 张${nMark ? `（含精选 ${nMark}）` : ''}，其余 ${rest} 张不过`
      : `还没点任何一张 —— 提交的话 ${ids.length} 张全部不过`;
    const btn = $('#dgCommit', root);
    btn.textContent = picks.length
      ? `留下这 ${picks.length} 张`
      : `全部 ${ids.length} 张不过`;
    btn.disabled = false;
    btn.classList.toggle('danger', !picks.length);
  }

  async function open(selectedIds, done) {
   try {
    build();
    // 多图模式正在进行。keys.js 靠这个标记让路 —— 否则空格/左右键还在
    // 悄悄决定左边列表里的"当前那张"，而用户以为自己在看多图。
    S.grid = true;
    ids = selectedIds.slice();
    onDone = done || null;
    focus = 0;
    // 队列里的那张照片，按 id 索引。没有 S.byId 这种字段，自己建。
    cards = new Map();
    (S.queue || []).forEach((c) => { if (c && c.id != null) cards.set(c.id, c); });
    // 上次打开留下的临时标记要清掉，否则会串到这个批次里
    ids.forEach((id) => { const c = cards.get(id); if (c) delete c.__gridPick; });

    // 先显示再量。元素还在 display:none 的时候 getBoundingClientRect() 是
    // 0×0，布局就算成最小格子 —— 在真窗口里表现为一堆 96px 缩略图挤在中间。
    root.classList.remove('hidden');

    const listEl = $('#listScroll');
    const left = listEl ? listEl.getBoundingClientRect().right : 0;
    root.style.left = Math.max(0, left) + 'px';

    // 起点放在筛选条下面，不是只避开顶栏 —— 否则网格头会压在「全部/未审/过…」上。
    const chips = document.querySelector('.chips');
    const bar = document.querySelector('.topbar');
    const anchor = chips && chips.getBoundingClientRect().height
      ? chips : bar;
    const top = anchor ? anchor.getBoundingClientRect().bottom : 0;
    root.style.top = Math.max(0, top) + 'px';

    const g = chooseLayout();
    const body = $('#dgBody', root);
    body.style.gridTemplateColumns = `repeat(${g.cols}, ${g.tile}px)`;
    body.style.gridAutoRows = `${g.tile}px`;
    body.style.width = '100%';
    if (g.overflow) body.style.width = (g.cols * (g.tile + GAP)) + 'px';

    tiles = new Map();
    body.innerHTML = '';
    ids.forEach((id) => {
      const c = cards.get(id);
      if (!c) return;
      const el = document.createElement('div');
      el.className = 'dgTile';
      el.dataset.id = id;
      el.innerHTML = `
        <img src="${imgUrl(id, 'card')}" alt="" draggable="false">
        <span class="dgFlag"></span>
        <span class="dgActions">
          <button class="dgKeep" data-act="keep">留下</button>
          <button class="dgMark" data-act="mark">精选</button>
        </span>`;
      body.appendChild(el);
      tiles.set(id, el);
    });
    root.classList.remove('hidden');
    paint();
   } catch (e) {
     window.__gridErr = (e && e.stack) || String(e);
     console.error('决策网格初始化失败', e);
   }
  }

  /** 用户按 Esc / 点取消：退出并把选择清空。 */
  function close() {
    if (root) root.classList.add('hidden');
    S.grid = false;
    // 广播，不等回调 —— onDone 可能已经被上一次 close 或 syncGrid 用掉了，
    // 那样用户按 Esc 之后左侧的选择就清不掉（表现为"退出了多图，左边还亮着"）。
    window.dispatchEvent(new CustomEvent('guopian:gridcancel'));
    if (onDone) { const f = onDone; onDone = null; f('cancel'); }
  }

  /** 程序自己收起（比如选中数掉到 1）。
   *  不跑回调 —— 回调会清空选择，那样用户刚点出来的东西会被自己抹掉。 */
  function closeQuiet() {
    if (root) root.classList.add('hidden');
    S.grid = false;
    // 不要清 onDone：清掉以后用户再按 Esc，close() 就找不到回调，
    // 选择永远清不掉 —— 表现为「退出了多图模式，左边还挂着一排选中」。
    // 回调本身只关心 what 是什么，重复调用是安全的。
  }

  async function commit() {
    if (!ids.length) return close();
    const picks = ids.filter((id) => stateOf(id));
    const marked = picks.filter((id) => stateOf(id) === 'mark');
    const kept = picks.filter((id) => stateOf(id) === 'keep');
    const rest = ids.filter((id) => !stateOf(id));

    const batch = 'grid-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 6);
    try {
      // 同一个 batch，所以 ⌫ 能整批撤回
      if (kept.length) await api('/api/decide', { method: 'POST', body: JSON.stringify({ action: 'keep', ids: kept, batch }) });
      if (marked.length) await api('/api/decide', { method: 'POST', body: JSON.stringify({ action: 'mark', ids: marked, batch }) });
      if (rest.length) await api('/api/decide', { method: 'POST', body: JSON.stringify({ action: 'reject', ids: rest, batch }) });
    } catch (e) {
      toast('提交失败：' + (e && e.message ? e.message : e), 'err');
      return;
    }

    ids.forEach((id) => { const c = cards.get(id); if (c) delete c.__gridPick; });
    root.classList.add('hidden');
    const msg = picks.length
      ? `留下 ${picks.length} 张${marked.length ? `（精选 ${marked.length}）` : ''}，${rest.length} 张不过`
      : `${ids.length} 张全部不过`;
    G.lastBatch = batch;      // app.js 的 ⌫ 用它整批撤回
    window.__lastBatch = batch;   // 浏览器测试用的
    const jumpTo = (kept[0] || marked[0] || ids[0]);
    if (onDone) { const f = onDone; onDone = null; f('commit', jumpTo); }
    toast(msg + ' · ⌫ 可整批撤回');
  }


/** 放大看当前聚焦的那一张。空格打开，Esc 或点一下关闭。 */
function openZoom() {
  if (!zoomEl) return false;
  zoomEl.classList.remove('hidden');
  paintZoom();
  return true;
}

/** 放大层显示当前聚焦的那一张，并把它的状态写在角上。
 *  放大以后左右翻，看到的还是同一套标记，不用退出去确认。 */
function paintZoom() {
  if (!zoomEl || zoomEl.classList.contains('hidden')) return;
  const id = ids[focus];
  if (id == null) return;
  const img = zoomEl.querySelector('img');
  img.src = imgUrl(id, 'card');
  zoomSetup();
  resetZoom();
  const p = stateOf(id);
  const badge = zoomEl.querySelector('.dgZoomBadge');
  badge.textContent = p === 'mark' ? '★ 精选' : (p === 'keep' ? '✓ 留下' : '');
  badge.className = 'dgZoomBadge' + (p ? ' on' : '') + (p === 'mark' ? ' mark' : '');
}

/* 放大层里的缩放与拖动。
 *
 * 之前点开只有一张贴满屏的静态图：既不能放大看眼神，也不能拖动看边角，
 * 和"图片查看器"差得远。现在滚轮缩放、按住拖动、双击还原。
 */
let zs = 1, zx = 0, zy = 0;

function applyZoom() {
  const img = zoomEl && zoomEl.querySelector('img');
  if (!img) return;
  img.style.transform = `translate(${zx}px, ${zy}px) scale(${zs})`;
  img.style.cursor = zs > 1.01 ? 'grab' : 'zoom-in';
}

function resetZoom() { zs = 1; zx = 0; zy = 0; applyZoom(); }

function zoomSetup() {
  if (!zoomEl || zoomEl.__zoomWired) return;
  zoomEl.__zoomWired = true;
  zoomEl.addEventListener('wheel', (e) => {
    e.preventDefault();
    const k = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    zs = Math.max(1, Math.min(8, zs * k));
    if (zs <= 1.01) { zx = 0; zy = 0; }
    applyZoom();
  }, { passive: false });
  let drag = null;
  zoomEl.addEventListener('pointerdown', (e) => {
    if (zs <= 1.01) return;
    drag = { x: e.clientX - zx, y: e.clientY - zy };
    zoomEl.setPointerCapture(e.pointerId);
    zoomEl.style.cursor = 'grabbing';
  });
  zoomEl.addEventListener('pointermove', (e) => {
    if (!drag) return;
    zx = e.clientX - drag.x; zy = e.clientY - drag.y;
    applyZoom();
  });
  const end = (e) => {
    if (!drag) return;
    drag = null;
    try { zoomEl.releasePointerCapture(e.pointerId); } catch {}
    zoomEl.style.cursor = zs > 1.01 ? 'grab' : 'zoom-in';
  };
  zoomEl.addEventListener('pointerup', end);
  zoomEl.addEventListener('pointercancel', end);
  zoomEl.addEventListener('dblclick', (e) => { e.stopPropagation(); resetZoom(); });
}

function closeZoom() {
  if (!zoomEl || zoomEl.classList.contains('hidden')) return false;
  zoomEl.classList.add('hidden');
  return true;
}

function isZoomed() {
  return !!zoomEl && !zoomEl.classList.contains('hidden');
}

  function onKey(e) {
    if (!root || root.classList.contains('hidden')) return false;
    const k = e.key;
    if (k === 'Escape') {
      e.preventDefault();
      // 放大中的 Esc 只关放大，不退出网格
      if (closeZoom()) return true;
      close();
      return true;
    }

    // ── 放大状态：一套单独的键位 ──
    // 看清楚了就当场决定，不用退出去；左右翻还是同一组照片。
    if (isZoomed()) {
      // 空格在放大里是「关掉」。之前这一块对任何键都 return true，
      // 空格被吞掉了，只能按 Esc 才出得来。
      if (k === ' ') { e.preventDefault(); closeZoom(); return true; }
      if (k === 'ArrowLeft' || k === 'ArrowRight' || k === 'ArrowUp' || k === 'ArrowDown') {
        e.preventDefault();
        const d = (k === 'ArrowLeft' || k === 'ArrowUp') ? -1 : 1;
        focus = Math.max(0, Math.min(ids.length - 1, focus + d));
        paint();
        paintZoom();
        return true;
      }
      if (k === 'k' || k === 'K') {
        e.preventDefault(); toggle(ids[focus], 'keep'); paint(); paintZoom(); return true;
      }
      if (k === 's' || k === 'S') {
        e.preventDefault(); toggle(ids[focus], 'mark'); paint(); paintZoom(); return true;
      }
      return true;   // 放大时其它键一律吃掉，不要漏到底下的网格
    }

    if (k === ' ') {
      // 空格 = 放大查看，不是「留下」。
      // 在网格里「留下」已经有点击这个动作，空格用来仔细看更顺手；
      // 键盘想标记留下按 K。
      e.preventDefault();
      if (isZoomed()) closeZoom(); else openZoom();
      return true;
    }
    if (k === 'Enter') { e.preventDefault(); commit(); return true; }
    const move = (d) => {
      const g = chooseLayout();
      focus = Math.max(0, Math.min(ids.length - 1, focus + d));
      paint();
      const el = tiles.get(ids[focus]);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      return true;
    };
    if (k === 'z' || k === 'Z') { e.preventDefault(); openZoom(); return true; }
    if (k === 'ArrowLeft') { e.preventDefault(); return move(-1); }
    if (k === 'ArrowRight') { e.preventDefault(); return move(1); }
    if (k === 'ArrowUp') { e.preventDefault(); return move(-chooseLayout().cols); }
    if (k === 'ArrowDown') { e.preventDefault(); return move(chooseLayout().cols); }
    // 网格里不做键盘决定 —— 选了哪个就是哪个，不留"焦点在哪"的歧义。
    // 只保留 Z 放大，放大层里再用键盘判。
    return false;
  }

  // 捕获阶段监听：网格开着的时候先拿到按键，其余时候完全放行。
  // 这样不用改 keys.js，也不会在网格关着时抢走任何一个键。
  window.addEventListener('keydown', (e) => {
    if (!root || root.classList.contains('hidden')) return;
    if (onKey(e)) { e.stopPropagation(); }
  }, true);

  return { open, close, closeQuiet, commit, onKey,
           isOpen: () => !!root && !root.classList.contains('hidden') };
})();

export { DecideGrid };
