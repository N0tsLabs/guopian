/* 过片 Guopian — 卡片流程的接线层：生命周期、决策、对话框、以及所有模块的装配。
 *
 *  键盘：见 ? 帮助面板。三个决定的用词来自 config.DECISION_LABELS，
 *  经 /api/home 下发，这个文件里不写死 —— 改词只需要改 config.py 一处。
 *
 *  Nothing pressed means "not reviewed yet" — that is the whole pending state,
 *  which is why there is no 待定 or 跳过 button.
 *
 *  按住先预览，松手才真的决定。底部那几个按钮也可以直接用鼠标点。
 *
 *  这个文件是 ES module。它 import 别人，别人不 import 它 —— 依赖图在这里
 *  收口，所以 configure() 的装配全部集中在本文件末尾那段"接线"里：
 *  读一个模块的依赖，只需要看它的 import 段，不需要在源码里搜谁调了谁。
 *
 * @requires ./core.js       $ $$ api toast esc 与 Views（sleep/fmtCount 这个文件
 *                           从来没用过，所以现在也不 import 它们了）
 * @requires ./state.js      el S V cur LABEL VERDICT OWNED HOLD_CLASS RELEASE_CLASS
 * @requires ./view.js       fitStage layerTransform setCardOffset onWheel onDblClick
 * @requires ./physics.js    physReset setDragProgress 与四个鼠标入口 cancelDrag
 * @requires ./list.js       renderList renderListSummary markListItem pickStartIndex
 * @requires ./card.js       render renderActionState renderDecisionBadge placeStamp
 * @requires ./grid.js       openGrid closeGrid onGridClick decideSelected
 * @requires ./keys.js       onKeyDown onKeyUp
 * @requires web/index.html  every id this file looks up
 * @requires /api/home        labels, and `current` when a library is open
 * @requires /api/state       counts, issue_summary, labels
 * @requires /api/queue       the list and the card order
 *
 * 六个模块都导出名叫 configure 的注入函数，所以 import 时按模块起了别名
 * （configureView / configurePhysics / …），装配段读起来才知道是谁的。
 * 由 web/home.js 作为唯一入口 import（见那里的注释：这是修掉启动竞态的关键）。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */

import { $, $$, api, toast, esc, Views, imgUrl, setLibSlug } from './core.js';
import { el, S, V, cur, LABEL, VERDICT, OWNED, HOLD_CLASS, RELEASE_CLASS } from './state.js';
import { fitStage, layerTransform, setCardOffset, onWheel, onDblClick,
         configure as configureView } from './view.js';
import { physReset, setDragProgress, onStageDown, onDragMove, onDragEnd,
         cancelDrag, configure as configurePhysics } from './physics.js';
import { orderQueue, renderList, renderListSummary, markListItem, pickStartIndex,
         savedSession, saveSession, configure as configureList } from './list.js';
import { render, renderActionState, renderDecisionBadge, placeStamp,
         configure as configureCard } from './card.js';
import { openGrid, closeGrid, onGridClick, decideSelected,
         configure as configureGrid } from './grid.js';
import { onKeyDown, onKeyUp, configure as configureKeys } from './keys.js';

// Everything comes from core.js. This file knows nothing about home.js.
// （这一行本来是 const { $, $$, api, toast, esc, sleep, fmtCount } = G;
//   现在改成上面那行具名 import —— 依赖只写在一处，读文件头就够了。
//   sleep 和 fmtCount 在这个文件里从来没有被调用过，所以没有 import 进来。）

/** Seed the list with the user's preferred filter and sort.
 *
 * Applied when a library opens, not when the page loads: a later settings
 * change should affect the NEXT library rather than yank the list out from
 * under whatever is on screen right now.
 */
function applyDefaults(s) {
  if (!s) return;
  // The settings are what a NEW library starts from; what you were last doing
  // in THIS one wins, because that is the thing you were in the middle of.
  const sess = savedSession();
  S.filter = sess.filter || s.default_filter || S.filter;
  S.sort = sess.sort || s.default_sort || S.sort;
  if (s.confirm_apply !== undefined) S.confirmApply = !!s.confirm_apply;
}

function setLabels(labels) {
  if (!labels) return;
  const take = (target, src) => {
    if (!src) return;
    for (const k of Object.keys(target)) if (src[k]) target[k] = src[k];
  };
  take(LABEL, labels.decisions);
  take(VERDICT, labels.verdict);
  take(OWNED, labels.owned);
  // Anything already on screen was rendered with the old words.
  if (S.state) { renderTriage(S.state); renderListSummary(); }
}
// How long each departure takes. They differ on purpose: a discard should
// feel like it is falling away, a keep like it is being filed, and 精选 has
// to fit a whole stamping gesture in before the card leaves.
// These must stay >= the CSS animation durations (see evaluation/anim_check.py).
const EXIT_MS = { reject: 400, keep: 440, mark: 540 };
const UNMARK_MS = 370;

function grab() {
  Object.assign(el, {
    root: $('#rootLabel'), stats: $('#stats'), roBadge: $('#roBadge'),
    progressFill: $('#progressFill'), progressText: $('#progressText'),
  progPanel: null,
    cardWrap: $('#cardWrap'), photoStage: $('#photoStage'), photo: $('#photo'),
    photoHD: $('#photoHD'), photoLayer: $('#photoLayer'), photoCard: $('#photoCard'),
    zebra: $('#zebra'), overlay: $('#overlay'), issueTags: $('#issueTags'),
    histo: $('#histo'), histoCanvas: $('#histoCanvas'), metaLine: $('#metaLine'),
    groupBadge: $('#groupBadge'), verdictBadge: $('#verdictBadge'),
    previewVeil: $('#previewVeil'), previewStamp: $('#previewStamp'),
    zoomBadge: $('#zoomBadge'), decisionBadge: $('#decisionBadge'),
    emptyState: $('#emptyState'), emptyTitle: $('#emptyTitle'), emptyHint: $('#emptyHint'),
    triage: $('#triage'), triageChips: $('#triageChips'),
    listPane: $('#listPane'), listScroll: $('#listScroll'), listTitle: $('#listTitle'),
    listCount: $('#listCount'), listProgressFill: $('#listProgressFill'),
    listSummary: $('#listSummary'), listJump: $('#listJump'), listJumpLabel: $('#listJumpLabel'),
    listShow: $('#listShow'), listHide: $('#listHide'),
    gridView: $('#gridView'), grid: $('#grid'), gridSort: $('#gridSort'),
    gridFilter: $('#gridFilter'), gridCount: $('#gridCount'),
    modal: $('#modal'), sheet: $('#sheet'), help: $('#help'), browser: $('#browser'),
    coach: $('#coach'),
  });
}

/* ═════════════════════════ 生命周期 ═════════════════════════ */

/* One automatic attempt to get the face model.
 *
 * The model is not in the repository, so a fresh clone has no face detection
 * until it is downloaded. Asking the user to read a README and run a script is
 * a step that only exists because of a packaging choice; the app can just fetch
 * it. Guarded so it runs at most once per session and never blocks the list.
 */
let _modelTried = false;

async function ensureFaceModel() {
  if (_modelTried) return;
  _modelTried = true;
  try {
    const st = await api('/api/models');
    // The key is the filename, not the bare model name.
    const m = (st.models || {})['face_landmarker.task'] || {};
    if (m.present) return;
    toast('正在下载人脸模型（3.6 MB），第一次需要一点时间…');
    const r = await api('/api/models/fetch', { method: 'POST', body: '{}' });
    if (r && r.ok) {
      toast('人脸模型已就绪，重新分析后生效');
      loadState();
    } else {
      toast('人脸模型下载失败：' + ((r && r.error) || '未知原因'), 'err');
      _modelTried = false;
    }
  } catch (e) {
    _modelTried = false;
  }
}

// 进度条的点击在模块加载时就绑上。
// 之前放在 start() 里，而已打开的库在刷新后走的是 attach()，不走 start()
// —— 于是刷新一次，进度条就再也点不开了。
(function bindProgressClick() {
  const pw = document.getElementById('progressWrap');
  if (!pw) return;
  pw.onclick = (e) => { e.stopPropagation(); toggleProgPanel(); };
  pw.title = '点击查看分类明细';
})();

function start() {
  ensureFaceModel();
  if (!S.running) { grab(); bind(); S.running = true; }
  S.filter = 'all'; S.idx = 0;
  loadState().then(loadQueue);
  tick();
  showCoachOnce();
}

/* ───────────────────── 首次分析：进度 + 分类图表 ─────────────────────

   打开一个还没分析过的文件夹时，先过这一道门：整页显示进度条和分类图表，
   分析完再进入过图页面。为什么不让它边分析边过图 —— 因为分析没完成时
   "建议过/不过"还没有（它要按整批照片的分布才有意义），先让人看一堆
   半成品判断、再全部变一遍，比等一下更难受。

   已有分析结果的库（重新打开）直接跳过，不弹这一屏。 */
function needsBoot(st) {
  if (!st || !st.counts) return false;
  // 服务端直接告诉我们该不该先看整页进度。用 "analyzed < total" 自己算会
  // 漏掉最关键的一段：刚打开的库在扫描完成之前 total 还是 0，条件不成立，
  // 于是整页进度被跳过，只剩左上角那条细线。
  if (typeof st.boot_needed === 'boolean') return st.boot_needed;
  const p = st.progress || {};
  if (p.running) return true;
  const total = st.counts.total || 0;
  const analyzed = st.counts.analyzed || 0;
  return !!total && analyzed < total;
}

async function runBoot(initial) {
  Views.show('bootView');
  bindBoot();
  let st = initial;
  renderBoot(st);
  const deadline = Date.now() + 1000 * 60 * 60 * 6;   // 六小时，够扫一个硬盘
  while (Date.now() < deadline) {
    await wait(600);
    try { st = await api('/api/state'); }
    catch (e) { return; }                             // 库被关了之类，交给上层
    renderBoot(st);
    const phase = (st.progress && st.progress.phase) || 'idle';
    const analyzed = (st.counts && st.counts.analyzed) || 0;
    const total = (st.counts && st.counts.total) || 0;
    const settled = ['done', 'error', 'cancelled'].includes(phase);
    if (settled || (total && analyzed >= total && !st.progress.running)) return;
  }
}

function bindBoot() {
  if (S.bootBound) return;
  S.bootBound = true;
  const btn = $('#bootCancel');
  if (btn) {
    btn.onclick = async () => {
      try { await api('/api/cancel', { method: 'POST', body: '{}' }); } catch (e) { /* 忽略 */ }
      toast('已取消分析，剩下的照片下次打开再继续');
    };
  }
}

function renderBoot(st) {
  if (!st) return;
  const p = st.progress || {};
  const total = p.total || (st.counts && st.counts.total) || 0;
  const done = p.done || 0;
  // 进度条用服务端算好的 overall：分段跑的时候它按段加权、且只增不减。
  // 直接用 done/total 会出现"分析跑到 100% → 换阶段又回到 0%"的跳变。
  const pct = typeof p.overall === 'number'
    ? Math.min(100, Math.round(p.overall * 100))
    : (total ? Math.min(100, Math.round(done / total * 100)) : 0);

  const name = (st.root || '').split(/[\\/]/).filter(Boolean).pop() || '';
  $('#bootName').textContent = name;
  $('#bootFill').style.width = pct + '%';

  // 阶段换名字：扫描 / 分析 / 提取特征 / 分组。
  // 现在向量是在逐张分析时一起算的，正常不会单独出现"提取特征"那一段；
  // 只有补旧库时才会，而且这时进度条用的是 overall（只增不减），不会倒退。
  const analyzed = (st.counts && st.counts.analyzed) || 0;
  const photoTotal = (st.counts && st.counts.total) || total;
  const phase = p.phase || '';
  const label = phase === 'embed' ? '提取特征'
    : phase === 'evaluate' ? '分组'
      : phase === 'scan' ? '扫描' : '分析';
  const bits = [`${label} ${done}/${total}`, `${pct}%`];
  if (phase === 'embed' && photoTotal) {
    bits.splice(1, 0, `照片 ${analyzed}/${photoTotal}`);
  }
  if (p.rate) bits.push(`${p.rate.toFixed(1)}/s`);
  if (p.eta) bits.push(`剩 ~${fmtEta(p.eta)}`);
  $('#bootSub').textContent = bits.join(' · ');

  const msg = p.message || '';
  const cur = p.current ? `正在处理 ${p.current}` : '';
  $('#bootNums').textContent = [msg, cur].filter(Boolean).join('　');

  const rows = (st.boot && st.boot.rows) || [];
  const chart = $('#bootChart');
  const empty = $('#bootChartEmpty');
  empty.classList.toggle('hidden', rows.length > 0);
  // 条形长度按当前最大的一类归一化：早期只有十几张时，绝对值都很小，
  // 用百分比当分母会全部顶满，看不出差别。
  const peak = rows.reduce((m, r) => Math.max(m, r.count), 0) || 1;
  chart.innerHTML = rows.map(r => {
    const w = Math.max(2, Math.round(r.count / peak * 100));
    return `<div class="bootRow ${r.sev ? 'sev-' + r.sev : ''}">
      <span class="lbl" title="${esc(r.label)}">${esc(r.label)}</span>
      <span class="track"><i style="width:${w}%"></i></span>
      <span class="num">${r.count}</span>
    </div>`;
  }).join('');
}

/** 打开库之后的统一入口：需要分析就先过首屏，否则直接进过图。 */
async function enter() {
  let st = null;
  try { st = await api('/api/state'); } catch (e) { /* 交给 start 里再报 */ }
  if (needsBoot(st)) await runBoot(st);
  Views.show('appView');
  start();
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

function attach() {
  if (!S.running) { grab(); bind(); S.running = true; }
  loadState().then(loadQueue);
  tick();
}

function stop() {
  clearInterval(S.poll); S.poll = null;
  S.queue = []; S.idx = 0;
}

function tick() {
  clearInterval(S.poll);
  S.poll = setInterval(loadState, 4000);
}

async function loadState() {
  let st;
  try { st = await api('/api/state'); }
  catch (e) {
      // 409 = 库被关掉了。回首页并刷新项目列表是 home.js 的事，而 home.js
      // import 本文件，所以这里只能调用注入进来的回调（见文件末尾的接线）。
      if (e.status === 409) { stop(); Views.show('homeView'); onLibraryClosed(); }
    return;
  }
  S.state = st;
  // 图片地址要带库的身份，否则换项目后浏览器会拿上一个项目的缓存（见 core.js）。
  // 放在这里是因为 loadState 一定先于 loadQueue / render 跑完。
  setLibSlug(st.slug);
  if (S.generation !== -1 && st.generation !== S.generation) loadQueue();
  S.generation = st.generation;

  el.root.textContent = st.root; el.root.title = st.root;
  el.roBadge.classList.toggle('hidden', !st.read_only);
  renderStats(st);
  renderProgress(st.progress);
  renderTriage(st);
}

function renderStats(st) {
  const d = st.counts.decisions || {};
  const reviewed = (d.keep || 0) + (d.reject || 0) + (d.mark || 0);
  const left = Math.max(0, (st.counts.total || 0) - reviewed);
  const parts = [`<span>共 <b>${st.counts.total}</b></span>`];
  if (d.keep) parts.push(`<span style="color:#7ee787">${LABEL.keep} <b>${d.keep}</b></span>`);
  if (d.reject) parts.push(`<span style="color:#ffa39c">${LABEL.reject} <b>${d.reject}</b></span>`);
  if (d.mark) parts.push(`<span style="color:#f5cd5c">${LABEL.mark} <b>${d.mark}</b></span>`);
  parts.push(`<span>未审 <b>${left}</b></span>`);
  const fa = st.face_available || {};
  if (!fa.ok) parts.push(`<span style="color:#f0c850" title="${esc(fa.message || '')}">人脸检测未启用</span>`);
  el.stats.innerHTML = parts.join('');
}

/** 秒数说人话：2 分钟比 134 秒好读。 */
function fmtEta(sec) {
  const s = Math.ceil(sec);
  if (s < 60) return s + ' 秒';
  const m = Math.floor(s / 60);
  return m + ' 分' + (s % 60 ? ' ' + (s % 60) + ' 秒' : '');
}

/** 点进度条展开的分类明细。
 *
 * 类别直接从左边那条筛选条读 —— 它是唯一一处算这些数字的地方，
 * 再算一遍迟早会和它对不上。 */
function drawProgPanel(p) {
  const panel = el.progPanel;
  if (!panel) return;
  const rows = [];
  const total = (S.state && S.state.counts && S.state.counts.total) || p.total || 0;
  // 分析跑完以后 p.done 会归零，这时要读 state 里的已分析张数，
  // 否则面板上写着「已分析 0 / 93」，明明全都分析完了。
  const done = p.running ? (p.done || 0)
    : ((S.state && S.state.counts && S.state.counts.analyzed) || p.done || total);

  rows.push(`<div class="progRow"><span class="nm">已分析</span>
    <span class="n">${done} / ${total}</span></div>
    <div class="progBar2"><i style="width:${total ? Math.round(100 * done / total) : 0}%"></i></div>`);

  const chips = document.querySelectorAll('#triageChips .chip');
  const found = [];
  chips.forEach((c) => {
    const t = (c.textContent || '').trim();
    const m = t.match(/^(.*?)\s*(\d+)$/);
    if (!m) return;
    const n = +m[2];
    if (!n) return;
    if (/^(全部|未审|过|不过|精选|有明显问题|有人脸|连拍|相似组)$/.test(m[1].trim())) return;
    found.push([m[1].trim(), n]);
  });
  found.sort((a, b) => b[1] - a[1]);
  if (found.length) {
    rows.push('<h4 style="margin-top:10px">检测到的问题</h4>');
    const mx = found[0][1] || 1;
    found.forEach(([nm, n]) => {
      rows.push(`<div class="progRow"><span class="nm">${esc(nm)}</span>
        <span class="n">${n}</span></div>
        <div class="progBar2"><i style="width:${Math.round(100 * n / mx)}%"></i></div>`);
    });
  }
  // 面板底部：全部重新分析。
  // 只在"没在跑"的时候给按钮 —— 分析中再点一次没有任何意义。
  const running = !!(p && p.running);
  rows.push(`<div class="progFoot">
      <button class="btn ghost small" id="progReanalyze" ${running ? "disabled" : ""}>
        全部重新分析</button>
      <span class="progHint">${running ? "分析中…" : "照片不会被移动或删除"}</span>
    </div>`);
  panel.innerHTML = rows.join('');
  const btn = panel.querySelector('#progReanalyze');
  if (btn) btn.onclick = (ev) => { ev.stopPropagation(); reanalyzeAll(btn); };
}

/** 全部重新分析：清掉分析结果重跑一遍（等价于重新打开一个没分析过的库）。 */
async function reanalyzeAll(btn) {
  const old = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '重置中…'; }
  try {
    const r = await api('/api/reanalyze', { method: 'POST', body: '{}' });
    if (!r.ok) { toast(r.error || '无法重新分析', 'err'); if (btn) { btn.disabled = false; btn.textContent = old; } return; }
    if (_progOpen) toggleProgPanel();
    await enter();          // 走统一入口：整页进度条会重新出现
  } catch (e) {
    toast('无法重新分析', 'err');
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

let _progOpen = false;

/** 点顶栏的进度条，展开 / 收起分类明细。 */
function toggleProgPanel() {
  if (!el.progPanel) {
    el.progPanel = document.createElement('div');
    el.progPanel.className = 'progPanel hidden';
    document.body.appendChild(el.progPanel);
  }
  _progOpen = !_progOpen;
  el.progPanel.classList.toggle('hidden', !_progOpen);
  if (!_progOpen) return;
  drawProgPanel(S.lastProgress || {});
  // 贴在进度条正下方、左对齐展开。
  //
  // 之前是写死的 right:12px;top:44px —— 弹框跑到了屏幕右边，离点它的
  // 地方隔着一整条界面，用户第一反应是"点了没反应"。弹框要贴着它的锚点。
  const anchor = document.getElementById('progressWrap');
  if (!anchor) return;
  const r = anchor.getBoundingClientRect();
  const w = Math.min(320, window.innerWidth - 24);
  el.progPanel.style.width = w + 'px';
  el.progPanel.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
  el.progPanel.style.top = Math.round(r.bottom + 6) + 'px';
}

function renderProgress(p) {
  S.lastProgress = p;   // 点开明细时要用最近一次的数据
  const pct = p.total ? Math.round(100 * p.done / p.total) : 0;
  el.progressFill.style.width = pct + '%';
  const bar = document.querySelector('.progressBar');
  if (bar) bar.classList.toggle('running', !!p.running);

  if (p.running) {
    const what = p.phase === 'scan' ? '扫描' : '分析';
    el.progressText.textContent =
      `${what} ${p.done}/${p.total} · ${pct}% · ${p.rate || 0}/s` +
      (p.eta ? ` · 剩 ~${fmtEta(p.eta)}` : '');
  } else if (p.phase === 'done') {
    const n = (S.state && S.state.counts && S.state.counts.analyzed) || p.total || 0;
    el.progressText.textContent = `分析完成 · ${n} 张 · ${p.elapsed}s`;
  } else if (p.phase === 'error') {
    el.progressText.textContent = '分析出错，见日志';
  } else {
    el.progressText.textContent = p.message || '';
  }
  if (el.progPanel && !el.progPanel.classList.contains('hidden')) drawProgPanel(p);
}

function renderTriage(st) {
  const defs = [
    ['all', '全部'], ['pending', '未审'], ['keep', LABEL.keep],
    ['reject', LABEL.reject], ['mark', LABEL.mark],
    ['issues', '有明显问题'], ['faces', '有人脸'], ['groups', '连拍 / 相似组'],
  ];
  const chips = defs.map(([f, label]) =>
    `<button class="chip ${S.filter === f ? 'on' : ''}" data-f="${f}">${label}</button>`);
  for (const it of (st.issue_summary || [])) {
    chips.push(`<button class="chip ${S.filter === 'issue:' + it.kind ? 'on' : ''}"
      data-f="issue:${it.kind}">${esc(it.label_zh)}<span class="n">${it.n}</span></button>`);
  }
  el.triageChips.innerHTML = chips.join('');
  $$('.chip', el.triageChips).forEach(c => {
    c.onclick = () => { S.filter = c.dataset.f; S.idx = 0; saveSession({ filter: S.filter }); loadQueue(); renderTriage(S.state); };
  });
  const gf = el.gridFilter;
  if (gf && !gf.options.length) {
    gf.innerHTML = defs.map(([v, t]) => `<option value="${v}">${t}</option>`).join('');
  }
  const titles = { all: '全部照片', pending: '未审', keep: LABEL.keep,
                   reject: LABEL.reject, mark: LABEL.mark };
  el.listTitle.textContent = titles[S.filter] ||
    (S.filter === 'issues' ? '有明显问题'
      : S.filter === 'faces' ? '有人脸'
      : S.filter === 'groups' ? '连拍 / 相似组'
      : S.filter.startsWith('issue:') ? '按问题筛选' : S.filter);
}

/* ═════════════════════════ 队列 + 左侧列表 ═════════════════════════ */

async function loadQueue() {
  let q;
  try { q = await api(`/api/queue?filter=${encodeURIComponent(S.filter)}&sort=${encodeURIComponent(S.sort)}`); }
  catch (e) { return; }
  // 用列表真正显示的顺序（相似组聚在一起、组内按排名），而不是服务器顺序。
  // 两套顺序并存时，键盘按 S.idx 走一条、眼睛看的是另一条 —— 那就是"按下一张
  // 却跳到组里最后一张、再跳回第一张"的来源。
  S.queue = orderQueue(q.items || []);
  S.idx = pickStartIndex();
  renderList();
  render();
}

/* ═════════════════════════ 按住预览 ═════════════════════════ */

let hold = null;

/** Pressing 精选 on a photo that is already 精选 takes the mark back. */
function isUnmark(action) {
  const c = cur();
  return action === 'mark' && !!c && c.decision === 'mark';
}

function startHold(action) {
  if (hold || S.animating || !cur() || S.busy) return;
  if (!HOLD_CLASS[action]) return;
  hold = { action, off: isUnmark(action) };
  el.photoStage.classList.add(HOLD_CLASS[action]);
  el.previewStamp.textContent = LABEL[action] || '';
  // The keyboard has no drag to measure, so it drives the same progress
  // numbers straight to 1 -- which means the overlay animates in under the
  // stage's transition instead of snapping.
  if (action === 'mark') setDragProgress(0, 0, 1);
  else if (action === 'reject') setDragProgress(1, 0, 0);
  else setDragProgress(0, 1, 0);
  const btn = $(`.act[data-act="${action}"]`);
  if (btn) btn.classList.add('active');
}

function resetHoldVisual() {
  Object.values(HOLD_CLASS).forEach(c => el.photoStage.classList.remove(c));
  Object.values(RELEASE_CLASS).forEach(c => el.photoStage.classList.remove(c));
  el.photoStage.classList.remove('dragging', 'release-mark-off');
  physReset();
  setDragProgress(0, 0, 0);
  el.previewStamp.style.setProperty('--stamp-dx', '0px');
  el.photoCard.style.transform = '';
  setCardOffset(0, 0);
  el.photoLayer.classList.remove('nofx');
  if (V.bw) el.photoLayer.style.transform = layerTransform(0, 0);
  $$('.act.active').forEach(b => b.classList.remove('active'));
  hold = null;
}

/** Play the departure animation and resolve when the card is gone. */
function flyOut(action) {
  S.animating = true;
  return new Promise(resolve => {
    el.photoStage.classList.remove(HOLD_CLASS[action]);
    // The veil has no release rule of its own -- it is pure progress -- so
    // zeroing this is what makes it retreat as the card flies. The stamp is
    // under an animation from here on, so it is unaffected.
    setDragProgress(0, 0, 0);
    // A key press has no velocity behind it, so this stays on the CSS
    // keyframes: there is no gesture to carry. 精选 is picked up, not thrown.
    el.photoStage.classList.add(RELEASE_CLASS[action]);
    // The card behind rises at the same time, so the two read as one motion.
    setTimeout(() => {
      el.photoStage.classList.remove(RELEASE_CLASS[action]);
      resolve();
    }, EXIT_MS[action] || 300);
  });
}

function endHold(commit) {
  if (!hold) return;
  const { action, off } = hold;
  hold = null;
  $$('.act.active').forEach(b => b.classList.remove('active'));

  if (!commit) { resetHoldVisual(); return; }

  if (off) {
    // Taking the mark back: the seal lifts off and the card does not move.
    // 精选 is the only decision that ADDS something, so undoing it looks like
    // removing that thing -- and since the photo is not being filed away,
    // there is no reason to jump to the next one.
    S.animating = true;
    el.photoStage.classList.add('release-mark-off');
    setTimeout(() => {
      resetHoldVisual();
      S.animating = false;
      commitClear();
    }, UNMARK_MS);
    return;
  }

  el.photoStage.classList.remove(HOLD_CLASS[action]);
  flyOut(action).then(() => { S.animating = false; commitDecision(action); });
}

/* ═════════════════════════ 决策 ═════════════════════════ */

/** Write a decision to the server, OFF the critical path.
 *
 * This used to be awaited BEFORE render(), so the sequence was: outgoing card
 * flies away (400ms), then the stage sits empty for a whole round-trip, then
 * the next card finally starts rising. The round-trip measured 3.7ms median
 * but 196.7ms at worst, and any of those outliers is a visible catch.
 *
 * The client state is already updated optimistically by the caller, so the
 * only thing this does is persist it and shout if the write fails.
 */
let savesInFlight = 0;
async function saveDecision(id, action) {
  savesInFlight++;
  try {
    await api('/api/decide', { method: 'POST', body: JSON.stringify({ id, action }) });
  } catch (e) {
    toast('保存失败，这一张可能没记上', 'err');
  }
  if (--savesInFlight === 0) loadState();
}

function commitDecision(action) {
  const c = cur();
  S.animating = false;
  if (!c) { resetHoldVisual(); return; }

  const at = S.idx;
  // Show the next card FIRST. Awaiting the server here left nothing on screen
  // to animate: the outgoing card had already gone and the incoming one had
  // not been rendered yet.
  c.decision = action;
  markListItem(at, action);
  S.idx++;
  render();
  saveDecision(c.id, action);
}

/** Take back the 精选 mark. Stays on the photo: nothing is being filed away. */
async function commitClear() {
  const c = cur();
  if (!c || S.busy) { resetHoldVisual(); return; }
  S.busy = true;
  try { await api('/api/decide', { method: 'POST', body: JSON.stringify({ id: c.id, action: 'clear' }) }); }
  catch (e) { toast('保存失败', 'err'); }

  c.decision = null;
  markListItem(S.idx, null);
  S.busy = false;
  // Deliberately NOT render(): that would replay the arrival animation and
  // look like a new photo had loaded, when all that changed is a badge.
  renderDecisionBadge(c);
  renderActionState(c);
  renderStats(S.state);
  toast('已取消' + LABEL.mark);
}

/** A direct, animated decision (toolbar / grid / click). */
async function decide(action) {
  if (S.busy || !cur()) return;
  await flyOut(action);
  commitDecision(action);
}

async function undo() {
  try {
    const r = await api('/api/undo', { method: 'POST' });
    if (!r.ok) { toast('没有可撤销的操作'); return; }
    toast('已撤销');
    const id = r.result.photo_id;
    const at = S.queue.findIndex(x => x.id === id);
    if (at >= 0) {
      S.queue[at].decision = r.result.restored_to || null;
      markListItem(at, S.queue[at].decision);
      S.idx = at;
      render();
    } else {
      await loadQueue();
    }
    loadState();
  } catch (e) { toast('撤销失败', 'err'); }
}

/** Navigation only -- it never touches the decision. */
function slide(fromX) {
  el.photoStage.animate(
    [{ transform: `translateX(${fromX}px)`, opacity: .35 }, { transform: 'none', opacity: 1 }],
    { duration: 190, easing: 'cubic-bezier(.22,.61,.36,1)' });
}

function prevPhoto() {
  if (S.idx <= 0) { toast('已经是第一张了'); return; }
  S.idx--;
  slide(-40);
  render();
}

function nextPhoto() {
  if (S.idx >= S.queue.length - 1) { toast('已经是最后一张了'); return; }
  S.idx++;
  slide(40);
  render();
}

function runAction(a) {
  if (a === 'undo') return undo();
  if (a === 'prev') return prevPhoto();
  if (a === 'next') return nextPhoto();
  if (HOLD_CLASS[a]) {
    // Mouse path: a click IS the intent, so there is nothing to preview.
    // Play the hold state for one frame anyway so the veil and stamp are
    // part of the same gesture rather than appearing only for keyboards.
    startHold(a);
    setTimeout(() => endHold(true), 90);
    return;
  }
  return decide(a);
}

/* ═════════════════════════ 应用决策 ═════════════════════════ */

/** "10-16 15:01" -- enough to tell two applies apart, short enough for a row. */
function fmtWhen(sec) {
  if (!sec) return '';
  const d = new Date(sec * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function applyDialog() {
  let pv;
  try { pv = await api('/api/apply/preview?mode=quarantine'); }
  catch (e) { toast('读取失败', 'err'); return; }
  // 不在这里 return。没有要移动的照片时，这一屏仍然是「撤销上次归档」和
  // 「重置全部决策」唯一能进来的地方 —— 审完了就把门关上，等于这两个功能
  // 永远用不到。改成在对话框里写清楚「没有要移动的」。
  const ro = S.state && S.state.read_only;
  // Undo lives on the screen where applying happens. A separate history page is
  // a place nobody visits until after they already wanted it.
  const last = (pv.history || [])[0];
  const undoBar = last ? `
    <div class="undoBar">
      <span>上次归档：<b>${last.n}</b> 张 · ${fmtWhen(last.at)}</span>
      <button class="btn ghost" id="apUndo">把上次归档撤回</button>
    </div>` : '';
  // 重置放在这屏：想从头再来的时候，人就在这个对话框里。
  // 它清的是决策，不动任何文件，而且整批可撤回。
  const resetBar = `
    <div class="undoBar resetBar">
      <span>想从头再来：清掉全部判断，并把归档出去的照片搬回原目录。</span>
      <button class="btn ghost" id="apReset">重置全部决策</button>
    </div>`;
  el.sheet.innerHTML = `
    <h2>应用决策</h2>
    <p class="muted small">筛选过程没有动过任何文件。下面是即将执行的唯一一次文件操作。</p>
    ${undoBar}
    ${resetBar}
    ${pv.count ? `<h3>将把 <b style="color:#ff8b84">${pv.count}</b> 张照片归入三个文件夹</h3>`
               : '<h3 class="muted">没有要移动的照片 —— 审过的都已经归档了</h3>'}
    ${pv.groups.map(g => `
      <div class="applyRow">
        <span class="applyTag d-${g.decision}">${esc(g.label)}</span>
        <b>${g.count}</b> 张
        <code>${esc(g.path)}</code>
      </div>`).join('')}
    <p class="muted small" style="margin-top:8px">
      ${pv.undecided} 张还没审的<b>留在原地</b>，不会被动 —— 这三个文件夹只表达筛完的结果。
    </p>
    <p class="muted small">共约 ${pv.total_mb} MB</p>
    <p class="muted small" style="margin-top:12px">扫一眼下面这些照片，确认没有误判：</p>
    <div class="applyGrid">
      ${pv.items.map(i => `<img loading="lazy" src="${imgUrl(i.id, 'small')}" class="d-${i.decision}" title="${esc(i.rel_path)}">`).join('')}
    </div>
    ${pv.truncated ? `<p class="muted small">…还有 ${pv.truncated} 张未显示</p>` : ''}
    ${ro ? `<p class="muted small" style="color:#e3b341">本库以只读方式打开，不会移动文件。</p>` : ''}
    <p class="muted small">
      「只做星标，不搬文件」不移动任何照片，只把判断写成星标
      （不过 = 1 星，其余 = 0 星）。接着用 Lightroom 或 Bridge 的人，
      缩略图上会直接看到这个星标。
    </p>
    <div class="rowBtns">
      <button class="btn ghost" id="apCancel">取消</button>
      <button class="btn ghost" id="apXmp" title="把「不过」写成 1 星、其余写成 0 星，存进照片的星标信息里。文件留在原处，Lightroom / Bridge 能直接读到。">只做星标，不搬文件</button>
      <button class="btn primary" id="apGo" ${ro ? 'disabled' : ''}>确认移动 ${pv.count} 张</button>
    </div>`;
  const resetBtn = $('#apReset');
  if (resetBtn) {
    resetBtn.onclick = async () => {
      // 这个函数里没有 st 这个变量，只有 S.state —— 之前写成 st 会当场
      // ReferenceError，表现就是"按钮点了没反应"。
      const d = (S.state && S.state.counts && S.state.counts.decisions) || {};
      const n = (d.keep || 0) + (d.mark || 0) + (d.reject || 0);
      // 二次确认：这个动作会搬文件，点两次。
      if (!window.confirm(`要把这个项目整个重置吗？\n\n1. 清掉全部 ${n} 张判断\n2. 把已经归档到三个文件夹里的照片，全部搬回原目录\n\n照片不会被删除，只是回到最开始的未审状态。\n这个操作不可撤销。`)) return;
      const r = await api('/api/reset', { method: 'POST', body: JSON.stringify({ confirm: true }) });
      if (!r || !r.ok) { toast('重置失败：' + ((r && r.error) || ''), 'err'); return; }
      closeModal();
      toast(`已清掉 ${r.result.cleared} 张决策，全部回到未看状态`);
      await loadState();
      loadQueue();
    };
  }

  const undoBtn = $('#apUndo');
  if (undoBtn) {
    undoBtn.onclick = async () => {
      undoBtn.disabled = true;
      try {
        const r = await api('/api/rollback', {
          method: 'POST', body: JSON.stringify({ batch: last.batch }),
        });
        if (!r.ok) { toast(r.error || '撤回失败', 'err'); undoBtn.disabled = false; return; }
        toast(`已撤回 ${r.restored} 张照片，回到原来的位置`);
        closeModal();
        await loadQueue();
      } catch (e) {
        toast((e.body && e.body.error) || '撤回失败', 'err');
        undoBtn.disabled = false;
      }
    };
  }
  el.modal.classList.remove('hidden');
  $('#apCancel').onclick = closeModal;
  $('#apXmp').onclick = () => doApply('xmp');
  if (!ro) $('#apGo').onclick = () => doApply('quarantine');
}

async function doApply(mode) {
  // 移动文件是按请求同步做的：几百张跨目录移动要几秒。期间必须给个反馈，
  // 否则按钮按下去"没反应"，人会再点一次。禁用它 + 换个文案就够。
  const go = $('#apGo');
  const label = go ? go.textContent : '';
  if (go) { go.disabled = true; go.textContent = '正在移动…'; }
  try {
    const r = await api('/api/apply', { method: 'POST', body: JSON.stringify({ mode, confirm: true }) });
    if (!r.ok) { toast(r.error || '失败', 'err'); return; }
    closeModal();
    toast(`已移动 ${r.moved} 张到隔离文件夹，可随时回滚`, 'warn');
    await loadQueue();
    loadState();
    showRollback(r.batch, r.moved);
  } catch (e) {
    toast('失败', 'err');
  } finally {
    if (go) { go.disabled = false; go.textContent = label; }
  }
}

function showRollback(batch, n) {
  el.sheet.innerHTML = `
    <h2>完成</h2>
    <p>已把 <b>${n}</b> 张照片移动到隔离文件夹。原照片没有被删除。</p>
    <p class="muted small">想反悔的话，随时点下面这个按钮，文件会回到原来的位置。</p>
    <div class="rowBtns">
      <button class="btn ghost" id="rbClose">关闭</button>
      <button class="btn primary" id="rbGo">撤销这次移动（回滚 ${n} 张）</button>
    </div>`;
  el.modal.classList.remove('hidden');
  $('#rbClose').onclick = closeModal;
  $('#rbGo').onclick = async () => {
    const r = await api('/api/rollback', { method: 'POST', body: JSON.stringify({ batch }) });
    toast(r.ok ? `已回滚 ${r.restored} 张` : (r.error || '回滚失败'), r.ok ? '' : 'err');
    closeModal();
    await loadQueue();
    loadState();
  };
}

function closeModal() { el.modal.classList.add('hidden'); }

/* ═════════════════════════ 首次引导 ═════════════════════════ */

function showCoachOnce() {
  let seen = null;
  try { seen = localStorage.getItem('guopian.coach'); } catch (e) { seen = null; }
  if (seen !== '1' && seen !== 'never') el.coach.classList.remove('hidden');
}

/* ═════════════════════════ 绑定 ═════════════════════════ */

let bound = false;
function bind() {
  if (bound) return;
  bound = true;
  grab();

  // Bottom toolbar. The three big buttons behave like their keys do -- hold
  // to preview, release to commit -- so mouse and keyboard stay one gesture.
  // The small ones act on click because there is nothing to preview.
  $$('.act[data-act]').forEach(b => {
    const act = b.dataset.act;
    b.addEventListener('mousedown', e => { e.preventDefault(); startHold(act); });
    b.addEventListener('mouseenter', e => { if (e.buttons === 1) startHold(act); });
  });
  $$('.act2[data-act]').forEach(b => {
    b.addEventListener('click', () => runAction(b.dataset.act));
  });
  document.addEventListener('mouseup', () => { if (hold) endHold(true); });

  $('#btnGrid').onclick = openGrid;
  $('#btnGridClose').onclick = closeGrid;
  $('#btnTriage').onclick = () => el.triage.classList.toggle('hidden');
  $('#btnHelp').onclick = () => el.help.classList.remove('hidden');
  // With the confirmation switched off, the button applies immediately.
  // The dialog is a safety net, not the only way in.
  $('#btnApply').onclick = () => (S.confirmApply === false ? doApply('quarantine') : applyDialog());
  $('#hintMore').onclick = () => el.help.classList.remove('hidden');
  $('#helpClose').onclick = () => el.help.classList.add('hidden');
  $('#listHide').onclick = () => setList(false);
  $('#listShow').onclick = () => setList(true);
  el.listJump.onclick = () => {
    const at = S.queue.findIndex(c => !c.decision);
    if (at < 0) { toast('这个列表里都决定完了'); return; }
    const before = S.idx;
    S.idx = at;
    render();
    toast(before === at ? '当前就是这一张' : `跳到第 ${at + 1} 张`);
  };

  $('#coachOk').onclick = () => {
    el.coach.classList.add('hidden');
    try { localStorage.setItem('guopian.coach', '1'); } catch (e) {}
  };
  $('#coachNever').onclick = () => {
    el.coach.classList.add('hidden');
    try { localStorage.setItem('guopian.coach', 'never'); } catch (e) {}
  };
  el.coach.onclick = (e) => { if (e.target === el.coach) $('#coachOk').click(); };

  el.gridSort.onchange = () => { S.sort = el.gridSort.value; loadQueue(); };
  el.gridFilter.onchange = () => { S.filter = el.gridFilter.value; loadQueue(); };
  el.grid.onclick = onGridClick;
  $('#gridDecideKeep').onclick = () => decideSelected('keep');
  $('#gridDecideReject').onclick = () => decideSelected('reject');

  el.photoStage.addEventListener('mousedown', onStageDown);
  el.photoStage.addEventListener('dblclick', onDblClick);
  el.cardWrap.addEventListener('wheel', onWheel, { passive: false });
  window.addEventListener('mousemove', onDragMove);
  window.addEventListener('mouseup', onDragEnd);
  // The arrival class only exists to carry the keyframes. Drop it when they
  // are done, so nothing is left applying an animation over style.transform.
  el.photoCard.addEventListener('animationend', e => {
    if (e.animationName === 'cardRise') el.photoCard.classList.remove('entering');
  });

  window.addEventListener('resize', () => { if (V.natW) fitStage(); });
  window.addEventListener('keydown', onKeyDown, true);
  window.addEventListener('keyup', onKeyUp, true);
  // drag 是 physics.js 私有的，这里只能"叫它取消"，读不到那个变量。
  window.addEventListener('blur', () => { if (hold) endHold(false); cancelDrag(); });
  el.photo.addEventListener('load', () => { if (V.natW !== el.photo.naturalWidth) fitStage(); });
}

function setList(open) {
  S.listOpen = open;
  el.listPane.classList.toggle('hidden', !open);
  el.listShow.classList.toggle('hidden', open);
  setTimeout(() => { if (V.natW) fitStage(); }, 30);
  setTimeout(() => { if (V.natW) fitStage(); }, 210);
}

/* ═════════════════════════ 装配（全项目唯一一处接线） ═════════════════════════

   到这里为止，每个模块都只 import 它下面那一层，没有一条边往上走 ——
   所以"谁先求值"是由 import 图唯一确定的，不再依赖文件在 index.html 里
   的先后、也不再依赖网络往返比解析慢。向上的那几条线（列表面向谁重绘、
   物理甩完通知谁、键盘敲了算谁）全部集中在这里注入，读依赖关系时
   只看各模块的 import 段就够了，不必在源码里搜调用点。

   这些函数都是函数声明，会被提升；本文件 import 进来的名字也已经求值完毕，
   所以模块体里直接引用它们是安全的 —— 这一段跑完，界面才有交互能力，
   而它跑在 home.js 的 boot() 之前（home.js import 本文件）。

   注入的名字和各自模块里的占位符同名（placeStamp / commitDecision / render …），
   所以被注入的函数体一个字都不用改，也就没有改名时漏改一处的机会。 */
configureView({ placeStamp });
configurePhysics({ commitDecision });
configureList({ render, loadQueue, renderTriage });
configureCard({ resetHoldVisual });
configureGrid({ loadQueue });
configureKeys({
  startHold, endHold, runAction, undo, closeModal, setList,
  holding: () => (hold ? hold.action : null),
});

/* app.js 往上还有一条线：库被关掉（/api/state 返回 409）时要回首页并刷新
   项目列表。那条线属于 home.js，而 home.js import 本文件 —— 所以只能
   注入，不能 import。装配在 home.js 里，因为它才是唯一入口。 */
let onLibraryClosed = () => {};
function configure(hooks) {
  if (hooks && hooks.onLibraryClosed) onLibraryClosed = hooks.onLibraryClosed;
}


export { enter, start, stop, attach, loadQueue, closeModal, setList, setLabels,
  configure, applyDefaults, ensureFaceModel
};

