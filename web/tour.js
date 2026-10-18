/* 过片 Guopian — 新手引导。
 *
 * @requires web/core.js    G ( $ $$ esc )
 * @requires web/state.js   S
 * @requires web/index.html #tour / #tourSpot / #tourCard 这层壳
 *
 * 教程指的**就是真实界面上的元素**，不画一套假的。
 *
 * 上一版是这么做的：教程里自己搭一个"看起来像项目"的假界面，步骤去指假的
 * 按钮。结果项目一改版，教程就和本体对不上了 —— 用户看到的按钮在左下角，
 * 真实项目里却在中间。写两套 UI，必然越差越远。
 *
 * 现在改成：高亮真实元素、把其余部分压暗。界面怎么变，教程自动跟着变，
 * 因为它指的就是那些元素本身。
 *
 * 两种状态：
 *   - 没打开项目时，只讲首页那三步（打开文件夹 / 最近项目），然后收尾
 *   - 已经打开项目时，接着讲项目里的那几屏
 * 没有项目却硬讲"点击卡片"这种步骤，只会让人对着不存在的按钮发呆。
 */

import { G, Views } from './core.js';
import { S } from './state.js';

const Tour = (() => {
  const { $, esc } = G;

  const SEEN_KEY = 'guopian.tour.v1';
  let step = 0;
  let steps = [];

  const home = () => Views.show('homeView');
  const proj = () => Views.show('appView');

  let hasLib = false;

  function libraryOpen() {
    return hasLib || !!(S.state && S.state.root);
  }

  function buildSteps() {
    const inProject = libraryOpen();

    const homeSteps = [
      {
        view: 'home',
        t: '这是过片',
        b: '只在你电脑上跑的照片筛选工具，不联网、不上传。'
         + '几千张照片不用一张张打开 —— 它把照片一张张推到你面前，'
         + '你只需要说「要」还是「不要」。',
        sel: null,
      },
      {
        view: 'home',
        t: '第一步：打开一个文件夹',
        b: '点这里选一个装着照片的文件夹。整个文件夹会被一起读进来，子文件夹也算。'
         + '**照片不会被移动、改名，或修改任何内容。**',
        sel: '#btnOpen',
      },
      {
        view: 'home',
        t: '打开过的会留在这里',
        b: '下次点一下就直接回来 —— 而且会回到你上次看到的那张照片。',
        sel: '#recentList',
      },
    ];

    if (!inProject) {
      return homeSteps.concat([{
        view: 'home',
        t: '就这些',
        b: '先打开一个文件夹，剩下的过片会带着你走。'
         + '**随时可以在设置里重看这个教程。**',
        sel: '#openSettings',
      }]);
    }

    return homeSteps.concat([
      {
        view: 'app',
        t: '左边是全部照片',
        b: '绿勾＝留着，红叉＝不过，金色星＝精选。编号是它在这个列表里的位置。',
        sel: '#listScroll',
      },
      {
        view: 'app',
        t: '右边是当前这一张',
        b: '下面那行是拍摄参数。检测到问题时会在这里列出来 ——'
         + '比如模糊、过曝、视线没看镜头。',
        sel: '#photoStage',
      },
      {
        view: 'app',
        t: '一张一张过',
        b: '**→ 要，← 不过，空格 精选。** 按住先预览、松手才生效；'
         + '拿不准就用 ↑ ↓ 往后翻。',
        sel: '.acts',
      },
      {
        view: 'app',
        t: '可以一组一起决定',
        b: '按住 Ctrl 点几张，右边会并排摊开。'
         + '**点图片是放大看，鼠标移上去点「留下」或「精选」；没点过的一律不过。**',
        sel: '#listScroll',
      },
      {
        view: 'app',
        t: '筛一下，只处理关心的',
        b: '「有明显问题」只看有问题的；「连拍 / 相似组」按相似度分组，'
         + '一组里通常留一张就够了。',
        sel: '#triageChips',
      },
      {
        view: 'app',
        t: '最后点这里归档',
        b: '把照片分进三个文件夹。**没审过的留在原地。** 会先让你确认，分完还能撤回。',
        sel: '#btnApply',
      },
      {
        view: 'app',
        t: '就这些',
        b: '随时可以在设置里重看这个教程。',
        sel: '#btnSettings',
      },
    ]);
  }

  /** 目标在不在、有没有尺寸。隐藏或没渲染出来的元素不能指。 */
  function boxOf(sel) {
    if (!sel) return null;
    const el = $(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    return { x: r.left, y: r.top, w: r.width, h: r.height, el };
  }

  function render() {
    const s = steps[step];
    const pad = 8;
    const box = boxOf(s.sel);
    const spot = $('#tourSpot');
    const card = $('#tourCard');

    // 挖洞：一个元素的巨大 box-shadow 把外面全压暗，比四块遮罩简单得多
    if (box) {
      spot.style.display = 'block';
      spot.style.left = (box.x - pad) + 'px';
      spot.style.top = (box.y - pad) + 'px';
      spot.style.width = (box.w + pad * 2) + 'px';
      spot.style.height = (box.h + pad * 2) + 'px';
      spot.style.borderRadius = '10px';
    } else {
      spot.style.display = 'none';
    }
    $('#tour').classList.toggle('dim', !box);

    $('#tourStepNo').textContent = `${step + 1} / ${steps.length}`;
    $('#tourTitle').textContent = s.t;
    $('#tourBody').innerHTML = esc(s.b).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    $('#tourPrev').disabled = step === 0;
    $('#tourNext').textContent = step === steps.length - 1 ? '开始用' : '下一步';

    if (box) {
      const gap = 14;
      const h = card.offsetHeight || 190;
      const w = card.offsetWidth || 352;
      const canRight = box.x + box.w + pad + gap + w < window.innerWidth - 12;
      const canLeft = box.x - pad - gap - w > 12;
      const below = box.y + box.h + pad + gap;
      const above = box.y - pad - gap - h;

      if (canRight) {
        card.style.left = (box.x + box.w + pad + gap) + 'px';
        card.style.top = Math.max(12, Math.min(box.y, window.innerHeight - h - 12)) + 'px';
      } else if (canLeft) {
        card.style.left = (box.x - pad - gap - w) + 'px';
        card.style.top = Math.max(12, Math.min(box.y, window.innerHeight - h - 12)) + 'px';
      } else if (below + h < window.innerHeight - 12) {
        card.style.left = Math.max(12, Math.min(box.x, window.innerWidth - w - 12)) + 'px';
        card.style.top = below + 'px';
      } else {
        card.style.left = Math.max(12, Math.min(box.x, window.innerWidth - w - 12)) + 'px';
        card.style.top = Math.max(12, above) + 'px';
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
    const s = steps[step];
    // 先切到这一屏，再量它 —— 隐藏的页量出来是 0×0
    if (s.view === 'home') home(); else proj();
    // 让浏览器排完版再量；requestAnimationFrame 在后台标签页会被节流，
    // 所以两边都来一次
    requestAnimationFrame(() => requestAnimationFrame(render));
    setTimeout(render, 60);
  }

  function open(opts) {
    try { localStorage.setItem(SEEN_KEY, '1'); } catch (e) {}
    // 能不能讲项目里那几步，取决于「此刻有没有打开项目」。
    // 从首页进来时 S.state 可能还没加载完 —— 那会被误判成没开项目，
    // 于是只讲 4 步。所以允许调用方直接告诉答案。
    hasLib = opts && typeof opts.hasLibrary === 'boolean' ? opts.hasLibrary : libraryOpen();
    steps = buildSteps();
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
    // 窗口变了、列表滚了，高亮位置就不对了 —— 重新量
    window.addEventListener('resize', () => {
      if (!$('#tour').classList.contains('hidden')) render();
    });
    window.addEventListener('scroll', () => {
      if (!$('#tour').classList.contains('hidden')) render();
    }, true);
  }

  return { open, close, bind, seen, isOpen: () => !$('#tour').classList.contains('hidden') };
})();

export { Tour };
