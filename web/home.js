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

import { G, Views } from './core.js';
import { Settings } from './settings.js';
import { Tour } from './tour.js';
import { start, stop, attach, setLabels, configure, applyDefaults } from './app.js';

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

    // A project URL wins over everything: reloading /p/<slug> must land you
    // back in that project, not on the home screen.
    const wantSlug = slugFromURL();
    if (wantSlug && !(data.current && data.current.root)) {
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
      Tour.open({ withDemo: true, onExit: () => refresh() });
      return true;
    }

    // If a library is already open (e.g. the user passed a folder on the
    // command line, or reloaded the window), go straight to it.
    if (data.current && data.current.root) {
      Views.show('appView');
      attach(data.current);
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

  async function cardAction(act, r, card) {
    if (!r) return;

    if (act === 'forget') {
      await api('/api/forget', { method: 'POST', body: JSON.stringify({ path: r.path }) });
      refresh();
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
      $('#toast').classList.add('hidden');
      // The address bar becomes the project, so a reload lands back here rather
      // than on the home screen. replaceState when the URL already names this
      // project -- opening from its own URL should not stack a second entry.
      const want = projectURL(PROJECTS.find(x => x.path === path));
      if (location.pathname === want) history.replaceState({}, '', want);
      else pushURL(want);
      Views.show('appView');
      start();
    } catch (e) {
      toast((e.body && e.body.error) || e.message || '打开失败', 'err');
    }
  }

  /* ───────────────────── 文件夹浏览器 ───────────────────── */

  const B = { cur: null, roots: [], picked: null, home: '' };

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

  async function navigate(path) {
    let d;
    try { d = await api('/api/fs/list' + (path ? '?path=' + encodeURIComponent(path) : '')); }
    catch (e) { toast('无法读取这个文件夹', 'err'); return; }
    if (d.error) { toast(d.error, 'err'); }

    B.cur = d.path;
    B.picked = d.path;
    renderCrumbs(d.path);
    renderDirs(d);
    $('#pickedPath').textContent = d.path;
    $('#pickedPath').title = d.path;
    const canOpen = d.photos > 0 || d.dirs.some(x => x.photos > 0);
    const btn = $('#browserOpen');
    btn.disabled = false;
    btn.textContent = d.photos > 0
      ? `打开这个文件夹（${d.photos} 张）`
      : '打开这个文件夹';
    return d;
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
    const rows = [];
    if (d.parent) {
      rows.push(`<button class="dirRow up" data-p="${esc(d.parent)}">
        <span class="ico"><svg viewBox="0 0 24 24" width="17" height="17" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 19V5M5 12l7-7 7 7"/></svg></span>
        <span class="nm">上一级</span></button>`);
    }
    if (d.photos > 0) {
      rows.push(`<button class="dirRow has" data-p="${esc(d.path)}">
        <span class="ico"><svg viewBox="0 0 24 24" width="17" height="17" fill="none"
          stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="8.7" cy="9.6" r="1.6"/>
          <path d="M4 16.5l4.6-4.3 3.5 3.2 3-2.7 4.9 4.3"/></svg></span>
        <span class="nm">就用这个文件夹</span>
        <span class="cnt">${d.photos} 张照片</span></button>`);
    }
    for (const sub of d.dirs) {
      rows.push(`<button class="dirRow ${sub.photos ? 'has' : ''}" data-p="${esc(sub.path)}">
        <span class="ico"><svg viewBox="0 0 24 24" width="17" height="17" fill="none"
          stroke="currentColor" stroke-width="1.8"><path d="M3 7.5A2 2 0 0 1 5 5.5h3.6a2 2 0 0 1 1.5.7l1 1.3H19a2 2 0 0 1 2 2v7A2 2 0 0 1 19 18.5H5a2 2 0 0 1-2-2z"/></svg></span>
        <span class="nm">${esc(sub.name)}</span>
        <span class="cnt">${sub.photos ? sub.photos + ' 张' : ''}</span></button>`);
    }
    $('#dirList').innerHTML = rows.length ? rows.join('')
      : '<div class="dirEmpty">这个文件夹是空的，也没有子文件夹</div>';
    $('#dirList').querySelectorAll('.dirRow').forEach(el => {
      el.onclick = () => {
        if (el.classList.contains('up') || !el.classList.contains('has')) {
          navigate(el.dataset.p);
        } else if (el.querySelector('.nm').textContent === '就用这个文件夹') {
          openLibrary(el.dataset.p, $('#roToggle').checked);
          closeBrowser();
        } else {
          navigate(el.dataset.p);
        }
      };
    });
  }

  /* ───────────────────── 绑定 ───────────────────── */

  function bind() {
    $('#btnOpen').onclick = () => openBrowser();
    $('#browserClose').onclick = closeBrowser;
    $('#browserCancel').onclick = closeBrowser;
    $('#browserOpen').onclick = () => {
      if (!B.picked) return;
      openLibrary(B.picked, $('#roToggle').checked);
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
    if (/^#tour(-\d+)?$/.test(location.hash)) Tour.open({ withDemo: true });

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
        openLibrary(path, $('#roToggle') ? $('#roToggle').checked : false);
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
