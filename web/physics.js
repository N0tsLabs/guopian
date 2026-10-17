/* 过片 Guopian — 拖拽手势：一个手写积分的刚体，加它的反馈和事件入口。
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
 * 从 web/app.js 逐行切出（内容一字未改，只剥掉闭包的两层缩进）。 */

import { el, V, LABEL, cur, RELEASE_CLASS } from './state.js';
import { applyView, clampPan } from './view.js';


// ── drag gesture ──
// Nothing at all happens inside DRAG_DEAD: that explicit neutral zone is what
// stops the middle of a drag from flickering between 不过 and 要. The old
// threshold was 18px, so merely wobbling across the centre flipped the whole
// overlay to the other colour.
const DRAG_DEAD = 26;      // px of travel that means "I have not decided"
const DRAG_COMMIT = 138;   // px past which releasing decides

// ── throwing ──
// A card is not only dragged, it is flicked. Velocity at release decides two
// things: whether the gesture counts at all (a quick flick should not have to
// travel 138px first), and how far and how fast it goes.
const FLING_MIN_V = 0.55;  // px/ms at release (550 px/s) to count as a throw
const FLING_MAX = 2.6;     // px/ms that saturates the throw

function setDragProgress(pl, pr, pm) {
  const s = el.photoStage.style;
  s.setProperty('--pl', (pl || 0).toFixed(3));
  s.setProperty('--pr', (pr || 0).toFixed(3));
  s.setProperty('--pm', (pm || 0).toFixed(3));
}

/* ═════════════════════════ 鼠标：拖拽 / 平移 ═════════════════════════ */

let drag = null;

function onStageDown(e) {
  if (e.button !== 0 || !cur()) return;
  if (V.s > 1.02) {
    drag = { mode: 'pan', x: e.clientX, y: e.clientY, tx: V.tx, ty: V.ty };
    el.photoStage.classList.add('panning');
    el.photoLayer.classList.add('nofx');
  } else {
    drag = { mode: 'swipe', x: e.clientX, y: e.clientY, dx: 0,
             samples: [{ x: e.clientX, y: e.clientY, t: performance.now() }] };
    // A fresh grip always starts from the resting position. After a throw the
    // integrator has left the body far off-centre, and render() zeroes it --
    // but only once the commit callback has run, so this covers the case
    // where the next gesture begins before that.
    if (P.mode === 'idle') { P.x = P.y = P.vx = P.vy = P.a = P.av = 0; }
    // Grabbing the card interrupts the arrival. A running animation outranks
    // inline styles, so leaving cardRise in flight would swallow every
    // transform the drag writes and the card would not move at all.
    el.photoCard.classList.remove('entering');
    // .dragging turns OFF the transition on the card and the progress numbers,
    // so the gesture is 1:1 under the pointer. Removing it on release is what
    // plays the spring home.
    el.photoStage.classList.add('dragging');
    el.photoLayer.classList.add('nofx');
  }
  e.preventDefault();
}

/* ═════════════════════════ 拖拽物理 ═════════════════════════

   A real rigid body, integrated by hand. There is no physics engine here on
   purpose: with ONE body, no collisions and a single spring, an engine's
   value -- broadphase, the constraint solver, sleeping, compound shapes -- is
   entirely unused, and it would cost 80 KB (Matter.js, the smallest 2D one)
   plus a licence notice. What actually makes a drag feel physical is:

     1. it moves in BOTH axes, not just horizontally
     2. it LAGS the pointer instead of being welded to it, so it swings
     3. the velocity it had at release carries on afterwards
     4. it spins, and the spin follows the motion

   Semi-implicit Euler over those four is about twenty lines. Units below are
   pixels and milliseconds, and every constant is expressed "per 16.7 ms" and
   raised to the elapsed-time ratio, so the feel does not change with frame
   rate -- a 144 Hz display and a throttled 30 Hz one behave the same. */

const P = {
  x: 0, y: 0,          // offset from the resting position, px
  vx: 0, vy: 0,        // px per 16.7 ms step
  a: 0, av: 0,         // angle in degrees, angular velocity per step
  tx: 0, ty: 0,        // where the pointer is pulling it
  mode: 'idle',        // idle | drag | coast | home
  fresh: true,         // the next frame has no previous timestamp to use
  raf: 0, last: 0,
};

// Tuned for a photograph rather than a crate: light, and quick enough to feel
// attached while still visibly trailing the finger.
const P_FOLLOW = 0.34;   // fraction of the remaining distance closed per step
const P_AIR = 0.992;     // nearly none -- a thrown card is not in treacle
const P_SPIN = 0.055;    // degrees of spin per px/step of horizontal velocity
const P_TILT = 0.9;      // how much of the pull turns into lean, in degrees/px
const P_SETTLE = 0.35;   // stop below this per-step move, in px

const scale = (base, dt) => Math.pow(base, dt);   // per-step constant -> dt

function physApply() {
  el.photoCard.style.transform =
    'translate3d(' + P.x.toFixed(1) + 'px,' + P.y.toFixed(1) + 'px,0) ' +
    'rotate(' + P.a.toFixed(2) + 'deg)';
}

function physFrame(now) {
  // The first frame after a gesture starts has no previous timestamp to
  // measure against. It gets one ordinary step rather than dt = 0: at dt = 0
  // the body is still sitting at rest on the origin, which the settle test at
  // the bottom reads as "finished" and shuts the loop down before it ever
  // moves. That made a drag completely dead -- no spring, no feedback.
  const dt = P.fresh ? 1 : Math.min(48, now - P.last) / 16.7;
  P.fresh = false;
  P.last = now;

  if (P.mode === 'coast') {
    // Nothing holds it: it keeps the velocity it was thrown with and only the
    // air slows it. This is the part a keyframe animation cannot do -- the
    // direction and the spin are whatever the gesture actually was.
    P.vx *= scale(P_AIR, dt);
    P.vy *= scale(P_AIR, dt);
    P.av *= scale(0.97, dt);
    P.x += P.vx * dt;
    P.y += P.vy * dt;
    P.a += P.av * dt;
  } else {
    // FIRST-ORDER follow, not a spring. A spring is underdamped by nature, so
    // stopping the pointer mid-drag made the card bounce in place -- which is
    // not what a held object does. Exponential approach gives the same lag
    // (the card trails the finger) with no oscillation, ever: each step moves
    // a fixed FRACTION of the remaining distance, so it can only get closer.
    //
    // The throw does not need inertia here: release velocity is measured from
    // the POINTER, so what the card was doing a frame earlier is irrelevant.
    const tx = P.mode === 'drag' ? P.tx : 0;
    const ty = P.mode === 'drag' ? P.ty : 0;
    const k = 1 - scale(1 - P_FOLLOW, dt);      // frame-rate independent
    const dx = (tx - P.x) * k;
    const dy = (ty - P.y) * k;
    P.x += dx;
    P.y += dy;
    P.vx = dx;                                   // kept for the release maths
    P.vy = dy;
    // Spin still comes out of the motion: a card pulled sideways leans.
    const lean = -(tx - P.x) * P_TILT * 0.02;
    P.av += (lean * 0.05 - P.a * 0.03) * dt;
    P.av *= scale(0.88, dt);
    P.a += P.av * dt;
  }

  physApply();
  // The feedback has to be driven from HERE, not from the pointer handler.
  // The body advances on animation frames, so updating the veil only when the
  // pointer moves leaves it a frame behind the card -- and with two quick
  // moves and no frame in between, it never updates at all.
  if (P.mode === 'drag') updateFeedback();

  const spent = P.mode === 'coast'
    ? Math.abs(P.x) > 4000 || Math.abs(P.y) > 4000
    : (Math.abs(P.vx) + Math.abs(P.vy) < P_SETTLE &&
       Math.abs(P.x) + Math.abs(P.y) < 1.5);
  if (spent) { physStop(); return; }
  P.raf = requestAnimationFrame(physFrame);
}

/** The veil and the label, keyed off the body's real horizontal position.
 *
 * Only left and right mean anything: you can toss the card wherever you like,
 * but the three judgements are a left/right axis, so the feedback tracks the
 * horizontal component of where the card actually is. */
function updateFeedback() {
  const hx = P.x;
  const mag = Math.abs(hx);
  const p = mag < DRAG_DEAD ? 0 : Math.min(1, mag / DRAG_COMMIT);
  setDragProgress(p > 0 && hx < 0 ? p : 0, p > 0 && hx > 0 ? p : 0, 0);
  el.previewStamp.style.setProperty('--stamp-dx', hx.toFixed(1) + 'px');
  el.photoStage.classList.toggle('hold-reject', hx < -DRAG_DEAD);
  el.photoStage.classList.toggle('hold-keep', hx > DRAG_DEAD);
  if (p > 0) el.previewStamp.textContent = hx < 0 ? LABEL.reject : LABEL.keep;
}

function physStart(mode) {
  P.mode = mode;
  // The integrator writes `transform` every frame, so the card must not have
  // a transition on it: each write would restart the 420 ms spring and the
  // motion would smear into treacle.
  el.photoCard.style.transition = 'none';
  if (!P.raf) {
    P.fresh = true;
    P.raf = requestAnimationFrame(physFrame);
  }
}

function physStop() {
  if (P.raf) cancelAnimationFrame(P.raf);
  P.raf = 0;
  P.mode = 'idle';
  // Hand the transition back. A throw that ends by leaving the screen stops
  // the loop on its own, and without this the card would keep
  // `transition: none` forever -- silently killing the keyboard path's spring
  // home. Restoring it here is safe: nothing is changing the transform at this
  // moment, so there is nothing to animate.
  if (el.photoCard) el.photoCard.style.transition = '';
}

function physReset() {
  physStop();
  P.x = P.y = P.vx = P.vy = P.a = P.av = P.tx = P.ty = 0;
  // Blank the transform with the transition OFF, force a recalc, then restore.
  //
  // Clearing it while the transition is armed makes the card animate home
  // from wherever the throw left it -- 420 ms of sliding back from the edge.
  // The peek hands over within a few frames (the preview is prefetched), so
  // the card was being revealed part-way through that slide, which is exactly
  // the "next photo slides in from the side" that replaced the rise from the
  // stack.
  el.photoCard.style.transition = 'none';
  el.photoCard.style.transform = '';
  void el.photoCard.offsetWidth;
  el.photoCard.style.transition = '';
}

/** Pointer speed in px per ms over the tail of a gesture, on both axes.
 *
 * Uses the oldest and newest sample still in the window rather than the last
 * two moves: a single jittery pair of frames can read as a huge velocity, and
 * then a slow deliberate drag would fire as a flick. The window is short
 * enough that a drag which ENDS in a flick still measures fast.
 */
function pointerVelocity(samples) {
  if (!samples || samples.length < 2) return { vx: 0, vy: 0 };
  const a = samples[0], b = samples[samples.length - 1];
  const dt = b.t - a.t;
  if (!(dt > 1)) return { vx: 0, vy: 0 };
  return { vx: (b.x - a.x) / dt, vy: (b.y - a.y) / dt };
}

function onDragMove(e) {
  if (!drag) return;
  if (drag.mode === 'pan') {
    const p = clampPan(drag.tx + (e.clientX - drag.x), drag.ty + (e.clientY - drag.y), V.s);
    V.tx = p.tx; V.ty = p.ty;
    applyView(true);
    return;
  }
  const dx = e.clientX - drag.x;
  drag.dx = dx;
  // A short window of recent pointer positions. The velocity at RELEASE is
  // what turns a drag into a throw, and it has to be measured over the last
  // few frames -- an average since mousedown would call a slow drag that
  // ended in a flick "slow".
  drag.samples.push({ x: e.clientX, y: e.clientY, t: performance.now() });
  if (drag.samples.length > 6) drag.samples.shift();

  // The pointer is a TARGET, not a position. The body is spring-pulled toward
  // it and lags behind, which is where the weight and the swing come from --
  // welding the card to the cursor (what this used to do) is why a drag felt
  // like moving a rectangle rather than throwing a card.
  P.tx = dx;
  P.ty = e.clientY - drag.y;
  physStart('drag');
  // The loop keeps the feedback in step from here on; this one call just
  // avoids a frame of lag on the very first move.
  updateFeedback();
}

function onDragEnd() {
  if (!drag) return;
  const d = drag;
  drag = null;
  el.photoStage.classList.remove('panning');

  if (d.mode === 'pan') { el.photoLayer.classList.remove('nofx'); applyView(false); return; }

  // Whatever happens next, the gesture is over: dropping .dragging re-arms the
  // springs, so the card and the overlay travel home under their own easing.
  el.photoStage.classList.remove('dragging');

  // The release velocity, in px per ms, on BOTH axes. The horizontal part
  // decides (the three judgements are left/right), but the vertical part is
  // carried into the throw: toss the card up and to the left and it goes up
  // and to the left.
  const vel = pointerVelocity(d.samples);
  const power = Math.min(1, Math.abs(vel.vx) / FLING_MAX);

  const flicked = Math.abs(vel.vx) >= FLING_MIN_V &&
                  Math.sign(vel.vx) === Math.sign(P.x || vel.vx);
  const far = Math.abs(P.x) > DRAG_COMMIT;

  if (far || flicked) {
    const action = (P.x < 0 || (flicked && vel.vx < 0)) ? 'reject' : 'keep';

    // Hand the body the velocity it was released with, converted from px/ms
    // into px-per-step and amplified a little so a throw goes somewhere. From
    // here nothing is authored: it coasts, spins and leaves in whatever
    // direction the gesture actually had.
    const boost = 26 + power * 34;
    P.vx = vel.vx * boost;
    P.vy = vel.vy * boost;
    // A card thrown sideways also turns over. The spin comes from the throw,
    // not from a keyframe.
    P.av = -vel.vx * P_SPIN * 60;

    el.photoStage.classList.remove('hold-reject', 'hold-keep');
    setDragProgress(0, 0, 0);
    el.photoLayer.classList.remove('nofx');
    // Deliberately NOT adding RELEASE_CLASS[action]. That class carries a CSS
    // keyframe on `transform`, and a CSS animation outranks an inline style --
    // so it would silently override every transform the integrator writes and
    // the throw would be whatever the keyframe says, not what you threw.
    // The integrator is the exit here.
    //
    // The exit is the integrator, and the arrival is a plain cardRise. The two
    // are NOT animated together any more -- see render().
    physStart('coast');

    // Commit once it is actually off the picture, with a hard deadline so a
    // card thrown straight up still resolves.
    const deadline = performance.now() + 900;
    const wait = () => {
      const gone = Math.abs(P.x) > (V.bw || 600) * 1.1;
      if (P.mode === 'coast' && !gone && performance.now() < deadline) {
        setTimeout(wait, 40);
        return;
      }
      // The peek has already risen into the slot and is showing the next
      // photo at full size. render() must therefore NOT replay the arrival
      // animation -- it starts at scale .955, so replaying it made the card
      // appear in place and then jump back down before rising again.
      physReset();
      el.photoStage.classList.remove(RELEASE_CLASS[action]);
      commitDecision(action);
    };
    setTimeout(wait, 60);
  } else {
    // Under the threshold: let the spring pull it home. No keyframe, no
    // easing curve -- it is the same integrator that was just swinging it.
    physStart('home');
    el.photoStage.classList.remove('hold-reject', 'hold-keep');
    setDragProgress(0, 0, 0);
    setTimeout(() => el.photoLayer.classList.remove('nofx'), 30);
  }
}

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


export { DRAG_DEAD, DRAG_COMMIT, FLING_MIN_V, FLING_MAX, P, P_FOLLOW, P_AIR,
  P_SPIN, P_TILT, P_SETTLE, scale, physApply, physFrame, physStart, physStop,
  physReset, pointerVelocity, setDragProgress, updateFeedback, onStageDown,
  onDragMove, onDragEnd, cancelDrag, configure
};
