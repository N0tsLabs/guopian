/* 过片 Guopian — 左侧照片列表，以及"上次看到哪一张"的记忆。
 *
 * 为什么单独成模块：列表的重绘（缩略图懒加载、当前项高亮、汇总条、进度条）
 * 是一整套自成体系的 DOM 操作，和卡片渲染没有共享代码。混在一起的时候，
 * 改汇总条的一个计数就要动 1700 行的文件。
 *
 * @requires ./state.js   el S LABEL
 * @requires ./core.js    esc $$
 *
 * 三处向上的调用用 configure() 注入，因为 import 上去就成环：
 *   render        —— 列表项被点击时要换卡片（card.js）
 *   loadQueue     —— 汇总条被点击时要重新拉队列（app.js）
 *   renderTriage  —— 同时要把顶部的筛选条画成一致的状态（app.js）
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */

import { el, S, LABEL } from './state.js';
import { esc, $$, imgUrl } from './core.js';

/* ── where to put the cursor when a list loads ──
   Reopening a project should land you back where you were, not at the top.
   If we have nothing remembered, start at the first photo that still needs
   a decision -- that is almost always what you came back to do. */
function posKey() {
  return 'guopian.pos.' + ((S.state && S.state.root) || '');
}

function savedPos() {
  try { return parseInt(localStorage.getItem(posKey()) || '0', 10) || 0; }
  catch (e) { return 0; }
}

/* Per-library session memory: the filter and sort you were last on.
 *
 * The photo position has been remembered for a while, but not the filter -- so
 * reloading put you back on the default filter while showing the photo you had
 * been looking at, which is the worst of both: the list changes underneath you
 * and the one thing that was remembered is now somewhere else in it.
 *
 * Keyed like the position, so it is per library, and kept in localStorage so it
 * survives closing the app -- the window profile lives in the data directory,
 * not a temp one, so this really does persist. */
function sessKey() {
  return 'guopian.sess.' + ((S.state && S.state.root) || '');
}

function savedSession() {
  try { return JSON.parse(localStorage.getItem(sessKey()) || '{}') || {}; }
  catch (e) { return {}; }
}

function saveSession(patch) {
  try {
    const cur = savedSession();
    Object.assign(cur, patch);
    localStorage.setItem(sessKey(), JSON.stringify(cur));
  } catch (e) { /* ignore */ }
}

function savePos(id) {
  try { localStorage.setItem(posKey(), String(id)); } catch (e) { /* ignore */ }
}

function pickStartIndex() {
  if (!S.queue.length) return 0;
  const id = savedPos();
  if (id) {
    const at = S.queue.findIndex(c => c.id === id);
    if (at >= 0) return at;
  }
  const firstOpen = S.queue.findIndex(c => !c.decision);
  return firstOpen >= 0 ? firstOpen : 0;
}

/* Similar groups get a colour so a pair or a burst is obvious while scrolling.
 *
 * Only groups of two or more: a group of one is not similar to anything, and
 * this library has 66 groups for 92 photos -- colouring the singletons too
 * would paint nearly the whole list and mean nothing.
 *
 * The colour is derived from group_id, so the same group keeps the same colour
 * between renders and between sessions. */
function groupClass(c) {
  // The index comes from the server, which ranks a group among the multi-photo
  // groups. Hashing group_id % 8 here gave two unrelated groups the same colour
  // in a 66-group library, which defeats the only thing the colour is for.
  if (!(c.group_size > 1) || c.group_color == null) return '';
  return ' g' + c.group_color;
}

function itemHTML(c, i, shown, endsGroup) {
  const flags = (c.issues || []).slice(0, 2)
    .map(x => `<span class="sev-${x.severity}">${esc(x.label_zh)}</span>`).join(' · ');
  // Both, not either. This used to be `${flags || g}`, so any photo with an
  // issue lost its group chip entirely -- and the "similar" filter showed a
  // column of chips with unlabelled gaps between them, which reads as broken
  // grouping rather than as a rendering bug.
  const g = c.group_size > 1
    ? `<span class="grp">相似 ${c.group_rank}/${c.group_size}</span>` : '';
  const cls = `${c.decision || ''}${groupClass(c)}`
    + (endsGroup != null ? ` grpEnd ge${endsGroup}` : '');
  return `<button class="listItem ${cls}" data-i="${i}" data-id="${c.id}">
    <span class="bar"></span>
    <span class="thumbWrap">
      <img data-src="${imgUrl(c.id, 'small')}" alt="">
      <span class="num">${shown == null ? i + 1 : shown}</span>
    </span>
    <span class="info">
      <span class="nm">${esc(c.name)}</span>
      <span class="fl">${g}${g && flags ? '<span class="dot">·</span>' : ''}${flags}</span>
    </span>
    <span class="mark">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.4"
           stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
    </span>
  </button>`;
}

let thumbObserver = null;
function observeThumbs() {
  if (thumbObserver) thumbObserver.disconnect();
  thumbObserver = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      const img = en.target;
      thumbObserver.unobserve(img);
      const src = img.dataset.src;
      if (src) {
        img.onload = () => img.classList.add('loaded');
        img.src = src;
      }
    }
  }, { root: el.listScroll, rootMargin: '300px 0px' });
  $$('img[data-src]', el.listScroll).forEach(im => {
    // item 0 is visible immediately; give the ones already on screen a head start
    thumbObserver.observe(im);
  });
}

/* The list, as it will actually be drawn.
 *
 * Base shape is two lines per photo: name, then issues. Photos in a similar
 * group additionally get a group header above the first of them.
 *
 * Group members are pulled together here. Measured on a real library, 15 of 16
 * groups were already adjacent under the time sort, and the one that was not
 * had a single ungrouped photo sitting between its two members -- so making
 * them adjacent moves that one photo and nothing else. Sorting by group rank
 * inside a block also means the best frame of a burst is the one you meet
 * first, which is the order you would want to compare them in anyway.
 */
function buildRows(queue) {
  const byGroup = new Map();
  queue.forEach((c, i) => {
    if ((c.group_size || 0) > 1 && c.group_id != null) {
      if (!byGroup.has(c.group_id)) byGroup.set(c.group_id, []);
      byGroup.get(c.group_id).push({ c, i });
    }
  });

  const rows = [];
  const done = new Set();
  queue.forEach((c, i) => {
    const gid = (c.group_size || 0) > 1 && c.group_id != null ? c.group_id : null;
    if (gid == null) {
      rows.push({ type: 'item', c, i });
      return;
    }
    if (done.has(gid)) return;               // emitted with the first member
    done.add(gid);
    const members = byGroup.get(gid)
      .sort((a, b) => (a.c.group_rank || 0) - (b.c.group_rank || 0));
    rows.push({ type: 'group', gid, members });
    // `end` marks the last member so the block can be closed off with a line in
    // the group's own colour. A header alone is an upper boundary with nothing
    // underneath it, and consecutive blocks then read as one long list.
    members.forEach((m, k) => rows.push({
      type: 'item', c: m.c, i: m.i, end: k === members.length - 1, gid,
    }));
  });
  return rows;
}

function groupHeadHTML(gid, members) {
  const first = members[0].c;
  const col = first.group_color == null ? 0 : first.group_color;
  const dec = {};
  for (const m of members) dec[m.c.decision || ''] = (dec[m.c.decision || ''] || 0) + 1;
  const parts = [];
  if (dec.keep) parts.push(`${LABEL.keep} ${dec.keep}`);
  if (dec.reject) parts.push(`${LABEL.reject} ${dec.reject}`);
  if (dec.mark) parts.push(`${LABEL.mark} ${dec.mark}`);
  const undecided = (dec[''] || 0);
  if (undecided) parts.push(`未审 ${undecided}`);
  return `<div class="grpHead g${col}">
    <span class="grp g${col}">相似 ${members.length} 张</span>
    <span class="grpTally">${parts.join(' · ') || '还没决定'}</span>
  </div>`;
}

function renderList() {
  let shown = 0;
  el.listScroll.innerHTML = buildRows(S.queue)
    .map(r => (r.type === 'group'
      ? groupHeadHTML(r.gid, r.members)
      : itemHTML(r.c, r.i, ++shown, r.end ? r.gid : null)))
    .join('');
  observeThumbs();
  highlightCurrent();
  updateListProgress();
  renderListSummary();
  $$('.listItem', el.listScroll).forEach(it => {
    it.onclick = (e) => {
      const i = +it.dataset.i;
      const id = S.queue[i] && S.queue[i].id;
      // 和文件资源管理器一样：修饰键要按着才算数，松开就是普通点击。
      // 我上一版做成了"Ctrl+点一次就进入粘性多选"，那是错的 ——
      // 松开 Ctrl 之后普通点击又会清空，两种行为混在一起只会让人摸不着头脑。
      if (e.shiftKey && S.selAnchor != null) {
        // Shift：从锚点到这一行，整段加入
        const a = Math.min(S.selAnchor, i);
        const b = Math.max(S.selAnchor, i);
        for (let k = a; k <= b; k++) {
          const kid = S.queue[k] && S.queue[k].id;
          if (kid != null) S.sel.add(kid);
        }
      } else if (e.ctrlKey || e.metaKey) {
        // 按住 Ctrl 点击：加一张或去掉一张。
        // 第一次按 Ctrl 点的时候，把「当前正在看的那张」一起选上 ——
        // 否则第一次只选中一张，进不了多图模式，要等第二次点击才生效。
        if (!S.sel.size) {
          const curId = S.queue[S.idx] && S.queue[S.idx].id;
          if (curId != null && curId !== id) S.sel.add(curId);
        }
        if (id != null) {
          if (S.sel.has(id)) S.sel.delete(id); else S.sel.add(id);
        }
        S.selAnchor = i;
      } else {
        // 没按修饰键：清空选择，回到单选
        if (S.sel.size) S.sel.clear();
        S.selAnchor = i;
      }
      S.multi = false;

      S.idx = i;
      // render() 是 app.js 注入的（见 configure），它既画列表也换右侧卡片。
      // 上一版我为了少闪一下把它换成只改类名，结果单击列表右侧完全不动 ——
      // 那是把"点一下就换图"这条主路断了，比闪一下严重得多。
      render();
      paintSelection();
      syncGrid();
    };
  });
}

/** Colour-coded tally at the top of the list. Clicking one filters to it. */
function renderListSummary() {
  // Counts come from the WHOLE library (state.counts.decisions), never from
  // S.queue. S.queue is the currently FILTERED list, so counting it meant that
  // clicking 过 produced { keep: 69 } and nothing else -- the other three
  // chips then had a count of zero, were filtered out of the row, and there
  // was no way back to them. The switcher deleted itself.
  const d = (S.state && S.state.counts && S.state.counts.decisions) || {};
  const n = {
    none: d.undecided || 0,
    keep: d.keep || 0,
    reject: d.reject || 0,
    mark: d.mark || 0,
  };
  const rows = [['none', '未审', 'pending'], ['keep', LABEL.keep, 'keep'],
                ['reject', LABEL.reject, 'reject'], ['mark', LABEL.mark, 'mark']];
  // All four are ALWAYS rendered, at zero included: they are how you switch
  // between views, not a summary of whatever happens to be on screen. The
  // active one is marked rather than the others being removed.
  el.listSummary.innerHTML = rows
    .map(([k, label, f]) =>
      `<button class="sumChip ${k} ${S.filter === f ? 'on' : ''}" data-f="${f}"` +
      ` title="只看${label}"><i></i>${label} <b>${n[k]}</b></button>`).join('');
  $$('.sumChip', el.listSummary).forEach(b => {
    b.onclick = () => {
      // Clicking the active one clears the filter, so the row is also the way
      // back to everything.
      S.filter = (S.filter === b.dataset.f) ? 'all' : b.dataset.f;
      saveSession({ filter: S.filter });
      S.idx = 0;
      loadQueue();
      // Keep the filtering bar at the top in step with the one in the list.
      renderTriage(S.state);
    };
  });

  // The jump label is about THIS list, so it does count the queue.
  let open = 0;
  for (const c of S.queue) if (!c.decision) open++;
  el.listJump.classList.toggle('done', open === 0);
  el.listJumpLabel.textContent = open
    ? `下一张未审（还有 ${open} 张）`
    : '这个列表里都审完了';
}

function highlightCurrent() {
  const prev = el.listScroll.querySelector('.listItem.current');
  if (prev) prev.classList.remove('current');
  const now = el.listScroll.querySelector(`.listItem[data-i="${S.idx}"]`);
  if (now) {
    now.classList.add('current');
    now.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

function updateListProgress() {
  const decided = S.queue.filter(c => c.decision).length;
  const pct = S.queue.length ? decided / S.queue.length * 100 : 0;
  el.listProgressFill.style.width = pct + '%';
  el.listCount.textContent = `${decided}/${S.queue.length}`;
}

function markListItem(i, decision) {
  const it = el.listScroll.querySelector(`.listItem[data-i="${i}"]`);
  if (!it) return;
  it.classList.remove('keep', 'reject', 'mark', 'pulse');
  if (decision) it.classList.add(decision);
  // Restart the highlight so a re-decision on the same row still registers.
  void it.offsetWidth;
  it.classList.add('pulse');
  updateListProgress();
  renderListSummary();
}

/* ───────────────────── 注入：列表自己能画，但换不了页面 ─────────────────────

   列表项被点击要换卡片（card.js 的 render）、汇总条被点击要重拉队列并让
   顶部筛选条跟着变（app.js 的 loadQueue / renderTriage）。这三件事都在上层，
   import 上去就成环，所以留同名占位符注入。 */
let render = () => {};
let loadQueue = async () => {};
let renderTriage = () => {};
function configure(hooks) {
  if (!hooks) return;
  if (hooks.render) render = hooks.render;
  if (hooks.loadQueue) loadQueue = hooks.loadQueue;
  if (hooks.renderTriage) renderTriage = hooks.renderTriage;
}



/** 选了两张以上就把右侧换成网格；一张都没有就关掉。
 *
 * 用动态 import：list.js 是基础模块，decidegrid.js 依赖它看的 S.queue，
 * 静态引入会成环。而且网格挂着也不该让列表挂掉。
 */
async function syncGrid() {
  try {
    const { DecideGrid } = await import('./decidegrid.js');
    if (S.sel.size >= 2) {
      // 每次都重新打开，不是只在没开的时候开：多选一张就要多一个格子，
      // 否则网格会一直停在第一次打开时的数量上。
      DecideGrid.open(Array.from(S.sel), (what) => {
        // 只有真的提交了才清空选择。
        // 这个回调在 syncGrid 自己关掉网格时也会跑（比如选中数掉到 1），
        // 那时候如果也清空，就会把用户刚点出来的选择一起抹掉 ——
        // 表现为"第一次 Ctrl+点没反应"。
        if (what === 'cancel') {
          // 用户按 Esc 退出多图模式：选择也要清掉，
          // 否则左侧还挂着一排选中，右侧已经是单图了。
          S.sel.clear();
          S.multi = false;
          render();
          return;
        }
        if (what !== 'commit') { render(); return; }
        const decided = new Set(S.sel);
        S.sel.clear();

        // 提交以后落到「第一个还没决策的」。不是简单 +1：
        // 选了 1,2,3,5,6，刚决定完的只有那五张，4 还没碰过 ——
        // 该跳回 4，而不是 7。连续的一组（5-8）自然就落到 9。
        const isDecided = (k) => decided.has(S.queue[k].id) || !!S.queue[k].decision;
        let start = -1, lastPos = -1;
        S.queue.forEach((c, k) => {
          if (!decided.has(c.id)) return;
          if (start < 0) start = k;
          lastPos = k;
        });
        let next = -1;
        for (let k = Math.max(0, start); k < S.queue.length; k++) {
          if (!isDecided(k)) { next = k; break; }
        }
        if (next < 0 && lastPos >= 0) next = Math.min(S.queue.length - 1, lastPos + 1);
        if (next >= 0) S.idx = next;
        render();
      });
    } else if (DecideGrid.isOpen()) {
      DecideGrid.closeQuiet();
    }
  } catch (e) {
    console.error('决策网格打开失败', e);
  }
}


/** 只更新「哪些行被选中」的样式，不重建列表。 */
function paintSelection() {
  $$('.listItem', el.listScroll).forEach((it) => {
    const i = +it.dataset.i;
    const id = S.queue[i] && S.queue[i].id;
    const on = id != null && S.sel.has(id);
    it.classList.toggle('sel', on);
    it.classList.toggle('current', i === S.idx);
  });
  if (typeof highlightCurrent === 'function') highlightCurrent();
}


// 用户关掉决策网格（Esc / 取消按钮）时，把左侧的选择一起清掉 ——
// 只剩下单图视图，左侧却还亮着一排，那是两套状态打架。
window.addEventListener('guopian:gridcancel', () => {
  // 无条件重画。之前这里是「size 为 0 就直接 return」，
  // 而 S.sel 可能已经被回调那条路清空了 —— size 是 0，DOM 里却还留着
  // 上一次 paintSelection() 加上的 .sel 类，于是左侧一直亮着。
  // 清什么不重要，重要的是把列表重画一遍。
  if (S.sel) S.sel.clear();
  S.multi = false;
  // 不能只靠 render()：这个模块里的 render 默认是空函数（app.js 通过
  // configure 注入，而 configure 在本项目里从没被调用过）。
  // 直接按当前 S.sel 重画一遍选中状态，才是真正把 .sel 类去掉的那一步。
  paintSelection();
  render();
});

export { posKey, savedPos, savePos, sessKey, savedSession, saveSession,
         pickStartIndex, itemHTML, observeThumbs,
  renderList, renderListSummary, highlightCurrent, updateListProgress,
  markListItem, configure
};
