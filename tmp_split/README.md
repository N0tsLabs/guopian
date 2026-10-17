# tmp_split/ — 这次拆分的工具与原件（不是产品代码，随时可删）

`web/*.js` 被拆成 11 个 ES module 的那次重构留下的东西。**前提是没有 git**，
所以这里保存着拆分前的原件 —— 确认新版本没问题之后，整个目录可以删掉。

## 原件（拆分前，一字未动）

| 文件 | 说明 |
|---|---|
| `app.js.orig` | 1760 行，单个 IIFE，70 个顶层函数 |
| `core.js.orig` | 62 行，挂 `window.G` / `window.Views` |
| `home.js.orig` | 460 行，末尾直接 `Home.boot()`（启动竞态的来源） |
| `index.html.orig` | 三个普通 `<script src>` |
| `web_smoke.js.orig` | 拍平式加载的前端冒烟测试 |
| `hygiene.py.orig` | 拆分前的封装守卫（第 4 组只查"文件头有没有声明依赖"） |
| `web_check.py.orig` | 只读 `app.js + home.js` 的 id 交叉检查 |

## 工具

| 文件 | 说明 |
|---|---|
| `split.py` | **怎么切的**：按行号把 `app.js.orig` 切成各模块，并断言"原文件每一行非空行都恰好落进一个模块"。所有模块正文都是逐行拷贝的，没有一个字符是重新打的 |
| `verify_fidelity.py` | 切完之后复核：原件里除了有意修改的 4 行，其余非空行都还能在模块里找到 |
| `check_imports.py` | 有没有 import 了却没用的名字；文件头 `@requires` 和实际 import 是否一致 |
| `esm_link.mjs` | 用 Node **真正的 ESM** 把 10 个模块链接一遍（`home.js` 会调 `boot()`，需要 DOM，跳过）。重复 export、import 名字写错、路径不通都会在这里报错 —— 这些是正则查不出来的 |
| `map.py` | 列出某个 JS 文件里所有顶层声明和它们的行号（拆分前用它建立行号地图） |
| `graph.py` | 打印每个顶层函数引用了哪些其它顶层名字（用来确认没有环，以及谁需要注入） |

```bash
python tmp_split/split.py              # 会覆盖 web/*.js，只在重做这次拆分时用
python tmp_split/verify_fidelity.py
python tmp_split/check_imports.py
node   tmp_split/esm_link.mjs
```
