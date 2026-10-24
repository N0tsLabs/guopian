/* 过片 Guopian — 全应用共享的那一份可变状态。叶子模块，谁都不 import。
 *
 * 为什么把它单独拿出来：
 *
 *   拆模块最大的坑是"状态归谁"。这几个对象（el 的 DOM 缓存、S 的会话状态、
 *   V 的视口几何、三个词表）原来在 app.js 的闭包里，谁都看得见、谁都改。
 *   改成 module 之后，如果每个模块各自持有一份，就会出现"列表看到 3 张、
 *   卡片看到 4 张"这种最难查的错。
 *
 *   所以它们留在这里，而且只留一份。ES module 的 import 是**活绑定**：
 *   别的模块 import 的是同一个对象，改字段立刻对所有人可见，不需要传参、
 *   不需要挂 window。约束是反向的 —— 谁都不许重新赋值这些绑定，只能改
 *   它们的字段。HOLD_CLASS / RELEASE_CLASS 也放这里，因为 app.js 和
 *   physics.js 都要用，而常量放两份就一定会漂。
 *
 *   cur() 只是 S.queue/S.idx 的一行取值器，五个模块都要用；与其让五个模块
 *   各自 import 一个 list.js，不如让它和它读取的状态待在一起。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */


const el = {};

const S = {
  state: null, queue: [], idx: 0, detail: null, running: false,
  showOverlay: false,        // 人脸框默认关闭，不遮挡照片
  showZebra: false,
  listOpen: true,
  // 'all' by default: the list is a file list, not a to-do queue. With
  // 'pending' a finished project showed an empty list and no way back.
  filter: 'all', sort: 'time',
  sel: new Set(),
  selAnchor: null,
  shiftAnchor: null,
  busy: false, poll: null, generation: -1,
};

const V = {
  s: 1, tx: 0, ty: 0, bw: 0, bh: 0, aspect: 0,
  areaW: 0, areaH: 0,      // the viewport the image is fitted into
  natW: 0, natH: 0,        // the currently loaded file
  origW: 0, origH: 0,      // the photo's real dimensions, from the catalog
  fullReady: false,
};

const HOLD_CLASS = { reject: 'hold-reject', keep: 'hold-keep', mark: 'hold-mark' };
const RELEASE_CLASS = { reject: 'release-reject', keep: 'release-keep', mark: 'release-mark' };

// The three judgements and their ONE set of user-facing names.
// Everything in the UI reads this -- toolbar, list, badges, toasts,
// apply panel -- so the vocabulary cannot drift apart again.
/* The three decision words, FILLED FROM THE SERVER at startup.
 *
 * They used to be written out here as literals, which made this the second
 * place they existed -- config.DECISION_LABELS is the first, and index.html
 * carried several more as bare text. Renaming a decision therefore took four
 * edits and missing one produced no error at all, just a screen showing two
 * different words for the same thing.
 *
 * Empty until setLabels() runs. That is deliberate: a use before startup is a
 * visible blank rather than a silently wrong word. */
const LABEL = { keep: '', reject: '', mark: '' };
// The software's suggestion, and the badge for a decision you have made.
// Both are DERIVED from the decision words, so they come from the same
// place -- see config.DECISION_VERDICT / DECISION_OWNED.
const VERDICT = { keep: '', reject: '', maybe: '' };
const OWNED = { keep: '', reject: '', mark: '' };

const cur = () => S.queue[S.idx] || null;

export { el, S, V, HOLD_CLASS, RELEASE_CLASS, LABEL, VERDICT, OWNED, cur
};
