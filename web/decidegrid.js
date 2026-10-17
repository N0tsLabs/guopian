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
  const { $, esc, api, toast } = G;

  let root = null;
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
    $('body') || document.body;
    document.body.appendChild(root);

    $('#dgCancel', root).onclick = () => close();
    $('#dgEsc', root).onclick = () => close();
    $('#dgCommit', root).onclick = () => commit();

    root.addEventListener('click', (e) => {
      const t = e.target.closest('.dgTile');
      if (!t) return;
      const id = +t.dataset.id;
      const i = ids.indexOf(id);
      if (e.shiftKey) toggle(id, 'mark');
      else toggle(id, 'keep');
      focus = i;
      paint();
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
    const body = $('#dgBody', root);
    const r = body.getBoundingClientRect();
    return computeGridLayout(ids.length, r.width, r.height);
  }

  function paint() {
    const picks = ids.filter((id) => stateOf(id));
    const nMark = ids.filter((id) => stateOf(id) === 'mark').length;
    const nKeep = picks.length - nMark;

    $('#dgCount', root).textContent = `${ids.length} 张`;
    tiles.forEach((el, id) => {
      const p = stateOf(id);
      el.classList.toggle('picked', !!p);
      el.classList.toggle('marked', p === 'mark');
      el.classList.toggle('focused', ids.indexOf(id) === focus);
      if (!p) el.classList.add('will-reject');
      else el.classList.remove('will-reject');
      const badge = el.querySelector('.dgBadge');
      if (badge) badge.textContent = p === 'mark' ? '★' : (p ? '✓' : '');
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
    ids = selectedIds.slice();
    onDone = done || null;
    focus = 0;
    // 队列里的那张照片，按 id 索引。没有 S.byId 这种字段，自己建。
    cards = new Map();
    (S.queue || []).forEach((c) => { if (c && c.id != null) cards.set(c.id, c); });
    // 上次打开留下的临时标记要清掉，否则会串到这个批次里
    ids.forEach((id) => { const c = cards.get(id); if (c) delete c.__gridPick; });

    const listEl = $('#listScroll');
    const left = listEl ? listEl.getBoundingClientRect().right : 0;
    root.style.left = Math.max(0, left) + 'px';

    const g = chooseLayout();
    const body = $('#dgBody', root);
    body.style.gridTemplateColumns = `repeat(${g.cols}, ${g.tile}px)`;
    body.style.gridAutoRows = `${g.tile}px`;
    body.style.width = g.overflow ? (g.cols * (g.tile + GAP)) + 'px' : '';

    tiles = new Map();
    body.innerHTML = '';
    ids.forEach((id) => {
      const c = cards.get(id);
      if (!c) return;
      const el = document.createElement('div');
      el.className = 'dgTile';
      el.dataset.id = id;
      el.innerHTML = `
        <img src="/api/thumb/${id}" alt="" draggable="false">
        <span class="dgBadge"></span>
        <span class="dgName">${esc(c.name || '')}</span>`;
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

  function close() {
    if (root) root.classList.add('hidden');
    if (onDone) { const f = onDone; onDone = null; f('cancel'); }
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

  function onKey(e) {
    if (!root || root.classList.contains('hidden')) return false;
    const k = e.key;
    if (k === 'Escape') { e.preventDefault(); close(); return true; }
    if (k === 'Enter') { e.preventDefault(); commit(); return true; }
    const move = (d) => {
      const g = chooseLayout();
      focus = Math.max(0, Math.min(ids.length - 1, focus + d));
      paint();
      const el = tiles.get(ids[focus]);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      return true;
    };
    if (k === 'ArrowLeft') { e.preventDefault(); return move(-1); }
    if (k === 'ArrowRight') { e.preventDefault(); return move(1); }
    if (k === 'ArrowUp') { e.preventDefault(); return move(-chooseLayout().cols); }
    if (k === 'ArrowDown') { e.preventDefault(); return move(chooseLayout().cols); }
    if (k === ' ' || k === 'k' || k === 'K') {
      e.preventDefault(); toggle(ids[focus], 'keep'); paint(); return true;
    }
    if (k === 's' || k === 'S') {
      e.preventDefault(); toggle(ids[focus], 'mark'); paint(); return true;
    }
    return false;
  }

  // 捕获阶段监听：网格开着的时候先拿到按键，其余时候完全放行。
  // 这样不用改 keys.js，也不会在网格关着时抢走任何一个键。
  window.addEventListener('keydown', (e) => {
    if (!root || root.classList.contains('hidden')) return;
    if (onKey(e)) { e.stopPropagation(); }
  }, true);

  return { open, close, commit, onKey,
           isOpen: () => !!root && !root.classList.contains('hidden') };
})();

export { DecideGrid };
