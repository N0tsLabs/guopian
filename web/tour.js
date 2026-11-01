/* 过片 Guopian — 新手教程。
 *
 * @requires web/core.js    G ( $ esc api toast ) and Views
 * @requires web/state.js   S
 * @requires web/app.js     enter() —— 演示库建好以后要用同一条入口进项目
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
 * ══════════════════════════ 两幕 ══════════════════════════
 *
 * 教程是一段**连续**的流程，不是"首页看几条、然后自己想办法"：
 *
 *   第一幕  首页：这是什么、怎么打开一个文件夹、最近打开在哪
 *   幕间    点「下一步」时，服务端现场画 12 张临时照片，打开成一个演示库，
 *           整页进度条跑完自动进项目 —— 不需要用户去点任何按钮
 *   第二幕  项目：左边列表、右边大图、按键、多选、筛选、归档
 *   收尾    "这些照片是临时造的" → 点「开始用」→ 删掉演示库 → 回首页
 *
 * 于是**整个教程里看到的照片都是演示数据**，只存在于这次教程期间；教程一结束
 * 就整个删除，首页回到干净状态（「最近打开」里不会有它）。
 *
 * 两种入口：
 *   Tour.start()                    从首页开始，带演示库（首次运行 / 「先看看它怎么用」）
 *   Tour.open({ hasLibrary: true }) 已经在项目里时，只讲项目那几屏（设置里重看）
 */

import { G, Views, setLibSlug } from './core.js';
import { S } from './state.js';
import { enter } from './app.js';

const Tour = (() => {
  const { $, esc, api, toast } = G;

  const SEEN_KEY = 'guopian.tour.v1';
  let step = 0;
  let steps = [];
  // 这一趟教程是不是要自带一个演示库；以及它到底建出来没有。
  // 两者分开：用户可能在第一幕就按了跳过，那时什么都还没建，也就没什么可删。
  let demoMode = false;
  let demoReady = false;
  let onDemoEnd = () => {};

  const home = () => Views.show('homeView');
  const proj = () => Views.show('appView');

  let hasLib = false;

  function libraryOpen() {
    return hasLib || !!(S.state && S.state.root);
  }

  /* ─────────────────────────── 第一幕：首页 ─────────────────────────── */

  function homeSteps() {
    return [
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
        b: '下次点一下就直接回来，还会回到你上次看到的那张。'
         + '第一次用这里是空的，没关系 —— 下一步就用一批临时照片试一遍。',
        sel: '#recentList',
      },
    ];
  }

  /* ─────────────────────────── 第二幕：项目 ─────────────────────────── */

  function projectSteps() {
    return [
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
         + '比如模糊、过曝、噪点偏高。这一批里故意做过曝、欠曝、失焦、'
         + '噪点、偏蓝、偏黄各一张，还有一组连拍里两张一模一样。',
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
    ];
  }

  /* ─────────────────────────── 组装 ─────────────────────────── */

  function buildSteps() {
    // 演示库建在幕间，所以第一幕开始时"项目"一定还没打开。
    const inProject = demoMode ? false : libraryOpen();
    const base = homeSteps();

    if (demoMode) {
      return base.concat([
        {
          view: 'home',
          t: '先拿一批临时照片试一遍',
          // 这一步没有高亮目标：卡片居中，点「下一步」才真正开始造照片。
          b: '接下来会打开一个装了 12 张照片的临时项目（过曝、欠曝、失焦、噪点、偏色、'
           + '连拍重复各一张），用它把整套流程走一遍。**这些照片只存在于这次教程里，'
           + '结束就删掉。**',
          sel: null,
        },
        // 第一步进项目，进场前先把这个演示库建出来。
        Object.assign({}, projectSteps()[0], { act: 'demo' }),
        ...projectSteps().slice(1),
        {
          view: 'app',
          t: '这些照片是临时造的',
          b: '它们放在系统临时目录，**结束教程就整个删掉** ——'
           + '不会出现在「最近打开」里，也没有碰你自己的任何一张照片。'
           + '点「开始用」就回首页，从你自己的文件夹开始。',
          sel: '#backHome',
        },
      ]);
    }

    if (!inProject) {
      return base.concat([{
        view: 'home',
        t: '就这些',
        b: '先打开一个文件夹，剩下的过片会带着你走。'
         + '**随时可以在设置里重看这个教程。**',
        sel: '#openSettings',
      }]);
    }

    return base.concat(projectSteps(), [{
      view: 'app',
      t: '就这些',
      b: '随时可以在设置里重看这个教程。',
      sel: '#btnSettings',
    }]);
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

  /** 幕间：把演示库建出来，再走统一入口进项目。
   *
   * 这一步要几秒（现场画 12 张 2400px 的照片），所以教程先藏起来、让整页
   * 进度条自己说话 —— 卡片盖在进度条上只会让人以为卡住了。 */
  async function enterDemo() {
    $('#tour').classList.add('hidden');
    toast('正在准备演示照片…', '', 30000);
    let r;
    try {
      r = await api('/api/demo', { method: 'POST', body: '{}' });
    } catch (e) {
      toast('无法准备演示照片：' + ((e.body && e.body.error) || e.message || ''), 'err', 6000);
      $('#tour').classList.remove('hidden');
      return false;
    }
    if (!r || !r.ok) {
      toast((r && r.error) || '无法准备演示照片', 'err', 6000);
      $('#tour').classList.remove('hidden');
      return false;
    }
    // 图片地址要先知道是哪个库，否则第一张缩略图会去拿上一个库的缓存。
    setLibSlug(r.slug);
    demoReady = true;
    try {
      await enter();            // 新库会先过整页进度，分析完自动进过图
    } catch (e) {
      /* enter 自己会处理错误并回首页 */
    }
    // 那句“正在准备”到此为止 —— 它的寿命是按最坏情况给的 30 秒。
    const t = $('#toast');
    if (t) t.classList.add('hidden');
    $('#tour').classList.remove('hidden');
    return true;
  }

  async function goto(n) {
    step = Math.max(0, Math.min(steps.length - 1, n));
    const s = steps[step];
    if (s.act === 'demo' && !demoReady) {
      const ok = await enterDemo();
      if (!ok) { close(false); return; }   // 造不出来就别把教程卡在半空
    }
    // 先切到这一屏，再量它 —— 隐藏的页量出来是 0×0
    if (s.view === 'home') home(); else proj();
    // 让浏览器排完版再量；requestAnimationFrame 在后台标签页会被节流，
    // 所以两边都来一次。后面的两次是给异步渲染留的：进项目那一步要等
    // loadQueue 把列表画出来，否则 #listScroll 还是空的，高亮只能居中。
    requestAnimationFrame(() => requestAnimationFrame(render));
    setTimeout(render, 60);
    setTimeout(render, 320);
    setTimeout(render, 900);
  }

  /** 完整教程：首页 → 演示项目 → 删掉演示、回首页。 */
  function start() {
    open({ demo: true, hasLibrary: false });
  }

  function open(opts) {
    try { localStorage.setItem(SEEN_KEY, '1'); } catch (e) {}
    demoMode = !!(opts && opts.demo);
    demoReady = false;
    // 教程期间不弹「三件事，两个方向」那个引导层（见 state.js 的说明）。
    S.suppressCoach = true;
    // 能不能讲项目里那几步，取决于「此刻有没有打开项目」。
    // 从首页进来时 S.state 可能还没加载完 —— 那会被误判成没开项目，
    // 于是只讲 4 步。所以允许调用方直接告诉答案。
    hasLib = opts && typeof opts.hasLibrary === 'boolean' ? opts.hasLibrary : libraryOpen();
    steps = buildSteps();
    $('#tour').classList.remove('hidden');
    const want = parseInt((location.hash.match(/^#tour-(\d+)/) || [])[1] || '1', 10);
    goto(want - 1);
  }

  async function close(markSeen = true) {
    $('#tour').classList.add('hidden');
    $('#tour').classList.remove('dim');
    S.suppressCoach = false;
    if (markSeen) { try { localStorage.setItem(SEEN_KEY, '1'); } catch (e) {} }
    if (!demoMode) return;
    demoMode = false;
    if (!demoReady) { onDemoEnd(); return; }   // 第一幕就跳过：没有东西需要删
    demoReady = false;
    // 演示到此为止：删掉临时库、回首页。删文件是服务端的事，这里只管界面。
    try { await api('/api/demo/end', { method: 'POST', body: '{}' }); } catch (e) { /* 已关 */ }
    onDemoEnd();
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

  /** 演示库结束时由 home.js 注入：回首页、刷新项目列表。 */
  function configure(hooks) {
    if (hooks && typeof hooks.onDemoEnd === 'function') onDemoEnd = hooks.onDemoEnd;
  }

  return { open, close, bind, seen, start, configure,
           isOpen: () => !$('#tour').classList.contains('hidden') };
})();

export { Tour };
