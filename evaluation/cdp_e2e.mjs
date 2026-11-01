/* 过片 Guopian — 全功能端到端测试（真实浏览器，CDP 驱动）。
 *
 * 为什么不用 ui_e2e.py：那个走 Kimi WebBridge，需要浏览器扩展 + 本地守护进程，
 * 而且只作用于「当前活动标签页」。这个脚本换成 Chrome DevTools Protocol：
 * 连一个带独立 profile 的 Edge/Chrome，谁也不碰，命令行就能跑。
 *
 * 起浏览器（另开一个终端；--headless 也行）：
 *
 *   msedge --user-data-dir=%TEMP%\guopian-e2e-profile ^
 *          --remote-debugging-port=9224 --window-size=1440,900 ^
 *          http://127.0.0.1:8765/
 *   node evaluation/cdp_e2e.mjs 9224
 *
 * 覆盖：首页 / 文件夹浏览器 / 首次分析 / 单图键位（含按住预览）/ 筛选 /
 *      列表点击 / Ctrl 多选与多图提交 / 整批撤回 / 归档与回滚 / 重置决策 /
 *      设置 / 演示教程 / 移出列表与删数据。
 *
 * 测试库建在系统临时目录（从 guopian/assets/demo 复制），跑完删掉 ——
 * 不碰你自己的照片，也不会在「最近打开」里留下东西。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const PORT = process.argv[2] || '9224';
const BASE = process.argv[3] || 'http://127.0.0.1:8765';
const LIB = path.join(os.tmpdir(), 'guopian-e2e-lib');
const ASSETS = path.join(process.cwd(), 'guopian', 'assets', 'demo');
const SHOTS = path.join(process.cwd(), '.cache', 'e2e');
fs.mkdirSync(SHOTS, { recursive: true });

// 测试库：从随包的演示照片复制一份，跑完整个删掉。
fs.rmSync(LIB, { recursive: true, force: true });
fs.mkdirSync(LIB, { recursive: true });
for (const f of fs.readdirSync(ASSETS).filter((n) => n.endsWith('.jpg'))) {
  fs.copyFileSync(path.join(ASSETS, f), path.join(LIB, f));
}
console.log('test library:', LIB, fs.readdirSync(LIB).length + ' photos');
// 跑之前先记下已经存在的演示临时目录，最后只断言"这次没多出来"。
const demoDirsBefore = new Set(
  fs.readdirSync(os.tmpdir()).filter((n) => n.startsWith('guopian-demo-')));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, cond, detail = '') {
  results.push({ name, ok: !!cond, detail });
  console.log((cond ? '  [ok]  ' : '  [FAIL] ') + name + (detail ? '   ' + detail : ''));
}
const api = async (p, opt) => {
  const r = await fetch(BASE + p, opt);
  return r.json();
};
const post = (p, body) => api(p, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

/* ───────────────────────── CDP plumbing ───────────────────────── */
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('127.0.0.1:8765'));
if (!page) { console.error('app tab not found; targets:', list.map((t) => t.url)); process.exit(1); }
console.log('tab:', page.url);

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let msgId = 0;
const pending = new Map();
const consoleErrors = [];
ws.onmessage = async (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === 'Runtime.exceptionThrown') {
    consoleErrors.push('exception: ' + (m.params.exceptionDetails?.exception?.description
      || m.params.exceptionDetails?.text));
  }
  if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
    consoleErrors.push('log: ' + m.params.entry.text);
  }
  if (m.method === 'Page.javascriptDialogOpening') {
    await send('Page.handleJavaScriptDialog', { accept: true });
    console.log('  (auto-accepted dialog: ' + m.params.message.slice(0, 40) + ')');
  }
};
function send(method, params = {}) {
  const id = ++msgId;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res) => pending.set(id, res));
}
async function evalJs(expr) {
  const r = await send('Runtime.evaluate', {
    expression: `(() => { ${expr} })()`, returnByValue: true, awaitPromise: true,
  });
  if (r.result?.exceptionDetails) {
    throw new Error(r.result.exceptionDetails.exception?.description || 'eval failed');
  }
  return r.result?.result?.value;
}
async function waitFor(expr, ms = 20000, label = '') {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const v = await evalJs(`return (${expr});`).catch(() => false);
    if (v) return v;
    await sleep(150);
  }
  if (label) console.log('  (timeout waiting: ' + label + ')');
  return false;
}
async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(SHOTS, name), Buffer.from(r.result.data, 'base64'));
}
const KEYS = {
  ArrowRight: { code: 'ArrowRight', vk: 39 }, ArrowLeft: { code: 'ArrowLeft', vk: 37 },
  ArrowUp: { code: 'ArrowUp', vk: 38 }, ArrowDown: { code: 'ArrowDown', vk: 40 },
  ' ': { code: 'Space', vk: 32 }, Enter: { code: 'Enter', vk: 13 },
  Escape: { code: 'Escape', vk: 27 }, Backspace: { code: 'Backspace', vk: 8 },
  '?': { code: 'Slash', vk: 191 }, '0': { code: 'Digit0', vk: 48 },
};
function keyInfo(k) {
  if (KEYS[k]) return KEYS[k];
  const up = k.toUpperCase();
  return { code: (/\d/.test(k) ? 'Digit' : 'Key') + up, vk: up.charCodeAt(0) };
}
async function keyDown(k) {
  const d = keyInfo(k);
  await send('Input.dispatchKeyEvent', {
    type: 'keyDown', key: k, code: d.code,
    windowsVirtualKeyCode: d.vk, nativeVirtualKeyCode: d.vk,
  });
}
async function keyUp(k) {
  const d = keyInfo(k);
  await send('Input.dispatchKeyEvent', {
    type: 'keyUp', key: k, code: d.code,
    windowsVirtualKeyCode: d.vk, nativeVirtualKeyCode: d.vk,
  });
}
async function press(k, gap = 60) {
  await keyDown(k); await sleep(gap); await keyUp(k);
}
const click = (sel) => evalJs(
  `const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.click(); return true;`);
const visible = (sel) => evalJs(
  `const e = document.querySelector(${JSON.stringify(sel)}); return !!e && !e.classList.contains('hidden');`);
const count = (sel) => evalJs(`return document.querySelectorAll(${JSON.stringify(sel)}).length;`);
const currentId = () => evalJs(
  "const m = /\\/img\\/[^/]+\\/(\\d+)\\//.exec(document.querySelector('#photo').src); return m ? +m[1] : 0;");

async function clickText(sel, text) {
  return evalJs(`const els = [...document.querySelectorAll(${JSON.stringify(sel)})];
    const e = els.find(x => x.textContent.trim().indexOf(${JSON.stringify(text)}) >= 0);
    if (!e) return false; e.click(); return true;`);
}
async function listClick(i, mods = {}) {
  return evalJs(`const e = document.querySelector('.listItem[data-i="${i}"]');
    if (!e) return false;
    e.dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: ${!!mods.ctrl}, shiftKey: ${!!mods.shift} }));
    return true;`);
}
async function decisions() {
  const q = await api('/api/queue');
  const out = {};
  for (const it of q.items) out[it.id] = it.decision || null;
  return out;
}

await send('Runtime.enable');
await send('Page.enable');
await send('Log.enable');

/* ───────────────────── 0. 干净起点 ───────────────────── */
console.log('\n== 0. 重置到首页 ==');
await post('/api/close');
// 全新的首次运行：清掉"已看过教程"的标记，也清掉上一次运行留下的项目列表。
await evalJs("localStorage.removeItem('guopian.tour.v1'); localStorage.removeItem('guopian.coach'); return 1;");
try { fs.unlinkSync(path.join(process.cwd(), 'prefs.json')); } catch (e) { /* 没有就算了 */ }
await send('Page.navigate', { url: BASE + '/?no-coach=1' });
await sleep(3000);
check('首页可见', await visible('#homeView'));
check('首页没有项目', (await count('#recentList .projCard')) === 0,
  'cards=' + (await count('#recentList .projCard')));
check('两个入口都在', (await visible('#btnOpen')) && (await visible('#btnDemo')));
await shot('01-home.png');

/* ───────────────────── 1. 首次教程（跳过） ───────────────────── */
console.log('\n== 1. 首次运行自动弹教程 ==');
if (await visible('#tour')) {
  check('教程自动打开', true, await evalJs("return document.getElementById('tourStepNo').textContent"));
  await click('#tourSkip');
  await sleep(1200);
  check('跳过教程后回首页', await visible('#homeView'));
  check('跳过不留项目', (await api('/api/home')).recent.length === 0);
} else {
  check('教程自动打开', false, '（没弹：localStorage 里可能已经标记看过）');
}

/* ───────────────────── 2. 文件夹浏览器 ───────────────────── */
console.log('\n== 2. 文件夹浏览器 ==');
await click('#btnOpen');
await sleep(600);
check('浏览器打开', await visible('#browser'));
check('列出了盘符/入口', (await count('#roots .rootChip')) >= 1,
  'chips=' + (await count('#roots .rootChip')));
const drive = LIB.slice(0, 2);            // "C:"
const segs = LIB.slice(3).split('\\');    // Users\...\guopian-e2e-lib
await clickText('#roots .rootChip', drive);
await sleep(800);
for (const s of segs) {
  // 行是异步渲染的（navigate() 要等 /api/fs/list），所以先等它出现再点，
  // 点完再等 #pickedPath 变成目标目录 —— 固定 sleep 只会测出脚本自己的急躁。
  const appeared = await waitFor(
    `[...document.querySelectorAll('#dirList .dirRow')].some(x => x.textContent.indexOf(${JSON.stringify(s)}) >= 0)`,
    8000, 'dir row ' + s);
  if (!appeared) {
    check('进入 ' + s, false, (await evalJs("return document.getElementById('dirList').textContent")).replace(/\s+/g, ' ').slice(0, 200));
    break;
  }
  await clickText('#dirList .dirRow', s);
  const landed = await waitFor(
    `document.getElementById('pickedPath').textContent.toLowerCase().endsWith(${JSON.stringify(s.toLowerCase())})`,
    10000, 'nav ' + s);
  if (!landed) {
    check('进入 ' + s, false, await evalJs("return document.getElementById('pickedPath').textContent"));
    break;
  }
}
await sleep(600);
const picked = await evalJs("return document.getElementById('pickedPath').textContent");
check('定位到测试库', picked.toLowerCase() === LIB.toLowerCase(), picked);
check('打开按钮可用且数到 12 张', await evalJs(
  "const b=document.getElementById('browserOpen'); return !b.disabled && /12/.test(b.textContent)"),
  await evalJs("return document.getElementById('browserOpen').textContent"));
await shot('02-browser.png');
await click('#browserOpen');

/* ───────────────────── 3. 首次分析 + 进入卡片 ───────────────────── */
console.log('\n== 3. 首次分析 ==');
const sawBoot = await waitFor("!document.getElementById('bootView').classList.contains('hidden')", 4000);
const gotApp = await waitFor("!document.getElementById('appView').classList.contains('hidden')", 90000, 'appView');
check('进入过图界面', !!gotApp, sawBoot ? '（经过了整页进度屏）' : '（库很小，可能直接进）');
await sleep(800);

/* 首次引导层 */
if (await visible('#coach')) {
  check('首次引导层出现', true);
  await click('#coachOk');
  await sleep(400);
} else {
  check('首次引导层出现', false, '（没弹）');
}
check('左侧列表 12 张', (await count('#listScroll .listItem')) === 12,
  'items=' + (await count('#listScroll .listItem')));
check('大图已加载', await evalJs(
  "const p=document.getElementById('photo'); return p.complete && p.naturalWidth>0"));
await shot('03-card.png');

/* ───────────────────── 4. 单图键位 ───────────────────── */
console.log('\n== 4. 单图键位 ==');
const id0 = await currentId();
check('当前照片 id 可读', id0 > 0, 'id=' + id0);

/* 服务端的保存是异步的（前端乐观更新），所以断言要等它落地，而不是睡固定毫秒。
   固定 800ms 在冷启动/慢盘上会红成"按键没生效"，其实是还没写进库。 */
async function waitDecision(id, want, ms = 8000) {
  const t0 = Date.now();
  let last;
  while (Date.now() - t0 < ms) {
    const dd = await decisions();
    last = dd[id] ?? null;
    if (last === want) return last;
    await sleep(150);
  }
  return last;
}
async function waitOtherPhoto(id, ms = 5000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if ((await currentId()) !== id) return true;
    await sleep(150);
  }
  return false;
}

/* 按住 → 先预览，松手才生效 */
await keyDown('ArrowRight');
await sleep(150);
check('按住 → 出现预览态', /hold-keep/.test(await evalJs("return document.getElementById('photoStage').className")));
await keyUp('ArrowRight');
const gotKeep = await waitDecision(id0, 'keep');
check('→ 记为「过」', gotKeep === 'keep', 'decision=' + gotKeep);
check('→ 之后翻到下一张', await waitOtherPhoto(id0));

/* 回到刚才那张：空格 = 精选，再按一次取消（不前进） */
await press('ArrowUp');
await sleep(600);
check('↑ 回到上一张', (await currentId()) === id0);
await press(' ');
const gotMark = await waitDecision(id0, 'mark');
check('空格记为「精选」', gotMark === 'mark', 'decision=' + gotMark);
await press('ArrowUp');
await sleep(600);
await press(' ');
const cleared = await waitDecision(id0, null);
check('再按空格取消精选（且原地不动）',
  cleared === null && (await currentId()) === id0, 'decision=' + cleared);

/* ← = 不过 */
await press('ArrowLeft');
const gotReject = await waitDecision(id0, 'reject');
check('← 记为「不过」', gotReject === 'reject', 'decision=' + gotReject);

/* ⌫ 撤销 */
await press('Backspace');
const undone = await waitDecision(id0, null);
check('⌫ 撤销上一步', undone === null, 'decision=' + undone);
let d = await decisions();

/* ↑↓ 只翻看 */
const decidedBefore = Object.values(d).filter(Boolean).length;
const idA = await currentId();
await press('ArrowDown');
await sleep(600);
const idB = await currentId();
const d2 = await decisions();
check('↓ 只翻看、不改判断', idB !== idA && Object.values(d2).filter(Boolean).length === decidedBefore,
  `id ${idA} -> ${idB}, decided ${decidedBefore} -> ${Object.values(d2).filter(Boolean).length}`);

/* 视图类 */
await press('i'); await sleep(300);
check('I 切换人脸框', await visible('#overlay'),
  await evalJs("return document.getElementById('overlay').getAttribute('class')"));
await press('i'); await sleep(200);
await press('p'); await sleep(400);
check('P 打开斑马纹', await visible('#zebra'));
await press('p'); await sleep(200);

await keyDown('z'); await sleep(400);
const zoomed = await evalJs("return document.getElementById('zoomBadge').classList.contains('hidden') === false");
check('按住 Z 放大到 100%', zoomed);
await keyUp('z'); await sleep(500);
check('松开 Z 复原', await evalJs("return document.getElementById('zoomBadge').classList.contains('hidden')"));

await press('l'); await sleep(400);
check('L 收起左侧列表', await evalJs("return document.getElementById('listPane').classList.contains('hidden')"));
await press('l'); await sleep(400);
check('L 再展开', !(await evalJs("return document.getElementById('listPane').classList.contains('hidden')")));

await press('g'); await sleep(700);
check('G 打开网格', await visible('#gridView'), 'tiles=' + (await count('#grid .cell, #grid .gitem, #grid > *')));
await shot('04-grid.png');
await press('g'); await sleep(500);
check('G 关闭网格', !(await visible('#gridView')));

await press('?'); await sleep(400);
check('? 打开快捷键表', await visible('#help'));
await press('Escape'); await sleep(400);
check('Esc 关闭快捷键表', !(await visible('#help')));

/* C 跳到同组下一张 */
await clickText('#triageChips .chip', '连拍');
await sleep(900);
const inGroup = await evalJs("return document.querySelectorAll('#listScroll .listItem').length");
if (inGroup >= 2) {
  const gid1 = await currentId();
  await press('c'); await sleep(500);
  const gid2 = await currentId();
  check('C 跳到同组另一张', gid1 !== gid2, `id ${gid1} -> ${gid2}`);
} else {
  check('C 跳到同组另一张', false, '组里只有 ' + inGroup + ' 张');
}
await clickText('#triageChips .chip', '全部');
await sleep(900);

/* ───────────────────── 5. 筛选 + 列表点击 ───────────────────── */
console.log('\n== 5. 筛选与列表 ==');
await clickText('#triageChips .chip', '高光溢出');
await sleep(900);
check('按问题筛选只剩过曝那张', (await count('#listScroll .listItem')) === 1,
  'items=' + (await count('#listScroll .listItem')));
await clickText('#triageChips .chip', '全部');
await sleep(900);

const target = await evalJs("const e=document.querySelector('.listItem[data-i=\"7\"]'); return e ? +e.dataset.id : 0");
const idBeforeClick = await currentId();
await listClick(7);
await sleep(800);
check('点列表切到那一张', (await currentId()) === target && target !== idBeforeClick,
  `${idBeforeClick} -> ${await currentId()} (target ${target})`);

/* ───────────────────── 6. 多选 → 多图 → 提交 ───────────────────── */
console.log('\n== 6. Ctrl 多选 / 多图提交 ==');
// 先清空决策，这一步才只量"这一批"的效果。
await post('/api/reset', { confirm: true });
await sleep(500);
await clickText('#triageChips .chip', '全部');
await sleep(1000);
const mA = await evalJs("const e=document.querySelector('.listItem[data-i=\"2\"]'); return e ? +e.dataset.id : 0");
const mB = await evalJs("const e=document.querySelector('.listItem[data-i=\"3\"]'); return e ? +e.dataset.id : 0");
await listClick(2);
await sleep(300);
await listClick(3, { ctrl: true });
await sleep(800);
const hasGrid = await evalJs("return !!document.querySelector('.decideGrid') && !document.querySelector('.decideGrid').classList.contains('hidden')");
check('Ctrl 多选打开多图', hasGrid, 'tiles=' + (await count('.decideGrid .dgTile')));
await shot('05-decidegrid.png');

const beforeMulti = await decisions();
await press('ArrowRight');
await sleep(500);
const afterMulti = await decisions();
check('多图里单图键位不生效（方向键只移焦点）',
  JSON.stringify(beforeMulti) === JSON.stringify(afterMulti));

// 格子里的键盘决定只在"放大层"里有效（见 decidegrid.onKey 的注释），
// 普通网格用每张图上的「留下 / 精选」按钮，和鼠标用户走同一条路。
const markTile = (id, act) => evalJs(
  `const t = document.querySelector('.dgTile[data-id="${id}"] [data-act="${act}"]');
   if (!t) return false; t.click(); return true;`);
check('格子上的「留下」按钮可用', await markTile(mA, 'keep'));
await sleep(400);
check('格子上的「精选」按钮可用', await markTile(mB, 'mark'));
await sleep(400);
await press('Enter');
await sleep(1800);
d = await decisions();
check('提交：点过的按点的算', d[mA] === 'keep' && d[mB] === 'mark',
  `A=${d[mA]} B=${d[mB]}`);
check('提交：没点过的算不过', Object.values(d).filter(Boolean).length === 2,
  'decided=' + Object.values(d).filter(Boolean).length);

await press('Backspace');
await sleep(1800);
d = await decisions();
check('⌫ 撤销整批', Object.values(d).filter(Boolean).length === 0,
  'decided=' + Object.values(d).filter(Boolean).length
  + ' / toast: ' + (await evalJs("return document.getElementById('toast').textContent")));
await press('Escape');
await sleep(600);

/* ───────────────────── 7. 归档 + 回滚 ───────────────────── */
console.log('\n== 7. 归档与回滚 ==');
// 按键要等出卡动画（440ms）和后台保存都跑完；固定 sleep 偶尔会吞掉一次，
// 所以按"直到服务端确实多了一张决定"来推进。
for (let i = 0; i < 3; i++) {
  const want = Object.values(await decisions()).filter(Boolean).length + 1;
  for (let t = 0; t < 6; t++) {
    await press('ArrowRight');
    await sleep(700);
    if (Object.values(await decisions()).filter(Boolean).length >= want) break;
  }
}
d = await decisions();
check('先决定 3 张', Object.values(d).filter(Boolean).length >= 3,
  'decided=' + Object.values(d).filter(Boolean).length);

await click('#btnApply');
await sleep(900);
const pv = await api('/api/apply/preview?mode=quarantine');
check('应用决策弹框', await visible('#modal'));
const sheetText = (await evalJs("return document.getElementById('sheet').textContent")).replace(/\s+/g, ' ');
check('弹框里的张数和预览一致', sheetText.indexOf(String(pv.count)) >= 0,
  'preview=' + pv.count + ' / ' + sheetText.slice(0, 90));
await shot('06-apply.png');
await click('#apGo');
await sleep(2500);
const keepDir = path.join(LIB, '过');
const movedFiles = fs.existsSync(keepDir) ? fs.readdirSync(keepDir).filter((f) => f.endsWith('.jpg')) : [];
check('文件真的移动了', movedFiles.length >= 3, '过/ 里有 ' + movedFiles.length + ' 张');
check('弹框给出撤销入口', await visible('#modal'));

await click('#rbGo');
await sleep(2500);
const backFiles = fs.readdirSync(LIB).filter((f) => f.endsWith('.jpg'));
check('回滚把文件放回原处', backFiles.length === 12, '根目录 ' + backFiles.length + ' 张');
check('归档文件夹空了', !fs.existsSync(keepDir) || fs.readdirSync(keepDir).length === 0);

/* ───────────────────── 8. 重置全部决策 ───────────────────── */
console.log('\n== 8. 重置全部决策 ==');
await click('#btnApply');
await sleep(800);
await click('#apReset');          // 会弹 window.confirm，脚本会自动点「确定」
await sleep(2000);
d = await decisions();
check('重置后没有任何决策', Object.values(d).filter(Boolean).length === 0,
  'decided=' + Object.values(d).filter(Boolean).length);
await click('#apCancel').catch(() => {});
await sleep(400);

/* ───────────────────── 9. 设置 ───────────────────── */
console.log('\n== 9. 设置 ==');
await click('#btnSettings');
await sleep(700);
check('设置面板打开', await visible('#settings'));
const s1Before = await evalJs("return getComputedStyle(document.documentElement).getPropertyValue('--s1').trim()");
await evalJs(`const b=[...document.querySelectorAll('#setBody .seg button')]
  .find(x=>x.dataset.k==='density' && x.dataset.v==='compact'); if(b) b.click(); return !!b;`);
await sleep(800);
const s1After = await evalJs("return getComputedStyle(document.documentElement).getPropertyValue('--s1').trim()");
check('改界面密度生效', s1Before !== s1After, `${s1Before} -> ${s1After}`);

await evalJs(`const b=[...document.querySelectorAll('#setBody .seg button')]
  .find(x=>x.dataset.k==='strictness' && x.dataset.v==='strict'); if(b) b.click(); return !!b;`);
await sleep(800);
check('严格程度写进设置', (await api('/api/settings')).settings.strictness === 'strict');

await click('#setClear');
await sleep(1200);
check('清理缩略图缓存有反馈', /缓存|清理/.test(await evalJs("return document.getElementById('toast').textContent")),
  await evalJs("return document.getElementById('toast').textContent"));

await click('#setReset');
await sleep(1200);
const s = (await api('/api/settings')).settings;
check('恢复默认', s.strictness === 'standard' && s.density === 'standard',
  `${s.strictness}/${s.density}`);
await shot('07-settings.png');
await click('#setClose');
await sleep(400);

/* ───────────────────── 10. 演示教程（跳到结束） ───────────────────── */
console.log('\n== 10. 演示教程 ==');
await click('#backHome');
await sleep(1500);
check('回到首页', await visible('#homeView'));
const recentBefore = (await api('/api/home')).recent.length;
await click('#btnDemo');
await sleep(1200);
check('教程从头开始', /^1 \/ 11$/.test(await evalJs("return document.getElementById('tourStepNo').textContent")),
  await evalJs("return document.getElementById('tourStepNo').textContent"));
await click('#tourSkip');
await sleep(2000);
const recentAfter = (await api('/api/home')).recent.length;
check('教程跳过不留项目', recentAfter === recentBefore, `${recentBefore} -> ${recentAfter}`);
// 只比"这一次跑之前和之后"：之前就存在的目录可能是别的实验留下的，不该算到
// 这次教程头上（第一版用绝对值 0，被上一轮手工试验的残留搞红过）。
const demoDirsNow = fs.readdirSync(os.tmpdir()).filter((n) => n.startsWith('guopian-demo-'));
const created = demoDirsNow.filter((n) => !demoDirsBefore.has(n));
check('没有留下新的临时演示目录', created.length === 0, created.join(','));

/* ───────────────────── 11. 移出列表 / 删除数据 ───────────────────── */
console.log('\n== 11. 移出列表与删除 ==');
check('首页记住了测试库', (await api('/api/home')).recent.length === 1);
check('首页有卡片可点', (await count('#recentList .projCard')) === 1,
  'cards=' + (await count('#recentList .projCard')));
await click('#recentList .projCard [data-act="forget"]');
await sleep(900);
check('点 ✕ 先问「保留还是删掉」', await visible('#modal'),
  (await evalJs("return document.getElementById('modal').className")));
await shot('08-forget.png');
await click('#fgWipe');
await sleep(2500);
const home = await api('/api/home');
check('项目从列表消失', home.recent.length === 0);
const catDir = path.join(process.cwd(), 'catalogs');
const remains = fs.existsSync(catDir)
  ? fs.readdirSync(catDir).filter((n) => n.includes('guopian-e2e-lib')) : [];
check('分析数据已删除', remains.length === 0, remains.join(','));
check('照片一张没少', fs.readdirSync(LIB).filter((f) => f.endsWith('.jpg')).length === 12);

/* ───────────────────── 汇总 ───────────────────── */
const fails = results.filter((r) => !r.ok);
console.log('\n===== ' + (results.length - fails.length) + ' / ' + results.length + ' 通过 =====');
if (fails.length) fails.forEach((f) => console.log('  FAIL ' + f.name + '  ' + f.detail));
console.log('console errors: ' + (consoleErrors.length ? '\n  ' + consoleErrors.join('\n  ') : '(none)'));
// 测试库是复制出来的，跑完就删；照片本体在 guopian/assets/demo 里。
fs.rmSync(LIB, { recursive: true, force: true });
ws.close();
process.exit(fails.length ? 1 : 0);
