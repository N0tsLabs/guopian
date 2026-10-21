/* 过片 Guopian — 网格视图：一次看很多张，可以框选批量决定。
 *
 * 为什么单独成模块：网格是另一个"页面"，它有自己的一次性 DOM 重绘、
 * 自己的选择集（S.sel）、自己的点击语义。把它留在 app.js 里，
 * 读卡片流程的人会不断撞见网格的分支。
 *
 * @requires ./state.js  el S LABEL
 * @requires ./core.js   $ api toast esc
 * @requires ./view.js   fitStage —— 关掉网格后要重新量一次舞台
 * @requires ./card.js   render
 *
 * configure({ loadQueue }) 注入：选中项落在当前队列之外时要重新拉队列，
 * 那是 app.js 的职责。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */

import { el, S, LABEL } from './state.js';
import { $, api, toast, esc, imgUrl } from './core.js';
import { fitStage } from './view.js';
import { render } from './card.js';

/* ═════════════════════════ 网格 ═════════════════════════ */

async function openGrid() {
  el.gridView.classList.remove('hidden');
  $('#appView').classList.add('hidden');
  await loadGrid();
}

function closeGrid() {
  el.gridView.classList.add('hidden');
  $('#appView').classList.remove('hidden');
  fitStage();
}

async function loadGrid() {
  S.filter = el.gridFilter.value || S.filter;
  S.sort = el.gridSort.value;
  let q;
  try { q = await api(`/api/queue?filter=${encodeURIComponent(S.filter)}&sort=${encodeURIComponent(S.sort)}`); }
  catch (e) { return; }
  const items = (q.items || []).slice(0, 1500);
  el.gridCount.textContent = `${q.total} 张` + (q.total > items.length ? `（显示前 ${items.length}）` : '');
  renderGrid(items);
  setSearchTitle('');
}

/* 卡片网格只画一次：队列和搜索结果用的是同一套格子。

   分开写会漂 —— 之前决策网格的那套就是因为两边各画一遍，搜索结果的
   decision 颜色、相似组角标全都不生效。 */
function renderGrid(items, emptyHtml) {
  if (!items.length && emptyHtml) {
    el.grid.innerHTML = `<div class="gridEmpty">${emptyHtml}</div>`;
    return;
  }
  el.grid.innerHTML = items.map(c => {
    const flags = (c.issues || []).slice(0, 3).map(i =>
      `<span class="flag ${i.severity}">${esc(i.label_zh)}</span>`).join('');
    return `<div class="cell ${c.decision || ''}" data-id="${c.id}">
      <img loading="lazy" src="${imgUrl(c.id, 'small')}" alt="">
      <div class="flags">${flags}</div>
      ${c.group_size > 1 ? `<div class="gmark">${c.group_rank}/${c.group_size}</div>` : ''}
      <div class="cap">${esc(c.name)}</div>
    </div>`;
  }).join('');
}

function setSearchTitle(text) {
  const t = el.gridSearchTitle;
  const clear = $('#gridSearchClear');
  if (!t) return;
  t.textContent = text || '';
  t.classList.toggle('hidden', !text);
  if (clear) clear.classList.toggle('hidden', !text);
}

/* 把一次 /api/search 的结果摊到网格里。
   没有结果时不说"0 张"，而是把词表里像的词提出来 —— 搜不到时候最需要的
   是下一步该搜什么。 */
async function showResults(res) {
  el.gridView.classList.remove('hidden');
  $('#appView').classList.add('hidden');
  const q = res.q || '';
  if (!res.ready) {
    el.gridCount.textContent = '';
    setSearchTitle('');
    renderGrid([], `画面识别还没完成，搜索暂时用不了。<br>` +
      `<button class="btn" id="sceneFetch">下载场景模型并开始识别</button>`);
    const btn = $('#sceneFetch');
    if (btn) {
      btn.onclick = async () => {
        btn.disabled = true;
        btn.textContent = '正在准备…';
        try {
          const r = await api('/api/models/fetch',
            { method: 'POST', body: JSON.stringify({ name: 'clip_vision.onnx' }) });
          if (!r.ok) throw new Error(r.error || '下载失败');
          await api('/api/embed', { method: 'POST', body: '{}' });
          toast('开始识别画面内容，可以先去干别的');
          btn.textContent = '正在识别…（进度看顶部）';
        } catch (e) {
          toast('准备失败：' + (e.message || e), 'err');
          btn.disabled = false;
          btn.textContent = '重试';
        }
      };
    }
    return;
  }
  if (res.tag === null) {
    const sug = (res.suggestions || []).map(w => `<b>${esc(w)}</b>`).join('、');
    el.gridCount.textContent = '';
    setSearchTitle('');
    renderGrid([], `词表里没有「${esc(q)}」。` +
      (sug ? `<br>要不要试试：${sug}` : ''));
    return;
  }
  if (!res.total) {
    el.gridCount.textContent = '';
    setSearchTitle(`搜索「${res.tag}」`);
    renderGrid([], `没有照片像「${esc(res.tag)}」（最高匹配度 ${res.best_z}，` +
      `低于阈值 ${res.zmin}）。<br>换一个词试试，比如「湖泊」「人像」「雪山」。`);
    return;
  }
  el.gridCount.textContent = `${res.total} 张`;
  setSearchTitle(`搜索「${res.tag}」`);
  renderGrid(res.items || []);
}

function onGridClick(e) {
  const cell = e.target.closest('.cell');
  if (!cell) return;
  const id = +cell.dataset.id;
  if (e.ctrlKey || e.metaKey || e.shiftKey) {
    S.sel.has(id) ? S.sel.delete(id) : S.sel.add(id);
    cell.classList.toggle('sel');
    return;
  }
  const at = S.queue.findIndex(x => x.id === id);
  closeGrid();
  if (at >= 0) { S.idx = at; render(); } else loadQueue();
}

async function decideSelected(action) {
  if (!S.sel.size) { toast('先 Ctrl+点击选中一些照片'); return; }
  const ids = Array.from(S.sel);
  await api('/api/decide', { method: 'POST', body: JSON.stringify({ ids, action }) });
  toast(`已把 ${ids.length} 张标为「${LABEL[action]}」`);
  S.sel.clear();
  loadQueue();
}

/* ───────────────────── 注入：选中项不在当前队列里时重拉 ─────────────────────

   onGridClick 要在当前队列里定位那张照片；找不到（例如换了筛选条件）就退回
   app.js 的 loadQueue()。 */
let loadQueue = async () => {};
function configure(hooks) {
  if (hooks && hooks.loadQueue) loadQueue = hooks.loadQueue;
}


export { openGrid, closeGrid, loadGrid, onGridClick, decideSelected, showResults,
  renderGrid, setSearchTitle, configure
};
