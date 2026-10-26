/* 过片 Guopian — 模式：单图 / 多图。
 *
 * 为什么要有这个模块：单图和多图是两套**完全不同的操作逻辑** ——
 * 单图是"看一张、决定一张"，多图是"选一批、批量决定"。之前它们混在一起，
 * 于是出现"在多图里按空格，左边列表却在精选别的照片"这种冲突。
 *
 * @requires 无 —— 这个模块刻意不 import 任何东西：它是最底层，
 *           让 keys.js（单图）和 decidegrid.js（多图）都能引用它而不成环。
 *
 * 现在只有一个地方回答"当前处于哪个模式"，键盘只按模式分派，两套键位表
 * 各管各的，互不可见：
 *
 *   单图：keys.js 里的 SINGLE 分支（决定 / 导航 / 视图）
 *   多图：decidegrid.js 注册进来的 handler（格子焦点 / 挑选 / 批量提交）
 *
 * 判定依据用显式状态，不靠"某个 DOM 元素是否可见"—— 靠 DOM 猜状态正是
 * 之前 S.grid 泄漏（提交后没清，导致之后所有按键失灵）的根源。
 */

const listeners = new Set();
let mode = 'single';
let multiKeyHandler = null;

export function getMode() {
  return mode;
}

export function isMulti() {
  return mode === 'multi';
}

/** 切换模式。重复切换同一模式是空操作，不会触发监听。 */
export function setMode(next, reason) {
  if (next !== 'single' && next !== 'multi') return mode;
  if (next === mode) return mode;
  mode = next;
  for (const fn of listeners) {
    try { fn(mode, reason); } catch { /* 监听者的错不该影响切换 */ }
  }
  return mode;
}

export function onModeChange(fn) {
  if (typeof fn === 'function') listeners.add(fn);
  return () => listeners.delete(fn);
}

/** 多图模式注册自己的按键处理。返回 true 表示这个键被多图接管了。 */
export function registerMultiKeys(fn) {
  multiKeyHandler = typeof fn === 'function' ? fn : null;
}

export function handleMultiKey(e) {
  if (!multiKeyHandler) return false;
  try { return !!multiKeyHandler(e); } catch { return false; }
}
