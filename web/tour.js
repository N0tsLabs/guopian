/* 过片 Guopian — the first-run tour.
 *
 * @requires web/core.js    G ( $ $$ esc )
 * @requires web/index.html the #tour shell, #tourStage and #tourCard
 *
 * A guided tour of a MOCK project, not of a real one.
 *
 * The earlier version generated a demo library and opened it through the real
 * API. That was wrong twice over: it swapped the user's library out from under
 * them, and it wrote files to disk just to show a picture. A tour does not need
 * to be real -- it needs to LOOK real and to be impossible to break.
 *
 * So the overlay carries a static replica of the project screen, built from the
 * app's own CSS classes so it is indistinguishable at a glance, and the tour
 * points at parts of it. Nothing here calls the API, touches a photo, or changes
 * any state. Whatever is underneath is still exactly where it was.
 */

import { G } from './core.js';

const Tour = (() => {
  const { $, esc } = G;

  const SEEN_KEY = 'guopian.tour.v1';
  let step = 0;
  let steps = [];

  /* The replica. Deliberately built from the real class names -- .photoCard,
   * .listItem, .act, .chips -- so it inherits the real styling and looks like
   * the app rather than like a picture of it. */
  const MOCK_HOME = `
    <div class="tourHome">
      <div class="tourRail">
        <div class="tourBrand">过片</div>
        <div class="tourRailBtns">
          <button class="btn primary block" data-ref="open">
            <span class="tourIco">▤</span> 打开新文件夹
          </button>
        </div>
        <div class="tourRailFoot">全部在本机处理</div>
      </div>
      <div class="tourHomeMain">
        <div class="tourHomeHead">最近打开 <b>2</b></div>
        <div class="tourProjGrid" data-ref="recent">
          <div class="tourProj">
            <div class="tourProjCover"></div>
            <div class="tourProjMeta"><b>川西</b><span>93 张 · 已审完</span></div>
          </div>
          <div class="tourProj">
            <div class="tourProjCover alt"></div>
            <div class="tourProjMeta"><b>婚礼</b><span>412 张 · 审到 210</span></div>
          </div>
        </div>
      </div>
    </div>`;

  const MOCK_PROJ = `
    <div class="tourApp">
      <div class="tourTop">
        <span class="tourTopName">川西</span>
        <span class="tourTopSpacer"></span>
        <button class="btn primary" data-ref="apply">应用决策</button>
      </div>
      <div class="tourChips" data-ref="chips">
        <span class="chip on">全部</span><span class="chip">未审</span>
        <span class="chip">过 74</span><span class="chip">不过 11</span>
        <span class="chip">精选 8</span><span class="chip">有明显问题</span>
        <span class="chip">连拍 / 相似组</span>
      </div>
      <div class="tourBody">
        <div class="tourList" data-ref="list">
          <div class="tourListItem keep"><span class="tourNum">1</span>
            <span class="tourThumb"></span><span class="tourNm">DSC09890.JPG</span><i>✓</i></div>
          <div class="tourListItem keep"><span class="tourNum">2</span>
            <span class="tourThumb a"></span><span class="tourNm">DSC09891.JPG</span><i>✓</i></div>
          <div class="tourListItem reject"><span class="tourNum">3</span>
            <span class="tourThumb b"></span><span class="tourNm">DSC09892.JPG</span><i>✕</i></div>
          <div class="tourListItem mark"><span class="tourNum">4</span>
            <span class="tourThumb c"></span><span class="tourNm">DSC09893.JPG</span><i>★</i></div>
          <div class="tourListItem"><span class="tourNum">5</span>
            <span class="tourThumb a"></span><span class="tourNm">DSC09894.JPG</span></div>
          <div class="tourListItem keep"><span class="tourNum">6</span>
            <span class="tourThumb"></span><span class="tourNm">DSC09895.JPG</span><i>✓</i></div>
        </div>
        <div class="tourStage" data-ref="stage">
          <div class="tourPhoto">
            <span class="tourBadge">建议过</span>
          </div>
          <div class="tourMetaLine">DSC09890.JPG · 1/50 f/5 ISO 320 · SONY ILCE-7C</div>
        </div>
      </div>
      <div class="tourActs">
        <button class="act reject" data-ref="reject">
          <span class="ak">←</span><span class="al">不过</span></button>
        <button class="act mark" data-ref="mark">
          <span class="ak">空格</span><span class="al">精选</span></button>
        <button class="act keep" data-ref="keep">
          <span class="ak">→</span><span class="al">过</span></button>
        <span class="tourActsSpacer"></span>
        <button class="act2" data-ref="undo"><span class="ak">⌫</span>撤销</button>
      </div>
    </div>`;

  function buildSteps() {
    return [
      {
        screen: 'home',
        t: '这是过片',
        b: '一个只在你电脑上跑的照片筛选工具，不联网、不上传。'
         + '几千张照片不用一张张打开 —— 它把照片一张张推到你面前，'
         + '你只需要说「要」还是「不要」。',
        ref: null,
      },
      {
        screen: 'home',
        t: '第一步：打开一个文件夹',
        b: '点这里选一个装着照片的文件夹。整个文件夹会被一起读进来，子文件夹也算。'
         + '**照片不会被移动、改名，或修改任何内容。**',
        ref: 'open',
      },
      {
        screen: 'home',
        t: '打开过的会留在这里',
        b: '下次点一下就直接回来 —— 而且会回到你上次看到的那张照片。',
        ref: 'recent',
      },

      {
        screen: 'proj',
        t: '进项目以后：左边是全部照片',
        b: '绿勾＝留着，红叉＝不要，金色星＝精选。编号是它在这个列表里的位置。',
        ref: 'list',
      },
      {
        screen: 'proj',
        t: '右边是当前这一张',
        b: '下面一行小字是拍摄参数。软件检测到问题时会在这里列出来，'
         + '比如模糊、过曝、视线没看镜头。',
        ref: 'stage',
      },
      {
        screen: 'proj',
        t: '按 → 表示「要」',
        b: '卡片往右飞走，你就是留了它。按住不放可以先看效果，松手才算数 ——'
         + '手滑不会误判。',
        ref: 'keep',
      },
      {
        screen: 'proj',
        t: '按 ← 表示「不要」',
        b: '这只是标记，**不会删任何东西**。所有「不要」的照片在最后确认之前，'
         + '一直待在原来的位置。',
        ref: 'reject',
      },
      {
        screen: 'proj',
        t: '按 空格 表示「精选」',
        b: '在「要」之外再加一层：我要它，而且它是这批里最好的。再按一次取消。',
        ref: 'mark',
      },
      {
        screen: 'proj',
        t: '按 ↑ ↓ 只是翻看',
        b: '上下翻动不改任何状态 —— 拿不准的时候可以先往后看看再决定。'
         + '按错了按 ⌫ 撤销上一步。',
        ref: 'undo',
      },
      {
        screen: 'proj',
        t: '筛一下，只处理关心的',
        b: '「有明显问题」只看有问题的；「连拍 / 相似组」按相似度分组，'
         + '一组里通常留一张就够了。',
        ref: 'chips',
      },
      {
        screen: 'proj',
        t: '最后点这里归档',
        b: '把照片按决定分进三个文件夹：要 / 不过 / 精选。'
         + '**没审过的留在原地**。会先让你确认，再动手；分完还能撤回。',
        ref: 'apply',
      },
      {
        screen: 'proj',
        t: '就这样',
        b: '上面这些只是演示，一张照片都不会动。'
         + '随时可以在设置里重看。接下来，打开你自己的文件夹试试。',
        ref: null,
      },
    ];
  }

  function showScreen(name) {
    $('#tourStage').innerHTML = name === 'home' ? MOCK_HOME : MOCK_PROJ;
  }

  function boxOf(ref) {
    if (!ref) return null;
    const el = $('#tourStage').querySelector(`[data-ref="${ref}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }

  function render() {
    const s = steps[step];
    const pad = 8;
    const b = boxOf(s.ref);
    const spot = $('#tourSpot');
    const card = $('#tourCard');

    if ($('#tourStage').dataset.screen !== s.screen) {
      showScreen(s.screen);
      $('#tourStage').dataset.screen = s.screen;
    }

    if (b) {
      spot.style.display = 'block';
      spot.style.left = (b.x - pad) + 'px';
      spot.style.top = (b.y - pad) + 'px';
      spot.style.width = (b.w + pad * 2) + 'px';
      spot.style.height = (b.h + pad * 2) + 'px';
    } else {
      spot.style.display = 'none';
    }
    $('#tour').classList.toggle('dim', !b);

    $('#tourStepNo').textContent = `${step + 1} / ${steps.length}`;
    $('#tourTitle').textContent = s.t;
    $('#tourBody').innerHTML = esc(s.b).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    $('#tourPrev').disabled = step === 0;
    $('#tourNext').textContent = step === steps.length - 1 ? '开始用' : '下一步';

    if (b) {
      // Placement order matters: to the side first, then below, then above.
      //
      // A card placed below a tall target (the photo list is most of the screen
      // height) has nowhere to go, so it gets pushed up and lands on top of the
      // very thing it is pointing at. Beside it is always free here, because the
      // app is a two-column layout.
      const gap = 14;
      const h = card.offsetHeight || 190;
      const w = card.offsetWidth || 352;
      const canRight = b.x + b.w + pad + gap + w < window.innerWidth - 12;
      const canLeft = b.x - pad - gap - w > 12;
      const below = b.y + b.h + pad + gap;
      const above = b.y - pad - gap - h;
      const canBelow = below + h < window.innerHeight - 12;
      const canAbove = above > 12;

      if (canRight) {
        card.style.left = (b.x + b.w + pad + gap) + 'px';
        card.style.top = Math.max(12, Math.min(b.y, window.innerHeight - h - 12)) + 'px';
      } else if (canLeft) {
        card.style.left = (b.x - pad - gap - w) + 'px';
        card.style.top = Math.max(12, Math.min(b.y, window.innerHeight - h - 12)) + 'px';
      } else if (canBelow) {
        card.style.left = Math.max(12, Math.min(b.x, window.innerWidth - w - 12)) + 'px';
        card.style.top = below + 'px';
      } else if (canAbove) {
        card.style.left = Math.max(12, Math.min(b.x, window.innerWidth - w - 12)) + 'px';
        card.style.top = above + 'px';
      } else {
        card.style.left = Math.max(12, (window.innerWidth - w) / 2) + 'px';
        card.style.top = '50%';
        card.style.transform = 'translateY(-50%)';
        return;
      }
      card.style.transform = 'none';
    } else {
      card.style.top = '50%';
      card.style.left = '50%';
      card.style.transform = 'translate(-50%, -50%)';
    }
  }

  function goto(n) {
    step = Math.max(0, Math.min(steps.length - 1, n));
    render();
  }

  function open() {
    steps = buildSteps();
    $('#tourStage').dataset.screen = '';
    $('#tour').classList.remove('hidden');
    const want = parseInt((location.hash.match(/^#tour-(\d+)/) || [])[1] || '1', 10);
    goto(want - 1);
  }

  function close(markSeen = true) {
    $('#tour').classList.add('hidden');
    $('#tour').classList.remove('dim');
    if (markSeen) { try { localStorage.setItem(SEEN_KEY, '1'); } catch (e) {} }
  }

  function seen() {
    try { return localStorage.getItem(SEEN_KEY) === '1'; } catch (e) { return true; }
  }

  function bind() {
    $('#tourNext').onclick = () => {
      if (step >= steps.length - 1) close();
      else goto(step + 1);
    };
    $('#tourPrev').onclick = () => goto(step - 1);
    $('#tourSkip').onclick = () => close();
    $('#tour').onclick = (e) => {
      if (e.target.id === 'tour' || e.target.id === 'tourSpot') {
        if (step >= steps.length - 1) close();
        else goto(step + 1);
      }
    };
    window.addEventListener('resize', () => {
      if (!$('#tour').classList.contains('hidden')) render();
    });
  }

  return { open, close, bind, seen, isOpen: () => !$('#tour').classList.contains('hidden') };
})();

export { Tour };
