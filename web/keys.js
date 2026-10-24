/* 过片 Guopian — 键盘。全应用唯一一处键位表。
 *
 * 为什么单独成模块：键位表的价值就在于它能被一眼看全（HOLD_KEYS / TAP_KEYS
 * 紧挨着）；散在一个 1700 行的文件中间，就没人敢确认"某个键到底还有没有用"。
 * 这一段还留着一个曾经真的出过的坑：只有首页忽略快捷键，判断依据是
 * #homeView 是否隐藏 —— 见 onKeyDown 里的注释。
 *
 * @requires ./state.js      el S V cur
 * @requires ./core.js       $ toast
 * @requires ./view.js       resetView zoomAt maxScale
 * @requires ./histogram.js  renderOverlay buildZebra
 * @requires ./grid.js       openGrid closeGrid
 * @requires ./card.js       render
 *
 * 剩下的动作全部由 configure(actions) 注入。键盘是"分发器"：它自己不该
 * 认识决策、按住、撤销这些东西的实现，否则它就会变成第二个 app.js，
 * 而且是 import 方向朝上的那个（成环）。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */

import { el, S, V, cur } from './state.js';
import { $, toast } from './core.js';
import { resetView, zoomAt, maxScale } from './view.js';
import { renderOverlay, buildZebra } from './histogram.js';
import { openGrid, closeGrid } from './grid.js';
import { render } from './card.js';

// Three decisions, hold-to-preview. J/K mirror the arrows for people who
// keep their hand on the home row.
const HOLD_KEYS = { ArrowLeft: 'reject', j: 'reject', J: 'reject',
                    ArrowRight: 'keep', k: 'keep', K: 'keep',
                    ' ': 'mark', Spacebar: 'mark' };
// Navigation and undo fire on keydown; they change nothing about a photo.
const TAP_KEYS = { ArrowUp: 'prev', ArrowDown: 'next',
                   Backspace: 'undo', Delete: 'undo' };

function overlayOpen() {
  return !el.modal.classList.contains('hidden') ||
         !el.help.classList.contains('hidden') ||
         !el.coach.classList.contains('hidden') ||
         !el.browser.classList.contains('hidden');
}

function onKeyDown(e) {
  if (e.key === 'Escape') {
    el.help.classList.add('hidden');
    if (!el.modal.classList.contains('hidden')) closeModal();
    if (!el.gridView.classList.contains('hidden')) closeGrid();
    // hold 住在 app.js（它要跨 flyOut/endHold 几个阶段），这里只问它有没有。
    if (holding()) endHold(false);
    resetView(true);
    return;
  }
  if (overlayOpen()) return;
  // 多图对比（DecideGrid）开着的时候，单图那套快捷键必须先让路。
  //
  // 否则就是实测到的那个严重 bug：用户在多图里按空格/左右，界面看着没动，
  // 左边列表却在"精选"别的照片、还一路切走当前那张。多图有自己的按钮，
  // 单图的键在这里一个都不该生效。
  if (S.grid) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  // Only the HOME screen ignores shortcuts. This used to test whether
  // #appView was hidden -- but openGrid() hides it too, so opening the grid
  // silently killed every key on the page, including the G that was supposed
  // to close it again.
  if (!$('#homeView').classList.contains('hidden')) return;

  if (e.ctrlKey && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undo(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.repeat) return;

  if (!el.gridView.classList.contains('hidden')) {
    if (e.key === 'g' || e.key === 'G') closeGrid();
    return;
  }

  const holdAct = HOLD_KEYS[e.key];
  if (holdAct) { e.preventDefault(); startHold(holdAct); return; }
  const tapAct = TAP_KEYS[e.key];
  if (tapAct) { e.preventDefault(); runAction(tapAct); return; }

  switch (e.key) {
    case 'z': case 'Z':
      if (V.s <= 1.02) {
        const r = el.cardWrap.getBoundingClientRect();
        const target = V.origW ? (V.origW / V.bw) : maxScale();
        zoomAt(r.left + r.width / 2, r.top + r.height / 2,
               Math.min(target, maxScale()) / V.s, true);
        S.peekZoom = true;
      }
      break;
  /** How many faces the CURRENT photo has, 0 when the detail has not landed.
   *
   *  S.detail is fetched asynchronously, so pressing I immediately after a photo
   *  appears can legitimately find nothing yet. Reporting 0 in that case is
   *  honest: it is what the screen is showing. */
  function faceCount() {
    return (S.detail && S.detail.faces) ? S.detail.faces.length : 0;
  }

    case 'i': case 'I':
      S.showOverlay = !S.showOverlay; renderOverlay();
      // A plain toggle. It used to switch itself off after four seconds, on the
      // theory that the boxes cover the photo -- but the answer to "this annoys
      // me" is the key that turns it off, not a timer that decides for you.
      //
      // It also used to say "这张没检出人脸", which asserts a fact about the
      // photograph. On a photo of a woman whose eyes and glasses are plainly
      // visible that was simply false. A tool that cannot see something must
      // say so about itself.
      toast(S.showOverlay
        ? (faceCount() ? `人脸框：开，这张检出 ${faceCount()} 张脸`
                       : '人脸框：开 —— 这张没检测到脸（被遮挡、侧脸或太小时会漏）')
        : '人脸框：关');
      break;
    case 'p': case 'P':
      S.showZebra = !S.showZebra;
      if (S.showZebra) { buildZebra(); toast('过曝斑马纹：开'); }
      else { el.zebra.classList.add('hidden'); toast('过曝斑马纹：关'); }
      break;
    case '0': resetView(true); break;
    case 'g': case 'G': openGrid(); break;
    case 'l': case 'L': setList(!S.listOpen); break;
    case 'c': case 'C': compareNext(); break;
    case 'f': case 'F':
      if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
      else document.exitFullscreen();
      break;
    case '?': el.help.classList.remove('hidden'); break;
  }
}

function onKeyUp(e) {
  if (e.key === 'z' || e.key === 'Z') {
    if (S.peekZoom) { S.peekZoom = false; resetView(true); }
    return;
  }
  const held = holding();
  if (!held) return;
  if (HOLD_KEYS[e.key] === held) { e.preventDefault(); endHold(true); }
}

function compareNext() {
  const c = cur();
  if (!c || !c.group_id) { toast('这张不在相似组里'); return; }
  const mates = S.queue.filter(x => x.group_id === c.group_id);
  if (mates.length < 2) { toast('相似组里只有这一张在当前列表'); return; }
  const pos = mates.findIndex(x => x.id === c.id);
  S.idx = S.queue.findIndex(x => x.id === mates[(pos + 1) % mates.length].id);
  render();
  toast(`相似组 ${pos + 1}/${mates.length}`);
}

/* ───────────────────── 注入：键盘只负责分发 ─────────────────────

   这些动作都住在 app.js（openGrid / closeGrid 是 import，不算注入）。
   键盘自己不认识决定和按住，它只把按键翻译成一个动作名，这样键位表
   才能被单独读、单独改。 */
let startHold = () => {};
let endHold = () => {};
let runAction = () => {};
let undo = () => {};
let closeModal = () => {};
let setList = () => {};
/* 当前是否正按住某个动作键，以及按的是哪一个。用一个取值函数而不是一个
   变量：hold 住在 app.js，这里只该问，不该能改。 */
let holding = () => null;
function configure(actions) {
  if (!actions) return;
  if (actions.startHold) startHold = actions.startHold;
  if (actions.endHold) endHold = actions.endHold;
  if (actions.runAction) runAction = actions.runAction;
  if (actions.undo) undo = actions.undo;
  if (actions.closeModal) closeModal = actions.closeModal;
  if (actions.setList) setList = actions.setList;
  if (actions.holding) holding = actions.holding;
}


export { HOLD_KEYS, TAP_KEYS, overlayOpen, onKeyDown, onKeyUp, compareNext,
  configure
};
