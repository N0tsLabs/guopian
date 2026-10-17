# 过片 Guopian

本地照片筛选工具：一张一张地过，只留好的。
Local, offline photo culling. Nothing is ever uploaded, nothing is ever deleted.

## 快速开始

```bash
cd ..
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
python scripts/fetch_models.py
python run.py "D:\你的照片文件夹" --read-only
```

## 这里的脚本

| 脚本 | 用途 |
|---|---|
| `make_testset.py` | 生成一套合成测试照片（每类缺陷各一张），用来快速确认流程没坏 |
| `run_report.py` | 跑完整流程并打印一张表：每张照片的指标、问题、建议 |
| `bench.py` | 性能基准：单张各阶段耗时 + 不同线程数的吞吐 |
| `api_test.py` | 打真实 HTTP 接口，验证首页 / 目录浏览 / 打开库 / 决策 / 只读保护 |
| `list_test.py` | 逐个筛选检查左侧列表拿到什么（复现"全选完后列表变空"那类问题） |
| `web_smoke.js` | **不需要浏览器**：用 Node 搭 DOM 桩，喂真实 API 数据把前端模块跑一遍，抓白屏类 bug。它自己解析 `import`/`export`，按 import 图的顺序逐模块加载（每个模块一个作用域，不拍平） |
| `web_check.py` | **不需要浏览器**：交叉检查 JS 引用的 id 是否都在 HTML、切换的 class 是否都有 CSS |
| `hygiene.py` | **不需要浏览器、不需要服务器**：封装守卫。见下 |
| `bridge.py` | 通过 Kimi WebBridge 驱动**真实浏览器**：导航、截图、执行 JS、读页面 |
| `shot.py` | **不需要你的浏览器、也不需要 bridge**：无头 Edge/Chrome 自动重拍 README 截图（首页 + 卡片视图） |
| `layout_audit.js` | 配合 `bridge.py` 用：把界面的真实尺寸量出来（行高、面板宽、溢出） |
| `anim_check.py` | 核验三种决策动效：选择器是否匹配、关键帧是否在、**JS 等待时长是否 ≥ 动画时长** |
| `zoom_sharpness.py` | 比对放大后的画面与磁盘原文件的逐像素差（MAD + 对齐搜索） |

```bash
python evaluation/make_testset.py
python evaluation/run_report.py evaluation/testset
python evaluation/bench.py "D:\照片文件夹" 10 1 4 8
python evaluation/hygiene.py                   # 封装守卫，最快，先跑它
python evaluation/api_test.py http://127.0.0.1:8765
python evaluation/list_test.py http://127.0.0.1:8765
python evaluation/zoom_sharpness.py 1 5        # 放大后是否逐像素等于原图
python evaluation/anim_check.py                # 三种退出动效是否真的在跑
node   evaluation/web_smoke.js
python evaluation/web_check.py
```

## hygiene.py：守着两条已经破过的规矩

它检查的五组东西，**每一条都是这个项目真的犯过的错**：

| | 守什么 | 犯过的样子 |
|---|---|---|
| 1 | 决策用词只能写在 `config.py` | 同一组词出现在四处（config / JS / index.html ×2）。改一处不报错，只是屏幕上出现两个词 |
| 2 | 颜色只能写在 `:root` | 17 处 `#hex` 散落各处，换配色要全文件搜索 |
| 3 | 前端零依赖、无构建步骤、只有一个模块入口 | —— |
| 4 | 依赖只能写在 `import` 段里 | 共享工具曾埋在 `home.js` 里，`app.js` 依赖一个跟自己无关的文件；三个 `<script>` 的加载顺序只写在注释里，而 `home.js` 末尾的 `Home.boot()` 会在 `app.js` 还没解析完时去调 `App.setLabels()` —— 能跑只是因为网络往返比解析慢 |
| 5 | 只有一个 `.btn` 基类 | 又写了一个 `.btn`（`34px`/`.pri`），而项目本来就有（`30px`/`.primary`）。CSS 不报错，后定义的静默生效 |

第 4 组现在查的是整个 `web/` 目录：每个 `import` 的路径存在吗、import 的名字
对方真的有 `export` 吗、依赖图有环吗、每个 `.js` 都是模块吗（没人挂 `window`）、
以及**跨模块用到的名字是不是都 import 了**（漏一个 import，浏览器直接
ReferenceError，而扁平化的冒烟测试反倒可能碰巧跑通）。

**为什么值得单独写一个脚本**：这五条**破坏了都不会报错**。它们不会让测试变红，
只会让界面上的词对不上、让换配色变成搜索、让依赖关系靠考古。
**不被检查的规矩一定会漂移** —— 第 4 条在加上守卫的当轮就被守卫抓到了，
犯规的是写守卫的人自己。

> 有一条**故意不查**：决策词出现在中文句子里（「这张我要」「不需要」）。
> 正则分不清标签和散文，一个天天误报的检查一周内就会被关掉，比没有更糟。
> 所以只查**能可靠判断的形状**：`>要<`、`标为要`、JS 字面量。

> `anim_check.py` 的**静态部分**任何时候都能跑；**实机部分**需要标签页在前台 ——
> Chromium 会冻结后台标签页的动画时间轴（`getAnimations()` 返回空、
> `document.timeline.currentTime` 恒为 0），所以隐藏标签页里量任何 CSS 过渡
> 都只会读到起始值。同一个坑也会让 `bridge.py` 的截图看起来"卡住不动"。
>
> 还有两条：**应用视图没打开时元素没有盒子**，浏览器根本不解析 `animation`；
> 而 `--dev` 模式下改了 `web/` 或 `guopian/` 里的文件，页面会在 600ms 内**自动重载**
> 并退回首页（`_dev_token()` 只监视这两个目录）。所以**先改完文件，再打开库验收**，
> 否则会一路看到"动画名是空的"。

## 端到端测试：不靠 bridge，也不靠人手

`web/_e2e.html` 是一个**测试页**（不是应用的一部分）。它：

1. `fetch('/')` 拿到 `index.html`，把 `<body>` **注入自己**（script 标签会被剥掉，
   因为 `innerHTML` 不执行脚本）—— 这样真实的应用 DOM 就位了
2. `await import('/home.js')` 手工启动应用
3. **派发真实的 `KeyboardEvent`**（比如 `i`）
4. 读 `#overlay` 的 `children` / `querySelectorAll('rect').length`，把结果打印在页面上

然后用无头浏览器截图就行：

```bash
python evaluation/shot.py        # 但把 URL 换成 http://127.0.0.1:8765/_e2e.html
```

**为什么值得留**：读代码在这里连续给出了好几次自信的错误答案。
真正终结争论的，是**在一个真实浏览器里按下真实的键，然后数矩形**。

它不依赖 Kimi WebBridge、不占用用户的标签页、可以在无人值守下重复跑。

## bridge 只驱动本机页面

浏览器扩展作用于**当前活动标签页**。你一旦切到别的标签页，之后每一次 `eval`、
截图、按键都会落到**你的页面上** —— 曾经因此把 `location.reload()` 发到了一个
已登录的站点。所以 `bridge.py` 在动手前先读一次 `location.href`，主机名不在
`127.0.0.1 / localhost / ::1` 里就直接拒绝并提示你重开：

```bash
python evaluation/bridge.py go http://127.0.0.1:8765/    # 先挂到自己的页面
```

## 用真实浏览器验收界面

`web_smoke.js` 只能证明 JS 不崩，**证明不了好看**。排版要用真浏览器看：

```bash
# 1) 起开发服务器
python run.py --dev

# 2) 用 Kimi WebBridge 打开并截图
python evaluation/bridge.py go http://127.0.0.1:8765/
python evaluation/bridge.py shot          # 打印 PNG 路径，然后用 Read 工具看图
python evaluation/bridge.py eval-file evaluation/layout_audit.js   # 量出真实尺寸
python evaluation/bridge.py close         # 用完关掉自己开的标签页
```

`layout_audit.js` 会输出每个关键元素的**实测宽高**，这样"行高 47px 太松散"
或者"声明 272px 实测 322px"这类问题能被直接看见，而不是靠猜。

> ⚠️ 沙箱里跑不了 Chromium（它需要命名管道做 IPC），所以在受限环境里
> `web_smoke.js` + `web_check.py` 是唯一的自动化保险，排版只能靠
> `bridge.py` 驱动用户自己的浏览器来看。

## ⚠️ 这个目录最重要的事

**合成测试照片只能证明代码没崩，证明不了准确率。**

上面那些合成图（模糊的、过曝的、旋转的）都是极端情况，任何算法都能判对。
真实照片不一样：侧脸、墨镜、逆光、玻璃反光、运动模糊、镜头虚化、
黄昏的暗部、雪地的高光 —— 这些才是误报的来源。

所以真正需要你做的是：

1. 拿**你自己的** 500–2000 张照片跑一遍 `run_report.py`
2. 对着输出，人工数一下：
   - 被判"闭眼"的里，真正闭眼的有几张？（假阳性率）
   - 被判"模糊"的里，真正糊的有几张？
   - 该被判出来但漏掉的有几张？（假阴性率）
3. 把结果发到 Issue

**这些数字决定每个功能的阈值该定在哪，也决定哪些功能值得留。**
如果闭眼检测的假阳性超过 10%，它就应该从"自动移除"降级成"提示"。

## 建议的评估集

```
evaluation/
  mytestset/            ← 你自己的照片（不要提交到 git）
  labels.csv            ← 人工标注
```

`labels.csv` 建议长这样：

```csv
file,decision,issues,note
DSC09871.JPG,keep,,光线很好
DSC09882.JPG,reject,blurry,跑动时拍的，确实糊了
DSC09926.JPG,keep,eye_maybe_closed,其实没闭眼，是太阳下眯眼 → 误报
```

有了这个标注集，之后每次改阈值都能回归验证，而不是凭感觉调。
