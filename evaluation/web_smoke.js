/* Runs the real Guopian frontend against a hand-rolled DOM stub.
 *
 * The sandbox forbids Chromium (it needs named pipes for mojo IPC), so we
 * cannot screenshot. What we CAN do is execute the frontend modules with
 * realistic API data and catch the class of bug that blanks the page: a typo, a
 * missing function, reading a property of undefined. That is worth more than a
 * pixel-perfect check for a change this size.
 *
 *   node evaluation/web_smoke.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEB = path.join(__dirname, '..', 'web');
const errors = [];
const log = [];

const NUMERIC = new Set([
  'naturalWidth', 'naturalHeight', 'clientWidth', 'clientHeight',
  'offsetWidth', 'offsetHeight', 'scrollTop', 'scrollHeight',
  'scrollLeft', 'scrollWidth', 'innerWidth', 'innerHeight',
  'deltaY', 'deltaX', 'clientX', 'clientY', 'pageX', 'pageY',
  'buttons', 'keyCode', 'which', 'width', 'height', 'top', 'left',
]);

function stub(name) {
  const fn = function () { return stub(name + '()'); };
  return new Proxy(fn, {
    get(t, k) {
      if (k === Symbol.iterator) return function* () {};
      if (k === Symbol.toPrimitive) return () => 0;
      if (k === 'then') return undefined;
      if (k === 'valueOf') return () => 0;
      if (typeof k === 'string' && NUMERIC.has(k)) return 0;
      // Listeners are recorded and dispatchEvent actually calls them. Without
      // this every addEventListener was a no-op, so no interaction path could be
      // exercised at all -- which is how a mousemove handler that threw on every
      // single move survived two rounds of green tests.
      if (k === 'addEventListener') {
        return (type, fn2) => {
          (t.__on || (t.__on = {}))[type] = (t.__on[type] || []).concat(fn2);
        };
      }
      if (k === 'removeEventListener') return () => {};
      if (k === 'dispatchEvent') {
        return (ev) => {
          const list = (t.__on || {})[ev.type] || [];
          for (const h of list) h(ev);
          return true;
        };
      }
      if (k in t) return t[k];
      switch (k) {
        case 'length': return 0;
        case 'nodeType': return 1;
        case 'tagName': return 'DIV';
        case 'dataset': return new Proxy({}, { get: () => '', set: () => true });
        // A CSSStyleDeclaration is not just a bag of properties. The app drives
        // its animations through custom properties (--pl/--pr/--pm for the drag
        // gesture, --sx/--sr for the hand-off into the exit keyframes), and
        // setProperty() is the only way to write those from JS. Memoised on the
        // target, because a fresh object per access would silently drop every
        // write and make the values unreadable from a test.
        case 'style': {
          if (!t.__style) {
            const o = {
              setProperty(k, v) { this[k] = v; },
              getPropertyValue(k) { return this[k] || ''; },
              removeProperty(k) { delete this[k]; },
            };
            t.__style = new Proxy(o, {
              get: (x, k) => (k in x ? x[k] : ''),
              set: (x, k, v) => { x[k] = v; return true; },
            });
          }
          return t.__style;
        }
        case 'classList': {
          const cls = (t.__cls || (t.__cls = new Set()));
          return {
            add: (...c) => c.forEach(x => cls.add(x)),
            remove: (...c) => c.forEach(x => cls.delete(x)),
            toggle: (c, on) => (on === undefined ? (cls.has(c) ? cls.delete(c) : cls.add(c))
                                                 : (on ? cls.add(c) : cls.delete(c))),
            contains: (c) => cls.has(c),
          };
        }
        case 'options': return [];
        case 'files': return [];
        case 'value': return '';
        case 'textContent': return '';
        case 'innerHTML': return '';
        default: return stub(name + '.' + String(k));
      }
    },
    set(t, k, v) { t[k] = v; return true; },
    apply() { return stub(name + '()'); },
    construct() { return stub(name); },
  });
}

const elCache = new Map();
function element(sel) {
  if (!elCache.has(sel)) elCache.set(sel, stub('el' + sel));
  return elCache.get(sel);
}

// Advanced by the drag tests to simulate the passage of time between moves.
let clock = 100000;
const advance = (ms) => { clock += ms; };

// A manual animation-frame pump. The drag is a physics integrator driven by
// requestAnimationFrame, so with no rAF in the sandbox the body never moves and
// every drag assertion would read zero. Tests step it explicitly instead of
// letting it run wild.
const rafQueue = new Map();
let rafId = 0;
function pump(frames = 1, stepMs = 16.7) {
  for (let i = 0; i < frames; i++) {
    clock += stepMs;
    const due = [...rafQueue.entries()];
    rafQueue.clear();
    for (const [, cb] of due) cb(clock);
  }
}

/* ---- realistic API fixtures (shapes copied from the running server) ---- */
const PHOTOS = [];
for (let i = 1; i <= 40; i++) {
  PHOTOS.push({
    id: i,
    name: 'DSC0' + (9850 + i) + '.JPG',
    rel_path: 'DSC0' + (9850 + i) + '.JPG',
    taken_at: '2026:10:02 19:25:0' + (i % 10),
    camera: 'SONY ILCE-7C',
    width: 6000, height: 4000,
    pct_high: i % 7 === 0 ? 27.7 : 0.4,
    pct_low: 1.2, lap_var_mp: 5000 + i * 100, noise: 1.05,
    face_count: i % 5 === 0 ? 1 : 0,
    group_id: Math.ceil(i / 4), group_size: 4, group_rank: (i % 4) + 1,
    suggest: i % 6 === 0 ? 'reject' : (i % 5 === 0 ? 'maybe' : 'keep'),
    suggest_reason: '高光溢出',
    decision: i < 8 ? ['keep', 'reject', 'maybe', 'skip'][i % 4] : null,
    issues: i % 3 === 0
      ? [{ kind: 'eye_closed', severity: 'fatal', confidence: 0.91, face_idx: 0,
           label_zh: '眼睛闭合', detail: '右眼', evidence: {} },
         { kind: 'overexposed', severity: 'high', confidence: 0.64, face_idx: null,
           label_zh: '高光溢出', detail: '12%', evidence: {} }]
      : [],
  });
}

const HOME = {
  version: '0.1.0', generation: 1, platform: 'windows',
  face_available: { ok: true, message: null },
  recent: [
    { path: 'D:\\image cache\\川西\\100MSDCF', name: '100MSDCF', at: 1,
      analyzed: 93, total: 93, decided: 4, has_catalog: true },
    { path: 'D:\\image cache\\川西\\101MSDCF', name: '101MSDCF', at: 2,
      analyzed: 0, total: 1428, decided: 0, has_catalog: false },
  ],
  current: null,
};

const STATE = {
  root: 'D:\\image cache\\川西\\100MSDCF', work_dir: 'C:\\cat',
  read_only: true, generation: 1,
  progress: { phase: 'done', total: 93, done: 93, rate: 17, elapsed: 5.4, running: false },
  counts: { total: 93, analyzed: 93,
            decisions: { keep: 2, reject: 1, maybe: 1, skip: 1, undecided: 88 } },
  face_available: { ok: true }, calibration: null,
  issue_summary: [
    { kind: 'eye_maybe_closed', severity: 'medium', label_zh: '眼睛可能闭着', n: 4 },
    { kind: 'overexposed', severity: 'fatal', label_zh: '高光溢出', n: 9 },
  ],
};

const PHOTO_DETAIL = Object.assign({}, PHOTOS[0], {
  faces: [{ idx: 0, x: .3, y: .3, w: .2, h: .26, yaw: 6.2, blink_l: .1, blink_r: .62,
            gaze_away: .3, smile: .4, jaw_open: .1, brow_down: .05, squint: .1,
            face_sharp: 1200, face_sharp_ratio: .42, face_pct_high: 1,
            face_pct_low: 2, gates: {}, landmarks: { r_eye: [.35, .4, .04, .02],
            l_eye: [.45, .4, .04, .02], nose: [.4, .45] } }],
});

function jsonResponse(data) {
  return Promise.resolve({
    ok: true, status: 200,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  });
}

let fetchCalls = [];
function fakeFetch(url, opts) {
  fetchCalls.push(String(url).split('?')[0]);
  const u = String(url);
  if (u.includes('/api/home')) return jsonResponse(HOME);
  if (u.includes('/api/state')) return jsonResponse(STATE);
  if (u.includes('/api/queue')) {
    return jsonResponse({ filter: 'pending', sort: 'time', total: PHOTOS.length, items: PHOTOS });
  }
  if (u.includes('/api/photo/')) return jsonResponse(PHOTO_DETAIL);
  if (u.includes('/api/fs/roots')) return jsonResponse({ roots: [{ name: 'D:', label: '', path: 'D:\\' }], home: 'C:\\Users' });
  if (u.includes('/api/fs/list')) {
    return jsonResponse({ path: 'D:\\image cache\\川西', name: '川西', parent: 'D:\\image cache',
                          photos: 0, error: null,
                          dirs: [{ name: '100MSDCF', path: 'D:\\image cache\\川西\\100MSDCF', photos: 93 }] });
  }
  return jsonResponse({ ok: true });
}

/* ---- the sandbox ---- */
const win = {};
const store = {};
const sandbox = {
  console,
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
  Promise, Math, JSON, Date, Object, Array, String, Number, Boolean, RegExp,
  Intl, Error, TypeError, Symbol, Map, Set, parseFloat, parseInt, isNaN,
  requestAnimationFrame: (fn) => setTimeout(fn, 0),
  addEventListener() {}, removeEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  alert() {}, confirm: () => false,
  fetch: fakeFetch,
  Image: function () { return stub('Image'); },
  IntersectionObserver: function () { this.observe = () => {}; this.disconnect = () => {}; },
  localStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  },
  // A controllable clock. The flick logic reads performance.now() to work out
  // pointer velocity, and with the real clock every synthetic mousemove lands in
  // the same millisecond -- so the velocity would be infinite and every test
  // drag would register as a throw.
  performance: { now: () => clock },
  requestAnimationFrame: (cb) => { rafQueue.set(++rafId, cb); return rafId; },
  cancelAnimationFrame: (id) => { rafQueue.delete(id); },
  navigator: { userAgent: 'node' },
  location: { href: 'http://127.0.0.1:8765/', search: '' },
  // prefetchAhead() builds Image objects to warm the cache for the next photos.
  // Without this the sandbox had no Image at all, so that call would have thrown
  // the moment a queue long enough to have a "next photo" was rendered.
  Image: function () {
    this.decode = () => Promise.resolve();
    this.addEventListener = () => {};
  },
  // Minimal event classes. Without these no interaction path could be driven at
  // all, which is how a drag handler that threw on every mousemove stayed green.
  MouseEvent: function (type, init) {
    Object.assign(this, { type, bubbles: false, cancelable: false,
                          button: 0, buttons: 0, clientX: 0, clientY: 0 }, init || {});
    this.preventDefault = () => {};
    this.stopPropagation = () => {};
  },
  KeyboardEvent: function (type, init) {
    Object.assign(this, { type, bubbles: false, cancelable: false, key: '' }, init || {});
    this.preventDefault = () => {};
    this.stopPropagation = () => {};
  },
  Event: function (type, init) {
    Object.assign(this, { type, bubbles: false, cancelable: false }, init || {});
    this.preventDefault = () => {};
    this.stopPropagation = () => {};
  },
  document: {
    querySelector: element,
    querySelectorAll: () => [],
    getElementById: (id) => element('#' + id),
    createElement: () => stub('newEl'),
    addEventListener() {},
    documentElement: stub('html'),
    body: stub('body'),
    fullscreenElement: null,
    exitFullscreen: () => Promise.resolve(),
  },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;

// The app binds mousemove / mouseup / keydown on `window`, not on an element, so
// the sandbox itself has to be a valid event target.
const winListeners = {};
sandbox.addEventListener = (type, fn) => {
  (winListeners[type] || (winListeners[type] = [])).push(fn);
};
sandbox.removeEventListener = () => {};
sandbox.dispatchEvent = (ev) => {
  for (const h of winListeners[ev.type] || []) h(ev);
  return true;
};

const ctx = vm.createContext(sandbox);

/* ───────────────────────── 模块加载器 ─────────────────────────
 *
 * 前端现在是浏览器原生 ES module：一个 <script type="module" src="/home.js">，
 * 其余靠 import 图。node 的 vm 里跑不了真的 ESM（真 ESM 要 URL 加载器、
 * 要真实的 globalThis），所以这里自己做一个最小加载器：
 *
 *   1. 读文件，把 `import {...} from './x.js'` 和 `export {...}` 摘出来
 *   2. 先递归加载它 import 的那些模块（顺序因此由 import 图决定，不是靠
 *      一个手写的列表 —— 加一行 import 不需要改这里）
 *   3. 把模块体包进一个函数作用域，import 的名字用解构从依赖的导出对象里取，
 *      末尾 return 自己的导出对象
 *
 * 为什么不是"把所有模块拍平到同一个 scope"（最省事的那种做法）：拍平会让
 * 不同模块的同名顶层绑定互相撞车。这套代码里 configure 就有七个模块各自
 * 声明了一份，拍平直接 SyntaxError —— 也就是说拍平会逼着源码改名去迁就测试。
 * 每个模块一个作用域则和浏览器里的语义一致得多。
 *
 * 这个加载器做得到、值得说明的：它自己解析 import 路径和名字，所以**路径写错、
 * 或者 import 了一个对方没导出的名字，在这里就会失败**（比"拍平"更强）。
 *
 * 它测不到的（这些交给 hygiene.py 的静态检查，以及浏览器）：
 *   - 真 ESM 的活绑定语义。导出的对象是求值那一刻的快照；如果某个模块导出
 *     了一个之后会被重新赋值的 let，这里看不到新值。本项目的模块只导出对象
 *     和函数，没有这种写法，所以等价 —— 但这是"恰好"，不是这个检查保证的。
 *   - 循环依赖的求值顺序。真 ESM 允许环并有一套规则；这里递归加载遇到环会
 *     直接报错。好在 hygiene.py 第 4 组也查环，两边一致。
 *   - index.html。这里不读它，所以入口路径写错、type="module" 漏写、
 *     或者 MIME 不对，都只能靠 hygiene.py 和真实浏览器。
 */
const RE_IMPORT = /import\s+(?:([\w$]+)\s*,\s*)?(?:\{([^}]*)\}|\*\s+as\s+([\w$]+))\s*from\s*['"]([^'"]+)['"];?/g;
/* Two export forms, because JavaScript has two and this only knew one.
 *
 * Every module happened to use `export { a, b };`, so the brace-only regex
 * looked correct -- until one file was written as `export const X = ...`, at
 * which point this reported "does not export X" while the browser would have
 * loaded it without complaint. A parser that recognises fewer forms than the
 * language has fails in exactly the same shape as a passing check. */
const RE_EXPORT = /export\s*\{([^}]*)\};?/g;
const RE_EXPORT_DECL = new RegExp(
  'export\\s+(?:async\\s+)?(?:const|let|var|function|class)\\s+([A-Za-z_$][\\w$]*)', 'g');

/* 注释必须先清掉，而且要在清掉之后的文本上找 import。
 *
 * 这条不是洁癖：core.js 的文件头注释里就写着一句 `import { esc } from
 * './core.js'`（在解释为什么要把帮手单独导出）。注释不清，正则就会把它当成
 * 一条真的 import，于是 core.js "import 自己"、加载器报环、整个测试崩掉。
 *
 * 注意这里只空掉**注释**，字符串、模板字符串、正则字面量一律原样抄回去 ——
 * 这段文本是要拿去执行的，把正则内容也抹掉会直接变成语法错误
 * （`.replace(          , ...)`）。扫描器认得这四种东西，只是为了不把
 * 字符串里的 `//` 当成注释。
 *
 * 空掉的字符换成空格、保留换行，报错时的行号就还是原来那个。
 *
 * 已知的局限：模板字符串里 ${...} 内部如果写注释，这里认不出来（会被当成
 * 模板内容原样保留）。这套代码的模板里没有表达式内注释，不值得为此写个
 * 完整的词法器。 */
function blankComments(src) {
  let out = '', i = 0, prev = '';
  const n = src.length;
  // 标准判据：前一个有效字符不可能是标识符/数字/`)]}` 的一部分时，斜杠是正则。
  const isRegexStart = () => !(/[A-Za-z0-9_$]/.test(prev) || ')]}'.includes(prev));
  while (i < n) {
    const c = src[i];
    if (c === '/' && src[i + 1] === '/') {
      while (i < n && src[i] !== '\n') { out += ' '; i++; }
    } else if (c === '/' && src[i + 1] === '*') {
      out += '  '; i += 2;
      while (i < n && !(src[i] === '*' && src[i + 1] === '/')) {
        out += (src[i] === '\n' ? '\n' : ' '); i++;
      }
      if (i < n) { out += '  '; i += 2; }
    } else if (c === '"' || c === "'") {
      const start = i; i++;
      while (i < n && src[i] !== c) i += (src[i] === '\\' ? 2 : 1);
      i = Math.min(n, i + 1);
      out += src.slice(start, i);
    } else if (c === '`') {
      const start = i; i++;
      while (i < n && src[i] !== '`') {
        if (src[i] === '\\') { i += 2; continue; }
        if (src[i] === '$' && src[i + 1] === '{') {
          let depth = 1; i += 2;
          while (i < n && depth) {
            if (src[i] === '{') depth++;
            else if (src[i] === '}') depth--;
            else if (src[i] === "'" || src[i] === '"' || src[i] === '`') {
              const q = src[i]; i++;
              while (i < n && src[i] !== q) i += (src[i] === '\\' ? 2 : 1);
            }
            i++;
          }
          continue;
        }
        i++;
      }
      i = Math.min(n, i + 1);
      out += src.slice(start, i);
    } else if (c === '/' && isRegexStart()) {
      const start = i; i++;
      let inClass = false;
      while (i < n) {
        if (src[i] === '\\') { i += 2; continue; }
        if (src[i] === '[') inClass = true;
        else if (src[i] === ']') inClass = false;
        else if (src[i] === '/' && !inClass) { i++; break; }
        else if (src[i] === '\n') break;      // 换行了，那它是除号不是正则
        i++;
      }
      while (i < n && /[a-z]/.test(src[i])) i++;
      out += src.slice(start, i);
    } else { out += c; i++; }
    if (i > 0 && !/\s/.test(src[i - 1] || ' ')) prev = src[i - 1];
  }
  return out;
}

const blankMatch = (text, re) => text.replace(re, m => m.replace(/[^\n]/g, ' '));

const registry = {};                  // 文件名 -> 该模块的导出对象
const loading = [];                   // 用于报环：正在加载中的文件

/** `a, b as c` -> [{remote:'a',local:'a'},{remote:'b',local:'c'}] */
function pairNames(blob) {
  return String(blob || '').split(',').map(s => s.trim()).filter(Boolean).map(s => {
    const p = s.split(/\s+as\s+/).map(x => x.trim());
    return { remote: p[0], local: p[p.length - 1] };
  });
}

function load(file) {
  if (registry[file]) return registry[file];
  if (loading.includes(file)) {
    errors.push('循环依赖: ' + loading.concat(file).join(' -> '));
    return {};
  }
  loading.push(file);
  const src = blankComments(fs.readFileSync(path.join(WEB, file), 'utf8'));

  const deps = [];
  RE_IMPORT.lastIndex = 0;
  let m;
  while ((m = RE_IMPORT.exec(src)) !== null) {
    deps.push({
      names: pairNames(m[2]).concat(pairNames(m[1]), pairNames(m[3])),
      target: m[4],
    });
  }
  // `export { local as pub }`：对象字面量的键必须是 pub，值才是 local。
  const exported = [];
  RE_EXPORT.lastIndex = 0;
  while ((m = RE_EXPORT.exec(src)) !== null) {
    for (const p of pairNames(m[1])) {
      if (!exported.some(x => x.pub === p.local)) exported.push({ pub: p.local, local: p.remote });
    }
  }
  // `export const X = ...` exports the name as-is.
  RE_EXPORT_DECL.lastIndex = 0;
  while ((m = RE_EXPORT_DECL.exec(src)) !== null) {
    if (!exported.some(x => x.pub === m[1])) exported.push({ pub: m[1], local: m[1] });
  }
  const body = blankMatch(blankMatch(src, RE_IMPORT), RE_EXPORT);

  // 递归：被 import 的先求值完 —— 和浏览器里 ES module 的规则一致。
  const prelude = [];
  for (const d of deps) {
    const dep = path.basename(d.target);
    if (!fs.existsSync(path.join(WEB, dep))) {
      errors.push(file + ': import 的路径不存在 -> ' + d.target);
      continue;
    }
    const mod = load(dep);
    const missing = d.names.filter(x => !(x.remote in mod)).map(x => x.remote);
    if (missing.length) {
      errors.push(file + ': ' + dep + ' 没有导出 ' + missing.join(', '));
    }
    if (d.names.length) {
      const pairs = d.names.map(x => x.remote + ': ' + x.local).join(', ');
      prelude.push('const { ' + pairs + ' } = __registry[' + JSON.stringify(dep) + '];');
    } else {
      prelude.push('__registry[' + JSON.stringify(dep) + '];');
    }
  }

  const factory =
    '(function (__registry) {\n' + prelude.join('\n') + '\n' + body +
    '\nreturn { ' + exported.map(x => x.pub + ': ' + x.local).join(', ') + ' };\n})';
  try {
    const fn = vm.runInContext(factory, ctx, { filename: file });
    registry[file] = fn(registry);
    log.push('  [ok]   ' + file + ' 加载并执行'
             + (deps.length ? '  <- ' + deps.map(d => path.basename(d.target)).join(', ') : ''));
    return registry[file];
  } catch (e) {
    errors.push(file + ': ' + e.message + '\n' + (e.stack || '').split('\n').slice(1, 4).join('\n'));
    registry[file] = {};
    return registry[file];
  } finally {
    loading.pop();
  }
}

async function call(label, fn) {
  try {
    await fn();
    log.push('  [ok]   ' + label);
  } catch (e) {
    errors.push(label + ': ' + e.message + '\n' + (e.stack || '').split('\n').slice(1, 4).join('\n'));
  }
}

(async () => {
  console.log('== 前端冒烟测试（真实数据结构）==\n');
  // 只加载入口。模块顺序由 import 图决定 —— 这正是这次重构要证明的事：
  // 原来是 index.html 里三个 <script> 的先后，而 home.js 末尾的 Home.boot()
  // 会在 app.js 还没解析完时就去调 App.setLabels()，靠"网络往返比解析慢"才
  // 没炸。现在 home.js 静态 import app.js，boot() 不可能跑到前面去。
  load('home.js');

  // 加载失败要立刻停在这里报出来。以前模块是拍平的，一个加载错误会推迟到
  // 几十行之后变成"App.xxx is not a function"，看不出真正的原因。
  if (errors.length) {
    console.log(log.join('\n'));
    console.log('\n===== 模块加载失败 =====');
    errors.forEach(e => console.log('\n--- ' + e));
    process.exit(1);
  }

  // home.js 导出的是 { Home }，app.js 直接导出它的公开接口。
  const ctxHome = (registry['home.js'] || {}).Home || {};
  const ctxApp = registry['app.js'] || {};

  await call('Home.refresh()', async () => { await ctxHome.refresh(); });
  await call('Home.openBrowser()', async () => { await ctxHome.openBrowser(); });
  await call('App.start()', async () => { ctxApp.start(); });
  await new Promise(r => setTimeout(r, 60));   // let the fetch chain settle
  await call('渲染队列 + 列表', async () => {
    // start() already kicked off loadState -> loadQueue -> renderList/render
  });

  // exercise the interaction paths directly
  const App = ctxApp;
  // The decision words now arrive from the API at startup. This harness never
  // runs the server, so it has to seed them -- and the drag tests below assert
  // on the stamp text, which would otherwise be blank. That blank is the
  // intended failure mode: a use before startup shows nothing rather than a
  // silently stale word.
  App.setLabels({ decisions: { keep: '要', reject: '不要', mark: '收藏' } });
  await call('缩放 30%', async () => {});
  await call('setList(false) / setList(true)', async () => {
    App.setList(false); App.setList(true);
  });

  // ── the drag gesture ──
  // This path once had a stale identifier that threw on EVERY mousemove. The
  // card still followed the pointer (that assignment ran first) so it looked
  // fine, while the veil and label stayed at opacity 0 -- a drag with no
  // feedback at all. Nothing caught it: `node --check` only sees syntax, and no
  // other test ever simulated a drag.
  //
  // Time is advanced between moves so these read as deliberate drags. With the
  // clock standing still the pointer velocity would be infinite and every one of
  // them would register as a flick.
  const down = (x) => ctx.document.getElementById('photoStage').dispatchEvent(
    new ctx.MouseEvent('mousedown', { button: 0, buttons: 1, clientX: x, clientY: 300 }));
  const move = (x) => ctx.window.dispatchEvent(
    new ctx.MouseEvent('mousemove', { bubbles: true, buttons: 1, clientX: x, clientY: 300 }));
  const up = () => ctx.window.dispatchEvent(
    new ctx.MouseEvent('mouseup', { buttons: 0 }));
  const stageEl = () => ctx.document.getElementById('photoStage');
  const stampText = () => String(ctx.document.getElementById('previewStamp').textContent);

  /** Drag slowly to `to` in 10 steps, 40ms apart: far too slow to be a flick. */
  const slowDrag = (from, to) => {
    down(from);
    for (let i = 1; i <= 10; i++) {
      advance(40);
      move(from + (to - from) * i / 10);
    }
    pump(14);   // let the spring pull the body toward where the pointer is
  };

  await call('拖拽向左：进度变量更新（证明积分器在跑）', async () => {
    slowDrag(500, 350);
    const pl = parseFloat(stageEl().style.getPropertyValue('--pl'));
    if (!(pl > 0)) {
      throw new Error('向左拖了 150px，--pl 仍是 ' + pl + '（物理没有推进）');
    }
    if (stampText() !== '不要') throw new Error('提示文字是「' + stampText() + '」，应为「不要」');
    up();
    pump(50);
  });

  await call('拖拽向右：进度变量更新且提示为「要」', async () => {
    slowDrag(500, 650);
    const pr = parseFloat(stageEl().style.getPropertyValue('--pr'));
    if (!(pr > 0)) throw new Error('向右拖了 150px，--pr 仍是 ' + pr);
    if (stampText() !== '要') throw new Error('提示文字是「' + stampText() + '」，应为「要」');
    up();
    pump(50);
  });

  await call('拖拽回中间：进度归零（取消）', async () => {
    down(500);
    advance(60); move(380);          // out to the left
    pump(10);
    advance(60); move(505);          // and back across the middle
    pump(30);                        // spring pulls the body home
    const pl = parseFloat(stageEl().style.getPropertyValue('--pl') || '0');
    const pr = parseFloat(stageEl().style.getPropertyValue('--pr') || '0');
    if (pl > 0 || pr > 0) {
      throw new Error('回到中间后进度没有归零：--pl=' + pl + ' --pr=' + pr);
    }
    up();
    pump(50);
  });

  // ── throwing ──
  // A flick should decide without travelling the full 138px, and the card should
  // then COAST -- the velocity it was released with carries on. That is the part
  // a keyframe animation cannot do, so it is the part worth asserting.
  const cardX = () => {
    const m = /translate3d\((-?[\d.]+)px/.exec(
      ctx.document.getElementById('photoCard').style.transform || '');
    return m ? parseFloat(m[1]) : 0;
  };

  await call('快速向左甩：距离不足也判定为甩出，且卡片继续飞', async () => {
    down(500);
    // 60px in 24ms = 2.5 px/ms, comfortably over FLING_MIN_V (0.55)
    for (let i = 1; i <= 6; i++) { advance(4); move(500 - i * 10); }
    pump(2);
    const before = cardX();
    up();
    pump(24);
    const after = cardX();
    if (!(after < before - 100)) {
      throw new Error('甩出后卡片没有继续飞：松手时 x=' + Math.round(before) +
                      '，24 帧后 x=' + Math.round(after) + '（应在向左远去）');
    }
    pump(90);
  });

  await call('拖到一半突然停住：贴住目标，不回弹不过冲', async () => {
    down(500);
    advance(40); move(430);
    advance(40); move(360);        // the pointer now rests at -140
    const xs = [];
    for (let i = 0; i < 24; i++) { pump(1); xs.push(cardX()); }
    const deepest = Math.min(...xs);
    if (deepest < -140 - 4) {
      throw new Error('过冲了：指针停在 -140，卡片却到了 ' + Math.round(deepest));
    }
    for (let i = 1; i < xs.length; i++) {
      if (xs[i] > xs[i - 1] + 0.5) {
        throw new Error('停住之后回弹了：第 ' + i + ' 帧从 ' + Math.round(xs[i - 1]) +
                        ' 退回 ' + Math.round(xs[i]) + '（抓在手里的东西不会自己弹）');
      }
    }
    if (Math.abs(xs[xs.length - 1] + 140) > 3) {
      throw new Error('最终没有贴住指针：' + Math.round(xs[xs.length - 1]) + '，应为 -140');
    }
    up(); pump(80);
  });

  await call('甩出结束后：卡片归位且过渡被恢复', async () => {
    down(500);
    for (let i = 1; i <= 6; i++) { advance(4); move(500 + i * 10); }
    pump(2);
    up();
    pump(120);
    const card = ctx.document.getElementById('photoCard');
    // The integrator switches the transition OFF while it drives transform. If
    // that is not restored, the keyboard path loses its spring home, and if the
    // transform is not blanked with it still off the card animates back from
    // wherever the throw left it -- which made the next photo look like it slid
    // in from the side.
    if (card.style.transition !== '') {
      throw new Error('过渡没有被恢复：' + JSON.stringify(card.style.transition));
    }
  });

  // NOT TESTED HERE: the list tally (renderListSummary).
  // It used to count S.queue -- the already-FILTERED list -- so clicking 要 left
  // 要 as the only chip with a non-zero count, dropped the other three from the
  // row, and removed any way back. Fixed by counting state.counts.decisions (the
  // whole library) and always rendering all four.
  //
  // It cannot be asserted in this harness: the stub document is synthesised on
  // demand and does NOT parse innerHTML, so querySelectorAll over rendered
  // markup always returns nothing. A test here would pass no matter what the
  // code did, which is worse than no test. Verified in the browser instead.

  await call('慢慢拖但没过线：弹簧把它拉回中位', async () => {
    slowDrag(500, 400);      // 100px, under DRAG_COMMIT (138), 0.25 px/ms
    up();
    pump(120);               // long enough for the spring to settle
    const x = cardX();
    if (Math.abs(x) > 6) {
      throw new Error('没有过判定线，但卡片停在了 x=' + Math.round(x) + '，没有回到中位');
    }
  });

  console.log(log.join('\n'));
  console.log('\n调用的接口: ' + [...new Set(fetchCalls)].join(', '));
  if (errors.length) {
    console.log('\n===== 发现 ' + errors.length + ' 个问题 =====');
    errors.forEach(e => console.log('\n--- ' + e));
    process.exit(1);
  }
  console.log('\n===== 前端冒烟测试通过 =====');
})();
