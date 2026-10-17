"""Throwaway: cut web/app.js into ES modules by EXACT line ranges.

Guarantees, asserted below:
  * every non-blank line of the original app.js (outside the replaced envelope,
    lines 24-27 and 1758-1760) lands in exactly ONE module file, byte-identical
    after removing the two spaces of IIFE indentation.
Nothing is retyped, so a transcription slip is impossible.

Run: python tmp_split/split.py
"""
import io, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
SRC = io.open(os.path.join(ROOT, "tmp_split", "app.js.orig"), encoding="utf-8").read().split("\n")

ENVELOPE = set(range(1, 28)) | set(range(1758, 1761))

# ---------------------------------------------------------------- headers
HEAD = {}

HEAD["state.js"] = """/* 过片 Guopian — 全应用共享的那一份可变状态。叶子模块，谁都不 import。
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
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""
HEAD["view.js"] = """/* 过片 Guopian — 视口几何：适应窗口、缩放、平移、滚轮与双击手势。
 *
 * 为什么单独成模块：这一整块只依赖 V（尺寸/比例/缩放）和 DOM 的边框盒，
 * 是纯几何，和队列、决策、卡片内容都没有关系。把它和渲染混在一起，
 * 就会出现"改一下缩放下限，结果碰到了列表"这种耦合。
 *
 * @requires ./state.js   el V cur —— 读 DOM 缓存、读写视口几何
 *
 * 唯一一条向上的线是 placeStamp()：fitStage() 算完盒子之后要把手势印章
 * 重新贴到照片上，而 placeStamp 住在 card.js。card.js 反过来要 import
 * fitStage()，直接互相 import 就成环了，所以用 configure() 注入。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""
HEAD["physics.js"] = """/* 过片 Guopian — 拖拽手势：一个手写积分的刚体，加它的反馈和事件入口。
 *
 * 为什么单独成模块：这是全项目唯一一段"有状态、按帧推进、跨帧保持"的代码
 * （P、drag 都是模块私有 let，外面碰不到）。它和渲染、队列、决策完全无关，
 * 只依赖 V/LABEL/DOM。放进 app.js 的话，读决策流程的人必须先绕过 260 行物理。
 *
 * @requires ./state.js   el V LABEL cur RELEASE_CLASS
 * @requires ./view.js    applyView clampPan —— 平移时复用同一套钳位
 *
 * 唯一一条向上的线是"甩出去之后算哪个决定"：那属于 app.js 的决策流程，
 * import app.js 会成环，所以 configure({ onCommit }) 注入。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""
HEAD["histogram.js"] = """/* 过片 Guopian — 照片上的三种叠加信息：人脸框、直方图、过曝斑马纹。
 *
 * 为什么单独成模块：它们都从"用户真正在看的那张位图"出发（visibleImage），
 * 都是只读的绘图，都不改变任何状态。三块放一起是因为它们共享同一个前提：
 * 全分辨率层没到之前，画的是预览层 —— 这个判断只写一次。
 *
 * @requires ./state.js   el S V
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""
HEAD["list.js"] = """/* 过片 Guopian — 左侧照片列表，以及"上次看到哪一张"的记忆。
 *
 * 为什么单独成模块：列表的重绘（缩略图懒加载、当前项高亮、汇总条、进度条）
 * 是一整套自成体系的 DOM 操作，和卡片渲染没有共享代码。混在一起的时候，
 * 改汇总条的一个计数就要动 1700 行的文件。
 *
 * @requires ./state.js   el S LABEL
 * @requires ./core.js    esc $$
 *
 * 三处向上的调用用 configure() 注入，因为 import 上去就成环：
 *   render        —— 列表项被点击时要换卡片（card.js）
 *   loadQueue     —— 汇总条被点击时要重新拉队列（app.js）
 *   renderTriage  —— 同时要把顶部的筛选条画成一致的状态（app.js）
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""
HEAD["card.js"] = """/* 过片 Guopian — 卡片本身：预览、原图、建议、问题标签、元信息。
 *
 * 为什么单独成模块：这一块是"一张照片怎么显示"，是改动最频繁的地方，
 * 也是唯一需要同时读 S/V/LABEL/VERDICT/OWNED 的地方。把它和网格、对话框、
 * 键位分开，改版式的人就不用经过决策流程。
 *
 * @requires ./state.js      el S V cur LABEL VERDICT OWNED
 * @requires ./core.js       $ $$ api esc
 * @requires ./view.js       fitStage centred updateZoomBadge
 * @requires ./histogram.js  drawHistogram renderOverlay buildZebra
 * @requires ./list.js       highlightCurrent savePos
 *
 * 一处向上的调用用 configure() 注入：render() 开头要清掉上一次"按住预览"
 * 的残留，而那一整套视觉状态（含 hold）的生命周期在 app.js —— 它要跨
 * flyOut / endHold 好几个阶段。为这一个函数 import app.js 会成环。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""
HEAD["grid.js"] = """/* 过片 Guopian — 网格视图：一次看很多张，可以框选批量决定。
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
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""
HEAD["keys.js"] = """/* 过片 Guopian — 键盘。全应用唯一一处键位表。
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
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""
HEAD["app.js"] = """/* 过片 Guopian — 卡片流程的接线层：生命周期、决策、对话框、以及所有模块的装配。
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
 * @requires ./core.js       G ( $ $$ api toast esc sleep fmtCount ) 与 Views
 * @requires ./state.js      el S V cur LABEL VERDICT OWNED HOLD_CLASS RELEASE_CLASS
 * @requires ./view.js       fitStage layerTransform setCardOffset
 * @requires ./physics.js    physReset setDragProgress 与四个鼠标入口
 * @requires ./list.js       renderList markListItem pickStartIndex
 * @requires ./card.js       render renderActionState renderDecisionBadge placeStamp
 * @requires ./grid.js       openGrid closeGrid onGridClick decideSelected
 * @requires ./keys.js       onKeyDown onKeyUp
 * @requires ./index.html    every id this file looks up
 * @requires /api/home        labels, and `current` when a library is open
 * @requires /api/state       counts, issue_summary, labels
 * @requires /api/queue       the list and the card order
 *
 * 由 web/home.js 作为唯一入口 import（见那里的注释：这是修掉启动竞态的关键）。
 *
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */"""


# ------------------------------------------------------- module -> ranges
R = {
    "state.js":     [(28, 28), (29, 39), (41, 47), (49, 50), (51, 69), (251, 251)],
    "physics.js":   [(89, 110), (804, 833), (849, 1130)],
    "view.js":      [(681, 802), (835, 847), (1132, 1144)],
    "histogram.js": [(1354, 1444)],
    "list.js":      [(253, 404)],
    "card.js":      [(406, 679)],
    "grid.js":      [(1446, 1501)],
    "keys.js":      [(1657, 1756)],
    "app.js":       [(71, 88), (112, 237), (239, 249), (1146, 1232), (1234, 1352),
                     (1503, 1574), (1576, 1655)],
}

# --------------------------------------------------------- imports & exports
IMPORTS = {
    "physics.js": ["import { el, V, LABEL, cur, RELEASE_CLASS } from './state.js';",
                   "import { applyView, clampPan } from './view.js';"],
    "view.js":    ["import { el, V, cur } from './state.js';"],
    "histogram.js": ["import { el, S, V } from './state.js';"],
    "list.js":    ["import { el, S, LABEL } from './state.js';",
                   "import { esc, $$ } from './core.js';"],
    "card.js":    ["import { el, S, V, cur, LABEL, VERDICT, OWNED } from './state.js';",
                   "import { $, api, esc } from './core.js';",
                   "import { fitStage, centred, updateZoomBadge } from './view.js';",
                   "import { drawHistogram, renderOverlay, buildZebra } from './histogram.js';",
                   "import { highlightCurrent, savePos } from './list.js';"],
    "grid.js":    ["import { el, S, LABEL } from './state.js';",
                   "import { $, api, toast, esc } from './core.js';",
                   "import { fitStage } from './view.js';",
                   "import { render } from './card.js';"],
    "keys.js":    ["import { el, S, V, cur } from './state.js';",
                   "import { $, toast } from './core.js';",
                   "import { resetView, zoomAt, maxScale } from './view.js';",
                   "import { renderOverlay, buildZebra } from './histogram.js';",
                   "import { openGrid, closeGrid } from './grid.js';",
                   "import { render } from './card.js';"],
    "app.js":     ["import { G, Views } from './core.js';",
                   "import { el, S, V, cur, LABEL, VERDICT, OWNED, HOLD_CLASS, RELEASE_CLASS } from './state.js';",
                   "import { fitStage, layerTransform, setCardOffset } from './view.js';",
                   "import { physReset, setDragProgress, onStageDown, onDragMove, onDragEnd, cancelDrag } from './physics.js';",
                   "import { renderList, markListItem, pickStartIndex } from './list.js';",
                   "import { render, renderActionState, renderDecisionBadge, placeStamp } from './card.js';",
                   "import { openGrid, closeGrid, onGridClick, decideSelected } from './grid.js';",
                   "import { onKeyDown, onKeyUp } from './keys.js';"],
}

# The destructure that the IIFE used to do. app.js is the only module that wants
# all seven; the comment is kept verbatim so the "knows nothing about home.js"
# note survives.
APP_DESTRUCTURE = [
    "// Everything comes from core.js. This file knows nothing about home.js.",
    "const { $, $$, api, toast, esc, sleep, fmtCount } = G;",
]

EXPORTS = {
    "state.js": ["el", "S", "V", "HOLD_CLASS", "RELEASE_CLASS", "LABEL", "VERDICT",
                 "OWNED", "cur"],
    "view.js": ["fitStage", "centred", "layerSize", "clampPan", "nativeScaleCap",
                "updateZoomBadge", "applyView", "resetView", "maxScale", "zoomAt",
                "layerTransform", "setCardOffset", "onWheel", "onDblClick",
                "configure"],
    "physics.js": ["DRAG_DEAD", "DRAG_COMMIT", "FLING_MIN_V", "FLING_MAX", "P",
                   "P_FOLLOW", "P_AIR", "P_SPIN", "P_TILT", "P_SETTLE", "scale",
                   "physApply", "physFrame", "physStart", "physStop", "physReset",
                   "pointerVelocity", "setDragProgress", "updateFeedback",
                   "onStageDown", "onDragMove", "onDragEnd", "cancelDrag",
                   "configure"],
    "histogram.js": ["renderOverlay", "visibleImage", "drawHistogram", "buildZebra"],
    "list.js": ["posKey", "savedPos", "savePos", "pickStartIndex", "itemHTML",
                "observeThumbs", "renderList", "renderListSummary", "highlightCurrent",
                "updateListProgress", "markListItem", "configure"],
    "card.js": ["render", "renderVerdict", "renderActionState", "renderDecisionBadge",
                "placeStamp", "prefetchAhead", "renderIssues", "renderGroup",
                "renderMeta", "loadDetail", "loadFullRes", "configure"],
    "grid.js": ["openGrid", "closeGrid", "loadGrid", "onGridClick", "decideSelected",
                "configure"],
    "keys.js": ["HOLD_KEYS", "TAP_KEYS", "overlayOpen", "onKeyDown", "onKeyUp",
                "compareNext", "configure"],
    "app.js": ["start", "stop", "attach", "loadQueue", "closeModal", "setList",
               "setLabels", "configure"],
}

# Hand-written additions (the only new code in the cut-out modules).
TAIL = {}

TAIL["view.js"] = """
/* ───────────────────── 注入：布局完成之后要把印章贴回去 ─────────────────────

   fitStage() 的最后一行调用 placeStamp()，而它住在 card.js；card.js 又必须
   import 这里的 fitStage()。两个模块互相 import 就是循环依赖 —— 浏览器会
   允许，但它让求值顺序变得不可预测，而顺序正是这次重构要消灭的东西。

   所以这里留一个同名占位符（名字不变，fitStage 的函数体就一个字都不用改），
   由 app.js 在装配时注入真正的实现。装之前是空的：加载期不会有人调用
   fitStage()，只有渲染之后才会。 */
let placeStamp = () => {};
function configure(hooks) {
  if (hooks && hooks.placeStamp) placeStamp = hooks.placeStamp;
}
"""

TAIL["physics.js"] = """
/* ───────────────────── 注入：甩出去之后算哪个决定 ─────────────────────

   onDragEnd 判定这是一次甩出之后，调用 commitDecision() —— 但决定这件事
   整个住在 app.js（乐观更新、翻到下一张、发请求）。import app.js 会成环，
   所以留同名占位符由 app.js 注入。 */
let commitDecision = () => {};
function configure(hooks) {
  if (hooks && hooks.commitDecision) commitDecision = hooks.commitDecision;
}

/* blur 时要取消正在进行的拖拽。drag 是这个模块私有的 let，外面拿不到
   也改不了，所以给一个动词而不是暴露那个变量 —— 暴露状态只会引来别人写它。 */
function cancelDrag() {
  if (drag) onDragEnd();
}
"""

TAIL["list.js"] = """
/* ───────────────────── 注入：列表自己能画，但换不了页面 ─────────────────────

   列表项被点击要换卡片（card.js 的 render）、汇总条被点击要重拉队列并让
   顶部筛选条跟着变（app.js 的 loadQueue / renderTriage）。这三件事都在上层，
   import 上去就成环，所以留同名占位符注入。 */
let render = () => {};
let loadQueue = async () => {};
let renderTriage = () => {};
function configure(hooks) {
  if (!hooks) return;
  if (hooks.render) render = hooks.render;
  if (hooks.loadQueue) loadQueue = hooks.loadQueue;
  if (hooks.renderTriage) renderTriage = hooks.renderTriage;
}
"""

TAIL["card.js"] = """
/* ───────────────────── 注入：清掉上一次按住预览的残留 ─────────────────────

   render() 的第一件事是把舞台恢复成什么都没按的样子，那是 app.js 的
   resetHoldVisual：它要同时管 hold、蒙版进度、印章、卡片偏移，而且必须和
   flyOut / endHold 的节奏一致。为一个函数 import app.js 会成环。 */
let resetHoldVisual = () => {};
function configure(hooks) {
  if (hooks && hooks.resetHoldVisual) resetHoldVisual = hooks.resetHoldVisual;
}
"""

TAIL["grid.js"] = """
/* ───────────────────── 注入：选中项不在当前队列里时重拉 ─────────────────────

   onGridClick 要在当前队列里定位那张照片；找不到（例如换了筛选条件）就退回
   app.js 的 loadQueue()。 */
let loadQueue = async () => {};
function configure(hooks) {
  if (hooks && hooks.loadQueue) loadQueue = hooks.loadQueue;
}
"""

TAIL["keys.js"] = """
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
"""

APP_TAIL = """
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
view.configure({ placeStamp });
physics.configure({ commitDecision });
list.configure({ render, loadQueue, renderTriage });
card.configure({ resetHoldVisual });
grid.configure({ loadQueue });
keys.configure({
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
"""


def slice_ranges(ranges):
    out = []
    for k, (a, b) in enumerate(ranges):
        if k:
            out.append("")          # the blank line that separated the two sections
        out.extend(SRC[a - 1:b])
    return out


def dedent(lines):
    """Remove exactly the two spaces the IIFE added. Asserted line by line."""
    out = []
    for ln in lines:
        if ln.startswith("  "):
            out.append(ln[2:])
        elif ln.strip() == "":
            out.append("")
        else:
            raise SystemExit("line not indented by 2: " + repr(ln))
    return out


# ---- coverage assertion -------------------------------------------------
seen = {}
for mod, ranges in R.items():
    for a, b in ranges:
        for i in range(a, b + 1):
            if i in seen:
                raise SystemExit("line {} claimed by {} and {}".format(i, seen[i], mod))
            seen[i] = mod
for i in range(1, len(SRC) + 1):
    if i in ENVELOPE:
        continue
    if SRC[i - 1].strip() == "":
        continue
    if i not in seen:
        raise SystemExit("non-blank line {} belongs to no module: {!r}".format(i, SRC[i - 1]))
print("coverage OK: every non-blank line of app.js 1..{} assigned exactly once".format(len(SRC)))

# ---- files --------------------------------------------------------------
for mod, ranges in R.items():
    body = dedent(slice_ranges(ranges))
    parts = [HEAD[mod], ""]
    parts += IMPORTS.get(mod, [])
    parts += [""]
    if mod == "app.js":
        parts += APP_DESTRUCTURE + [""]
    parts += body
    if mod == "app.js":
        parts += [APP_TAIL]
    tail = TAIL.get(mod, "")
    if tail:
        parts += [tail]
    names = EXPORTS[mod]
    # export block, wrapped at ~78 columns so it stays readable
    chunks = []
    line = "export {"
    for n in names:
        if len(line) + len(n) + 2 > 78:
            chunks.append(line)
            line = "  " + n + ","
        else:
            line += " " + n + ","
    chunks.append(line.rstrip(","))
    chunks.append("};")
    parts += [""] + chunks + [""]
    text = "\n".join(parts)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")
    io.open(os.path.join(WEB, mod), "w", encoding="utf-8", newline="\n").write(text)
    print("{:14s} {} lines".format(mod, text.count("\n")))
