/* 过片 Guopian — the layer every other module stands on.
 *
 * @requires web/index.html   the views and the #toast element
 * @requires /api/*           only through G.api
 *
 * 无依赖的叶子模块：只有 G（$ $$ api toast esc sleep fmtCount）和 Views。
 * 原来它是普通 <script>，靠"index.html 里排在第一个"来保证别人能用；改成
 * module 之后，顺序由 import 图保证 —— 谁 import 它，它就先求值完。
 *
 * 它是这次拆分里唯一不需要改内容的模块：原来挂 window.G / window.Views，
 * 现在改成 export。挂 window 的写法看着"谁都能用"，实际是把依赖关系藏进
 * 了全局命名空间，读一个文件根本看不出它依赖谁。
 *
 * 浏览器原生 ES module，无打包器、无构建步骤。 */

const G = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  async function api(path, opts) {
    const r = await fetch(path, Object.assign(
      { headers: { 'Content-Type': 'application/json' } }, opts || {}));
    const ct = r.headers.get('content-type') || '';
    const body = ct.includes('json') ? await r.json() : await r.text();
    if (!r.ok) throw Object.assign(new Error((body && body.message) || ('HTTP ' + r.status)),
                                  { body, status: r.status });
    return body;
  }

  let toastTimer = null;
  function toast(msg, kind) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = msg;
    t.className = 'toast ' + (kind || '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add('hidden'), 2800);
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function fmtCount(n) {
    return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
  }

  return { $, $$, api, toast, esc, sleep, fmtCount };
})();

/* 除了 G 这个命名空间，还把这七个帮手单独导出。

   理由是可读性，而且是有代价之后才看清楚的：如果只导出 G，每个模块就得写
   `import { G } from './core.js'` 再在函数体里 `const { esc } = G`，
   依赖关系被拆成两处；写 `import { esc } from './core.js'` 时，
   文件头那一行就完整说明了"这个模块用到 core 的哪一样"。 */
const { $, $$, api, toast, esc, sleep, fmtCount } = G;

/* ═══════════════════════════════ 视图切换 ═══════════════════════════════ */

const Views = {
  show(name) {
    ['homeView', 'appView', 'gridView'].forEach(id => {
      G.$('#' + id).classList.toggle('hidden', id !== name);
    });
  },
};

export { G, Views, $, $$, api, toast, esc, sleep, fmtCount };
