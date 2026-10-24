/* 过片 Guopian — the home screen: the project list, the detail panel, and the
 * in-app folder browser. 全应用唯一的入口（index.html 里唯一的 <script>）。
 *
 * @requires ./core.js      G ( $ api toast esc fmtCount ) and Views
 * @requires ./app.js       把打开的库交给卡片流程；见下面"为什么 import app.js"
 * @requires web/index.html the home view's markup, including the [data-label]
 *                          placeholders that are filled from the API
 * @requires /api/home      recents, labels, version, face_available
 * @requires /api/alias     rename (an alias only -- never touches the folder)
 * @requires /api/reveal    "show in file manager"
 *
 * 这个文件是入口，所以它 import app.js —— 这一条 import 就是启动竞态的修法。
 *
 * 原来的顺序是"比赛"：index.html 依次加载 core.js → home.js → app.js，
 * home.js 末尾直接调 Home.boot()，它 await fetch('/api/home') 之后调
 * App.setLabels()。那时 app.js 往往刚解析到一半 —— 能跑只是因为网络往返
 * 比解析 73 KB 慢。网速快一点、文件大一点、机器慢一点，就会炸成
 * "App is not defined"，而且是偶发。
 *
 * 现在 home.js 静态 import app.js：ES module 的求值顺序由 import 图决定，
 * 被 import 的模块一定先求值完。boot() 里那一步不再需要任何时序假设。
 *
 * 反向那条线（app.js 需要"库被关掉时回首页"）不能 import 回来，会成环，
 * 所以用 configure() 注入，见文件末尾。 */

import { G, Views, setLibSlug } from './core.js';
import { S } from './state.js';
import { Settings } from './settings.js';
import { Tour } from './tour.js';
import { enter, start, stop, attach, setLabels, configure, applyDefaults } from './app.js';

/* ═══════════════════════════════ 首页 ═══════════════════════════════ */

const Home = (() => {
  const { $, api, toast, esc, fmtCount } = G;
  let booted = false;

  async function boot() {
    if (booted) return;
    booted = true;
    bind();
    Settings.bind();
    Tour.bind();
    try {
      const sc = await Settings.load();
      Settings.applyDensity(sc.density);
      applyDefaults(sc.settings);
    }
    catch (e) { /* the screen still works without it */ }
    await refresh();
  }

  async function refresh() {
    let data;
    try { data = await api('/api/home'); }
    catch (e) { toast('无法连接本地服务', 'err'); return; }

    $('#versionLabel').textContent = 'v' + (data.version || '');
    const fa = data.face_available || {};
    $('#faceHint').textContent = fa.ok
      ? '' : '人脸检测未启用：' + (fa.message || '模型缺失');

    // The static markup carries <b data-label="keep"></b> placeholders instead of
    // the words themselves. Fill them here, and hand the same object to the app
    // view so it never has its own copy.
    const labels = data.labels || {};
    const words = labels.decisions || {};
    document.querySelectorAll('[data-label]').forEach(el => {
      const w = words[el.dataset.label];
      if (w) el.textContent = w;
    });
    // 直接把词表交给 app.js。因为是静态 import，这里必然已经求值完毕 ——
    // 原来这一行是靠"网络比解析慢"才碰巧成立的。
    setLabels(labels);

    renderRecent(data.recent || []);

    // 地址栏说了算。
    //
    // 以前这里还有一条"服务端已经有打开的库就直接进去"，本意是"双击文件夹
    // 启动"那条路径，代价是：在项目里按了回首页、或者地址栏敲回 /，只要
    // 服务端还留着那个库（分析还在跑、或者只是没关），一刷新就又进去了 ——
    // 地址栏写着首页，屏幕上是项目，怎么刷新都回不去。
    //
    // 现在只有 /p/<slug> 会自动进项目。启动时如果带了文件夹参数，
    // run.py 会让窗口直接开在 /p/<slug>，那条路径照旧。
    const wantSlug = slugFromURL();
    if (wantSlug) {
      if (data.current && data.current.slug === wantSlug) {
        // 服务端开着的正是 URL 指的那个库：走统一入口（还在分析就先过整页
        // 进度），别重新开一遍。
        enter();
        return true;
      }
      const r = (data.recent || []).find(x => x.slug === wantSlug);
      if (r) { openLibrary(r.path); return true; }
      // The slug is not in the recent list any more -- forget it rather than
      // leaving a URL that will never resolve.
      history.replaceState({}, '', '/');
    }

    // First ever run: nothing has been opened yet. Offer the tour before the
    // home screen asks for a folder -- the first thing anyone meets should
    // explain what the app does, not demand they pick photos.
    if (!(data.recent || []).length && !data.current && !Tour.seen()) {
      Tour.open({ hasLibrary: !!data.current, onExit: () => refresh() });
      return true;
    }
    return false;
  }

  /* ═════════════════ 项目列表 + 详情 ═════════════════
     The home screen is a project manager, not a landing page. Left is what you
     have; right is what you can do with the one you picked. Selecting does NOT
     open -- that is a separate, deliberate action, so a stray click can never
     drop you into a 1428-photo library. */

  let PROJECTS = [];
  let SEL = null;            // the path currently shown on the right

  function statOf(r) {
    const total = r.total || 0;
    const done = r.decided || 0;
    const pct = total ? Math.round(done / total * 100) : 0;
    let text;
    if (!total) text = '空文件夹';
    else if (done) text = `${done} / ${total} 已决定`;
    else if (r.analyzed) text = `${r.analyzed} / ${total} 已分析`;
    else text = `${total} 张，还没分析`;
    return { total, done, pct, text };
  }

  const coverURL = r => `/api/cover?root=${encodeURIComponent(r.path)}`;
  const when = ts => {
    if (!ts) return '—';
    const d = Math.max(0, Date.now() / 1000 - ts);
    if (d < 90) return '刚刚';
    if (d < 3600) return Math.round(d / 60) + ' 分钟前';
    if (d < 86400) return Math.round(d / 3600) + ' 小时前';
    if (d < 86400 * 30) return Math.round(d / 86400) + ' 天前';
    return new Date(ts * 1000).toLocaleDateString();
  };

  /** The address-bar form of a project: /p/<slug>. */
  function projectURL(r) {
    return r && r.slug ? '/p/' + encodeURIComponent(r.slug) : '/';
  }

  /** Which project the current URL is asking for, if any. */
  function slugFromURL(match) {
    const m = /^\/p\/([^/?#]+)/.exec(location.pathname);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function pushURL(url) {
    if (location.pathname + location.search !== url) {
      history.pushState({}, '', url);
    }
  }

  function renderRecent(list) {
    PROJECTS = list || [];
    const wrap = $('#recentList');
    const none = PROJECTS.length === 0;

    $('#projCount').textContent = none ? '' : PROJECTS.length;
    $('#clearRecent').style.display = none ? 'none' : '';
    $('#projEmpty').classList.toggle('hidden', !none);

    // A project is shown by its own first photograph, not by its folder name.
    // The cover comes from /api/cover because no library is open on this screen
    // and /img/<id>/small needs a live one.
    wrap.innerHTML = PROJECTS.map(r => {
      const st = statOf(r);
      return `<button class="projCard" data-path="${esc(r.path)}">
        <span class="cardCover">${r.has_catalog
          ? `<img loading="lazy" alt="" src="${coverURL(r)}">` : ''}</span>
        <span class="cardMeta">
          <span class="cardName">${esc(r.name)}</span>
          <span class="cardStat">${esc(st.text)}</span>
          <span class="cardBar"><i style="width:${st.pct}%"></i></span>
        </span>
        <span class="cardActs">
          <span data-act="rename" title="重命名（只改过片里显示的名字）">✎</span>
          <span data-act="reveal" title="在文件夹中显示">↗</span>
          <span data-act="forget" title="从列表移除">✕</span>
        </span>
      </button>`;
    }).join('');

    wrap.querySelectorAll('.projCard').forEach(el => {
      const r = PROJECTS.find(x => x.path === el.dataset.path);
      el.onclick = (ev) => {
        const hit = ev.target.closest('[data-act]');
        // The whole card opens the library, so the small actions on the cover
        // have to stop the click rather than sit inside a nested button.
        if (hit) { ev.stopPropagation(); cardAction(hit.dataset.act, r, el); return; }
        openLibrary(r.path);
      };
    });
  }

  /** ✕ 其实是两件事，让用户自己选。
   *
   * 以前它只把项目从"最近打开"里拿掉，catalog（分析结果 + 缩略图）留在原处，
   * 所以重新打开同一个文件夹会"秒开、还带着上次的结果" —— 看起来就像删了
   * 没删干净。现在把两个意思分开：
   *   只从列表移除   数据留着，下次打开不用重扫
   *   连数据一起删   下次打开重新扫描（会先算一下占多大，写清楚代价）
   */
  async function forgetDialog(r) {
    const modal = $('#modal');
    const sheet = $('#sheet');
    const nm = esc(r.name || r.path);
    sheet.innerHTML = `
      <h2>移出项目列表</h2>
      <p><b>${nm}</b></p>
      <p class="muted small">分析结果和缩略图存在一边，不在你的照片文件夹里；
      这两件事的区别只在于要不要把它们也删掉。</p>
      <div class="fgChoice">
        <button class="btn ghost" id="fgKeep">
          <b>只从列表移除</b>
          <span class="muted small">保留分析数据 · 下次打开仍然秒开</span>
        </button>
        <button class="btn ghost" id="fgWipe">
          <b>删除项目和分析数据</b>
          <span class="muted small" id="fgSize">下次打开会重新扫描</span>
        </button>
      </div>
      <div class="rowBtns"><button class="btn ghost" id="fgCancel">取消</button></div>`;
    modal.classList.remove('hidden');

    // 顺手算一下会释放多少空间，别让人盲选
    api('/api/catalog/size?path=' + encodeURIComponent(r.path))
      .then(s => {
        const el = $('#fgSize');
        if (!el) return;
        el.textContent = s.bytes
          ? `释放 ${(s.bytes / 1048576).toFixed(1)} MB · 下次打开会重新扫描`
          : '下次打开会重新扫描';
      })
      .catch(() => {});

    const done = () => { modal.classList.add('hidden'); refresh(); };
    $('#fgCancel').onclick = () => modal.classList.add('hidden');
    $('#fgKeep').onclick = async () => {
      await api('/api/forget', { method: 'POST', body: JSON.stringify({ path: r.path }) });
      toast('已从列表移除，分析数据还在');
      done();
    };
    $('#fgWipe').onclick = async () => {
      const btn = $('#fgWipe');
      btn.disabled = true;
      try {
        const res = await api('/api/forget', {
          method: 'POST', body: JSON.stringify({ path: r.path, delete_data: true }) });
        const mb = res.freed ? (res.freed / 1048576).toFixed(1) + ' MB' : '';
        toast(`已删除项目${mb ? '，释放 ' + mb : ''}，下次打开会重新扫描`);
        done();
      } catch (e) {
        toast('删除失败', 'err');
        btn.disabled = false;
      }
    };
  }

  async function cardAction(act, r, card) {
    if (!r) return;

    if (act === 'forget') {
      forgetDialog(r);
      return;
    }

    if (act === 'reveal') {
      try {
        await api('/api/reveal', { method: 'POST', body: JSON.stringify({ path: r.path }) });
      } catch (e) { toast('无法打开资源管理器', 'err'); }
      return;
    }

    if (act === 'rename') {
      // In place: the name becomes the input, so nothing moves.
      const holder = card.querySelector('.cardName');
      const cur = r.alias || r.real_name || r.name;
      holder.innerHTML = `<input class="renameBox" value="${esc(cur)}"
                                 spellcheck="false" autocomplete="off">`;
      const inp = holder.querySelector('input');
      inp.focus();
      inp.select();
      let done = false;
      const commit = async () => {
        if (done) return;
        done = true;
        const v = inp.value.trim();
        await api('/api/alias', {
          method: 'POST',
          // Empty, or equal to the folder name, clears the alias rather than
          // storing a redundant copy of it.
          body: JSON.stringify({ path: r.path, alias: v === (r.real_name || '') ? '' : v }),
        });
        refresh();
      };
      inp.onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        if (e.key === 'Escape') { done = true; refresh(); }
        e.stopPropagation();
      };
      inp.onclick = (e) => e.stopPropagation();
      inp.onblur = commit;
    }
  }



  /** "2026-10-02 19:25 → 10-03 08:33", collapsing the shared date. */
  function dateSpan(a, b) {
    const f = (ts, withDate) => {
      const d = new Date(ts * 1000);
      const p = n => String(n).padStart(2, '0');
      const md = `${p(d.getMonth() + 1)}-${p(d.getDate())}`;
      const hm = `${p(d.getHours())}:${p(d.getMinutes())}`;
      return withDate ? `${d.getFullYear()}-${md} ${hm}` : `${md} ${hm}`;
    };
    const sameDay = new Date(a * 1000).toDateString() === new Date(b * 1000).toDateString();
    return `${f(a, true)} → ${f(b, !sameDay)}`;
  }




  async function openLibrary(path, readOnly) {
    toast('正在打开…');
    const body = { path };
    if (readOnly !== undefined) body.read_only = readOnly;
    try {
      const r = await api('/api/open', { method: 'POST', body: JSON.stringify(body) });
      if (!r.ok) { toast(r.error || '打开失败', 'err'); return; }
      // Tell imgUrl() which library it is before anything renders: photo ids
      // restart at 1 in every project, so a slug-less URL would be served from
      // the previous project's cache (see core.js).
      setLibSlug(r.slug);
      $('#toast').classList.add('hidden');
      // The address bar becomes the project, so a reload lands back here rather
      // than on the home screen. replaceState when the URL already names this
      // project -- opening from its own URL should not stack a second entry.
      const want = projectURL(PROJECTS.find(x => x.path === path));
      if (location.pathname === want) history.replaceState({}, '', want);
      else pushURL(want);
      // 统一入口：新文件夹（还没分析过）会先过整页的进度 + 分类图表，
      // 分析完自动进入过图；已经分析过的库直接进。
      await enter();
    } catch (e) {
      toast((e.body && e.body.error) || e.message || '打开失败', 'err');
    }
  }

  /* ───────────────────── 文件夹浏览器 ─────────────────────

     列表和计数是分开的两件事。
     列出目录只 scandir 一次（几毫秒），而"这个文件夹里有几张照片"要递归走
     整棵树 —— 以前两件事在同一个请求里做，点一下 D 盘就要把 D 盘连同每个
     子目录都数一遍（SteamLibrary 一个就 154 ms，冷缓存要几秒），看着就像在
     扫描。现在列表立刻出来，数字按行懒问、边到边填，填完再排一次序。 */

  const B = { cur: null, roots: [], picked: null, home: '', seq: 0,
              counts: new Map(), curPhotos: null };

  async function openBrowser(startPath) {
    $('#browser').classList.remove('hidden');
    if (!B.roots.length) {
      try {
        const r = await api('/api/fs/roots');
        B.roots = r.roots || [];
        B.home = r.home || '';
      } catch (e) { B.roots = []; }
      renderRoots();
    }
    await navigate(startPath || B.home);
  }

  async function countPhotos(path) {
    if (B.counts.has(path)) return B.counts.get(path);
    try {
      const r = await api('/api/fs/count?path=' + encodeURIComponent(path));
      const n = r.photos | 0;
      B.counts.set(path, n);
      return n;
    } catch (e) { return null; }
  }

  /** 把这一屏的数字填上；并发 4，切目录就作废（seq 变了直接退出）。 */
  async function fillCounts(d, seq) {
    const targets = [{ path: d.path, set: n => { B.curPhotos = n; syncOpenButton(); } }]
      .concat(d.dirs.map(x => ({ path: x.path, set: n => { x.photos = n; } })));
    let at = 0;
    const worker = async () => {
      while (at < targets.length) {
        const t = targets[at++];
        const n = await countPhotos(t.path);
        if (seq !== B.seq) return;
        if (n != null) t.set(n);
        renderDirs(d);
        if (t.path === d.path) syncOpenButton();
      }
    };
    await Promise.all(Array.from({ length: Math.min(4, targets.length) }, worker));
    if (seq !== B.seq) return;
    // 到齐了按"有照片的排前面"重排一次。只排这一下：边到边排会让行来回跳。
    d.dirs.sort((a, b) => (((b.photos || 0) > 0) - ((a.photos || 0) > 0))
      || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    renderDirs(d);
    syncOpenButton();
  }

  function syncOpenButton() {
    const btn = $('#browserOpen');
    if (btn) btn.textContent = B.curPhotos ? `打开这个文件夹（${B.curPhotos} 张）`
                                          : '打开这个文件夹';
  }

  async function navigate(path) {
    let d;
    try { d = await api('/api/fs/list' + (path ? '?path=' + encodeURIComponent(path) : '')); }
    catch (e) { toast('无法读取这个文件夹', 'err'); return; }
    if (d.error) { toast(d.error, 'err'); }

    const seq = ++B.seq;
    B.cur = d.path;
    B.picked = d.path;
    B.curPhotos = B.counts.has(d.path) ? B.counts.get(d.path) : null;
    renderCrumbs(d.path);
    renderDirs(d);                       // 立刻画：名字已经在手里了
    $('#pickedPath').textContent = d.path;
    $('#pickedPath').title = d.path;
    syncOpenButton();
    fillCounts(d, seq);                  // 数字慢慢补
    return d;
  }

  function closeBrowser() {
    $('#browser').classList.add('hidden');
  }

  function renderRoots() {
    $('#roots').innerHTML = B.roots.map((r, i) =>
      `<button class="rootChip" data-i="${i}">
         <span>${esc(r.name)}</span>${r.label ? `<span class="lbl">${esc(r.label)}</span>` : ''}
       </button>`).join('');
    $('#roots').querySelectorAll('.rootChip').forEach(el => {
      el.onclick = () => navigate(B.roots[+el.dataset.i].path);
    });
  }

  function renderCrumbs(path) {
    const sep = path.includes('\\') ? '\\' : '/';
    const parts = path.split(/[\\/]+/).filter(Boolean);
    const out = [];
    let acc = path.startsWith('/') ? '' : '';
    parts.forEach((p, i) => {
      acc = i === 0 ? (sep === '\\' ? p + sep : '/' + p) : acc.replace(/[\\/]$/, '') + sep + p;
      const isLast = i === parts.length - 1;
      out.push(`<span class="crumbSep">${sep === '\\' ? '›' : '/'}</span>`);
      out.push(`<button class="crumb${isLast ? ' last' : ''}" data-p="${esc(acc)}">${esc(p)}</button>`);
    });
    $('#crumbs').innerHTML = out.join('');
    $('#crumbs').querySelectorAll('.crumb').forEach(el => {
      el.onclick = () => navigate(el.dataset.p);
    });
  }

  function renderDirs(d) {
    // photos 还没问到就是 null：行照样画，数字位显示"…"，问到再填。
    // 不要因为它未知就藏起来 —— 那会让列表先"少一半"再"变多"。
    const unknown = d.photos == null;
    const rows = [];
    if (d.parent) {
      rows.push(`<button class="dirRow up" data-p="${esc(d.parent)}">
        <span class="ico"><svg viewBox="0 0 24 24" width="17" height="17" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 19V5M5 12l7-7 7 7"/></svg></span>
        <span class="nm">上一级</span></button>`);
    }
    for (const sub of d.dirs) {
      const known = sub.photos != null;
      rows.push(`<button class="dirRow ${known && sub.photos ? 'has' : ''}" data-p="${esc(sub.path)}">
        <span class="ico"><svg viewBox="0 0 24 24" width="17" height="17" fill="none"
          stroke="currentColor" stroke-width="1.8"><path d="M3 7.5A2 2 0 0 1 5 5.5h3.6a2 2 0 0 1 1.5.7l1 1.3H19a2 2 0 0 1 2 2v7A2 2 0 0 1 19 18.5H5a2 2 0 0 1-2-2z"/></svg></span>
        <span class="nm">${esc(sub.name)}</span>
        <span class="cnt">${known ? (sub.photos ? sub.photos + ' 张' : '') : '…'}</span></button>`);
    }
    $('#dirList').innerHTML = rows.length ? rows.join('')
      : '<div class="dirEmpty">这个文件夹是空的，也没有子文件夹</div>';
    $('#dirList').querySelectorAll('.dirRow').forEach(el => {
      el.onclick = () => navigate(el.dataset.p);
    });
  }

  /* ───────────────────── 绑定 ───────────────────── */

  function bind() {
    $('#btnOpen').onclick = () => openBrowser();
    $('#browserClose').onclick = closeBrowser;
    $('#browserCancel').onclick = closeBrowser;
    $('#browserOpen').onclick = () => {
      if (!B.picked) return;
      openLibrary(B.picked);
      closeBrowser();
    };
    $('#browser').onclick = (e) => { if (e.target.id === 'browser') closeBrowser(); };

    $('#homeHelp').onclick = () => $('#help').classList.remove('hidden');
    $('#helpClose').onclick = () => $('#help').classList.add('hidden');
    $('#openSettings').onclick = () => Settings.open();
    // The same screen, reachable without leaving the project.
    const bs = $('#btnSettings');
    if (bs) bs.onclick = () => Settings.open();
    // #settings opens the panel directly. It makes the screen linkable, and it
    // is the only way a headless browser can reach it for a screenshot -- the
    // alternative was patching this file every time someone wanted a picture.
    if (location.hash === '#settings') Settings.open();
    // #tour opens the walkthrough directly. Same reason as #settings: it
    // makes the screen linkable, and a headless browser can otherwise
    // never reach it.
    if (/^#tour(-\d+)?$/.test(location.hash)) {
      // 等状态到齐再开，否则会把「已打开的项目」误判成没开，
      // 只讲首页那四步。
      const go = () => Tour.open({ hasLibrary: !!(S.state && S.state.root) });
      setTimeout(go, 1200);
    }

    $('#clearRecent').onclick = async () => {
      const r = await api('/api/home');
      for (const item of (r.recent || [])) {
        await api('/api/forget', { method: 'POST', body: JSON.stringify({ path: item.path }) });
      }
      refresh();
    };

    $('#backHome').onclick = goHome;

    bindDrop();
  }

  async function goHome() {
    try { await api('/api/close', { method: 'POST' }); } catch (e) { /* ignore */ }
    stop();
    pushURL('/');
    Views.show('homeView');
    await refresh();
  }

  /* drag a folder onto the window: Chromium gives us the path in newer builds */
  function bindDrop() {
    const veil = $('#dropVeil');
    let depth = 0;
    window.addEventListener('dragenter', (e) => {
      e.preventDefault();
      depth++;
      veil.classList.remove('hidden');
    });
    window.addEventListener('dragover', (e) => e.preventDefault());
    window.addEventListener('dragleave', () => {
      depth = Math.max(0, depth - 1);
      if (!depth) veil.classList.add('hidden');
    });
    window.addEventListener('drop', async (e) => {
      e.preventDefault();
      depth = 0;
      veil.classList.add('hidden');
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      const path = f && (f.path || (window.guopianPathFor && window.guopianPathFor(f)));
      if (path) {
        openLibrary(path);
      } else {
        toast('浏览器没有把文件夹路径给我们，请用「打开照片文件夹」按钮', 'warn');
      }
    });
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (!$('#browser').classList.contains('hidden')) closeBrowser();
      }
    });
  }

  return { boot, refresh, openBrowser, openLibrary, goHome, closeBrowser };
})();

export { Home };

/* app.js 需要一条向上的线：/api/state 返回 409（库被关掉）时要回首页并刷新
   项目列表。app.js 不能 import 本文件 —— 本文件 import 了它，反向再 import
   就是循环依赖。所以那条线用注入：把 refresh 交出去，app.js 在需要时调用。
   configure 必须在 boot() 之前，因为 boot() 可能立刻就打开一个库。 */
configure({ onLibraryClosed: Home.refresh });

/* 启动。写在模块体最后一行：此刻 import 图已经保证 core.js 和 app.js 都
   求值完毕，所以 boot() 里 await 回来的那一步调用 setLabels() 是安全的。 */
Home.boot();

