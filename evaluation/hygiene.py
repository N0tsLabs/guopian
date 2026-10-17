#!/usr/bin/env python3
"""Encapsulation guards.

These are the rules that this project has already broken once, in ways that
produced NO error and were only noticed by looking at the screen:

  1. Decision wording was written down in four places (config.py, app.js, and
     twice in index.html). Renaming one of them left the others behind.
  2. Colours were written as literals in seventeen places outside :root, so
     changing the palette meant hunting for hex codes.
  3. The frontend grew a build step's worth of implicit ordering: three plain
     <script> tags whose order was written down in a comment. The load order is
     now an import graph, and it is checked here instead of being trusted.

A rule that is not checked is a rule that will drift. Run this with the other
evaluation scripts; it needs no server, no browser, and no node.

    python evaluation/hygiene.py
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

# The canonical words live in config.py only. If a rename happens, these are
# whatever config says -- the check is that nothing ELSE spells them out.
sys.path.insert(0, ROOT)

fails: list[str] = []
notes: list[str] = []


def check(ok: bool, msg: str, detail: str = "") -> None:
    print("  [{}] {}".format("OK  " if ok else "FAIL", msg) + ("  " + detail if detail else ""))
    if not ok:
        fails.append(msg)


def read(rel: str) -> str:
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ─────────────────────────── JS 静态扫描 ───────────────────────────
#
# 只是为了回答"这个模块用到的名字，是不是它自己声明的、或者 import 进来的"。
# 不需要一个完整的解析器，但必须先把注释、字符串、正则、以及模板字符串里的
# 代码片段处理干净 —— 否则 template literal 里的 `${esc(x)}` 会被当成字符串
# 丢掉（漏报），而正则里的引号会把后面的代码整段吞掉（误报）。后者的教训很
# 直接：一个会乱报的检查，一周之内就会被关掉，那还不如没有。

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")

# 浏览器/JS 内建。列在这里的当作"本来就是全局的"，不算跨模块依赖。
BUILTINS = set("""
Object Array String Number Boolean Math JSON Date RegExp Error TypeError RangeError
Symbol Map Set WeakMap WeakSet Promise Proxy Reflect Intl BigInt
parseInt parseFloat isNaN isFinite encodeURIComponent decodeURIComponent
encodeURI decodeURI Infinity NaN undefined null true false this
window document globalThis self console navigator location localStorage
sessionStorage history screen performance fetch alert confirm prompt
setTimeout clearTimeout setInterval clearInterval queueMicrotask
requestAnimationFrame cancelAnimationFrame
Image File FileReader Blob URL FormData Headers Request Response AbortController
IntersectionObserver ResizeObserver MutationObserver Event CustomEvent
MouseEvent KeyboardEvent DragEvent WheelEvent
Element HTMLElement Node NodeList
if else for while do switch case default break continue return function
const let var class extends super new typeof instanceof in of void delete
try catch finally throw await async yield import export from as
""".split())


def strip_js(src: str) -> str:
    """Blank out comments and literals, but KEEP the code inside ${...}."""
    out, i, n = [], 0, len(src)
    prev = ""            # last significant character, for the regex heuristic
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i)
            i = n if j < 0 else j + 2
            out.append(" ")
            continue
        if c == "/" and prev not in ")]}" and not (prev.isalnum() or prev in "_$"):
            # a regex literal: /.../flags
            i += 1
            while i < n and src[i] != "/":
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == "[":
                    while i < n and src[i] != "]":
                        i += 2 if src[i] == "\\" else 1
                i += 1
            i += 1
            out.append(" ")
            continue
        if c in "'\"":
            q = c
            i += 1
            while i < n and src[i] != q:
                i += 2 if src[i] == "\\" else 1
            i += 1
            out.append(" ")
            continue
        if c == "`":
            i += 1
            while i < n and src[i] != "`":
                if src[i] == "\\":
                    i += 2
                elif src[i:i + 2] == "${":
                    depth, i = 1, i + 2
                    start = i
                    while i < n and depth:
                        if src[i] == "{":
                            depth += 1
                        elif src[i] == "}":
                            depth -= 1
                        elif src[i] in "'\"`":
                            qq = src[i]
                            i += 1
                            while i < n and src[i] != qq:
                                i += 2 if src[i] == "\\" else 1
                        i += 1
                    # 递归：${...} 里面还可能嵌着模板字符串，而它自己的 ${...}
                    # 又是代码。直接原样拼回去会把 "${" 留成两个 token，
                    # 其中一个就是假的自由变量 `$` —— 这条误报真的出现过。
                    out.append(" " + strip_js(src[start:i - 1]) + " ")
                else:
                    i += 1
            i += 1
            out.append(" ")
            continue
        out.append(c)
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


RE_IMPORT = re.compile(
    r"""import\s+(?:([\w$]+)\s*,\s*)?(?:\{([^}]*)\}|\*\s+as\s+([\w$]+)|([\w$]+))?\s*"""
    r"""from\s*['"]([^'"]+)['"]""")
RE_EXPORT = re.compile(r"export\s*\{([^}]*)\}")
# 顶层声明一律顶格（模块体没有闭包缩进），所以这里不加 \s* —— 缩进的
# const/let 都是函数内部的局部变量，把它们算成"模块的顶层名字"会让
# 下面的检查把局部变量当成跨模块引用，一天误报几十条。
RE_TOP = re.compile(
    r"^(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)"
    r"|^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"|^(?:export\s+)?(?:const|let|var)\s*\{([^}]*)\}", re.M)
# 任何位置的声明（含缩进的局部）—— 只用来"减掉"被引用的名字。
RE_ANY_DECL = re.compile(
    r"(?:function|class)\s+([A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s*\{([^}]*)\}")
RE_ARROW = re.compile(r"([A-Za-z_$][\w$]*)\s*=>")
RE_PARAMS = re.compile(r"(?:function\s*[\w$]*|catch)\s*\(([^()]*)\)")
RE_PAREN_ARROW = re.compile(r"\(([^()]*)\)\s*=>")
RE_PROP = re.compile(r"\.[A-Za-z_$][\w$]*")
RE_KEY = re.compile(r"([{,]\s*)[A-Za-z_$][\w$]*(\s*:)")


def names_of(blob: str) -> set:
    """Every declared binding in a snippet: `a, b: c, d = 1, ...rest`."""
    out = set()
    for part in blob.split(","):
        m = _IDENT.search(part)
        if m:
            out.add(m.group(0))
    return out


def strip_comments(src: str) -> str:
    """Blank out comments only. import 语句里的路径是字符串字面量，所以
    "找 import" 必须在保留字符串的文本上做 —— 否则会一条都匹配不到，
    而下面那些"路径存在 / 无环"的检查就全成了空转。"""
    out, i, n = [], 0, len(src)
    while i < n:
        if src[i] == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src[i] == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i)
            i = n if j < 0 else j + 2
            out.append(" ")
            continue
        out.append(src[i])
        i += 1
    return "".join(out)


def parse_module(src: str) -> dict:
    code = strip_js(src)
    raw = strip_comments(src)

    top = set()
    for m in RE_TOP.finditer(code):
        top |= names_of(next(g for g in m.groups() if g))

    imports, edges = [], []
    for m in RE_IMPORT.finditer(raw):
        default, braced, star, bare, target = m.groups()
        if target.startswith("."):
            edges.append(target)
        imported = set()
        if braced:
            imported |= names_of(braced)
        for one in (default, star, bare):
            if one:
                imported.add(one)
        imports.append((imported, target))

    exported, dup_export = set(), []
    for m in RE_EXPORT.finditer(code):
        for n in names_of(m.group(1)):
            if n in exported:
                dup_export.append(n)
            exported.add(n)
    for m in re.finditer(r"export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([\w$]+)",
                         code):
        if m.group(1) in exported:
            dup_export.append(m.group(1))
        exported.add(m.group(1))

    # 形参、局部声明：都会遮蔽同名顶层绑定，必须减掉，否则 el / c / x 这种
    # 常见短名字会天天误报。这个代码库里没有更花哨的参数模式，扫这几类就够。
    local = set()
    for m in RE_ANY_DECL.finditer(code):
        local |= names_of(next(g for g in m.groups() if g))
    for rx in (RE_PARAMS, RE_PAREN_ARROW):
        for m in rx.finditer(code):
            local |= names_of(m.group(1))
    for m in RE_ARROW.finditer(code):
        local.add(m.group(1))

    # 属性名永远不是自由变量。两种写法都要去掉：点号访问 `st.counts`，
    # 以及对象字面量的键 `{ holding: () => ... }` —— 后者漏掉的话，
    # configure({ holding }) 这种注入调用会被误报成"没 import holding"。
    code = RE_PROP.sub(" ", code)
    code = RE_KEY.sub(lambda m: m.group(1) + " " + m.group(2), code)
    used = set(_IDENT.findall(code))
    return {"code": code, "top": top, "local": local, "imports": imports,
            "exported": exported, "dup_export": dup_export, "used": used,
            "edges": edges}


def main() -> int:
    try:
        from guopian import config
        words = list(config.DECISION_LABELS.values())
    except Exception as exc:                                    # pragma: no cover
        print("  cannot import config: {}".format(exc))
        return 2

    html = read("web/index.html")
    appjs = read("web/app.js")
    css = read("web/style.css")

    print("\n== 1. 决策用词只有 config.py 一个真源 ==")

    # a) THE WORD STANDING ALONE IN ITS OWN ELEMENT, e.g. <b>要</b>, and the
    #    "标为要" buttons in the grid, where it is glued to a known prefix.
    #
    #    What is deliberately NOT checked: the word inside a sentence. "这张我要"
    #    and "我要，而且这是里面最好的" are prose -- 要 is doing its ordinary job
    #    as a verb, and "不需要" contains it by accident. A regex cannot tell a
    #    label from a sentence in Chinese, and a check that cries wolf on prose
    #    gets switched off within a week, which is worse than not having it.
    #    So this covers the shapes that ARE unambiguous, which is where the
    #    duplication actually happened.
    alt = "|".join(map(re.escape, words))
    bare = re.findall(r">\s*({})\s*<".format(alt), html)
    glued = re.findall(r"标为\s*({})\s*<".format(alt), html)
    check(not bare and not glued, "index.html 的决策词都走 data-label 占位符",
          "found {} {}".format(bare, glued) if (bare or glued)
          else "{} 处占位符".format(html.count("data-label=")))

    # b) no JS object literal spelling them out, e.g. keep: '要'. 决策词现在散在
    #    多个模块里，所以整份 web/*.js 都要扫，不能只看 app.js。
    alljs = "\n".join(read("web/" + f) for f in sorted(os.listdir(WEB)) if f.endswith(".js"))
    lit = re.findall(r"\b(?:keep|reject|mark)\s*:\s*'({})'".format(
        "|".join(map(re.escape, words))), alljs)
    check(not lit, "web/*.js 里没有决策词字面量", "found {}".format(lit) if lit else "")

    # c) the placeholders must all be keys the backend actually sends
    try:
        from guopian import config as c2
        keys = set(c2.DECISION_LABELS)
    except Exception:
        keys = set()
    ph = set(re.findall(r'data-label="(\w+)"', html))
    check(ph <= keys, "data-label 占位符都有对应的下发键",
          "{} -> {}".format(sorted(ph), sorted(keys)) if ph else "")

    print("\n== 2. 颜色只写在 :root 里 ==")

    # strip comments, then everything up to the end of the :root block
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    m = re.search(r":root\s*\{.*?\}", body, flags=re.S)
    outside = body[m.end():] if m else body
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", outside)
    # rgba()/rgb() literals are allowed where the colour is a veil or a shadow:
    # they are alpha composites over photography, not palette entries.
    check(not hexes, "style.css 的 :root 之外没有 #hex",
          "{} 处: {}".format(len(hexes), sorted(set(hexes))[:8]) if hexes else "")

    print("\n== 3. 前端零依赖、无构建步骤 ==")

    scripts = re.findall(r'<script[^>]*\bsrc="([^"]+)"', html)
    external = [s for s in scripts if s.startswith(("http://", "https://", "//"))]
    check(not external, "没有外链脚本", "found {}".format(external) if external else
          "{} 个本地脚本".format(len(scripts)))
    check(not os.path.exists(os.path.join(ROOT, "package.json")),
          "没有 package.json（保持无构建步骤）")
    inline = re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*type=\"module\"[^>]*\bsrc=)[^>]*>",
                        html)
    check(len(scripts) == 1 and scripts and scripts[0].startswith("/"),
          "index.html 只有一个入口脚本，且从根路径加载",
          "scripts={}".format(scripts))

    print("\n== 4. 模块依赖显式声明（import 图是唯一的真源）==")

    files = sorted(f for f in os.listdir(WEB) if f.endswith(".js"))
    mods = {f: parse_module(read("web/" + f)) for f in files}

    # a) 每个 .js 都是 module。挂 window 的普通脚本一律不算 —— 那种写法让
    #    "谁依赖谁"躲进全局命名空间，是这次重构要根除的东西。
    plain = [f for f in files
             if not mods[f]["imports"] and not mods[f]["exported"]]
    check(not plain, "web/ 下每个 .js 都是 ES module（有 import 或 export）",
          "found {}".format(plain) if plain else "{} 个模块".format(len(files)))
    check(not re.search(r"^\s*window\.\w+\s*=", read("web/core.js"), re.M)
          and not re.search(r"window\.(App|Home|G|Views)\s*=", alljs),
          "没有模块往 window 上挂东西", "")

    # b) 每个相对路径都存在
    badpath = []
    for f in files:
        for _, target in mods[f]["imports"]:
            if not target.startswith("."):
                badpath.append("{} -> {}".format(f, target))
                continue
            if not os.path.exists(os.path.normpath(os.path.join(WEB, target))):
                badpath.append("{} -> {}（文件不存在）".format(f, target))
    check(not badpath, "每个 import 的路径都真的存在",
          "; ".join(badpath) if badpath else "{} 条依赖边".format(
              sum(len(mods[f]["edges"]) for f in files)))

    # c) import 过来的名字，目标模块必须真的 export 了。这条和下面的 (e) 一起
    #    把"漏 import"和"名字写错"两个方向都堵住 —— 打包器平时替我们做的
    #    就是这个检查，而这里没有打包器。
    badname = []
    for f in files:
        for imported, target in mods[f]["imports"]:
            if not target.startswith("."):
                continue
            dest = os.path.basename(target)
            if dest not in mods:
                continue
            for n in sorted(imported - mods[dest]["exported"]):
                badname.append("{}: {} 不在 {} 的 export 里".format(f, n, dest))
    check(not badname, "import 的每个名字在目标模块里都有对应 export",
          "; ".join(badname) if badname else "")

    # d) 无环。有环不会立刻报错，但会让求值顺序变得不可预测 ——
    #    而"顺序可预测"正是这次拆分的全部理由。
    edges = {f: [os.path.basename(t) for t in mods[f]["edges"]] for f in files}
    state, cycles = {}, []

    def walk(node, trail):
        if state.get(node) == 1:
            cycles.append(" -> ".join(trail + [node]))
            return
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in edges.get(node, []):
            if nxt in edges:
                walk(nxt, trail + [node])
        state[node] = 2

    for f in files:
        walk(f, [])
    check(not cycles, "依赖图无环", "; ".join(cycles) if cycles else "")

    # e) 每个模块用到的、属于别的模块的顶层名字，必须是 import 进来的。
    #    这是"忘了写 import"的兜底：浏览器会直接 ReferenceError，而冒烟测试
    #    如果只是把所有模块拍平到同一个 scope，反倒可能碰巧跑通。
    owner = {}
    for f in files:
        for n in mods[f]["top"]:
            owner.setdefault(n, set()).add(f)
    forgotten = []
    for f in files:
        imported = set()
        for names, _ in mods[f]["imports"]:
            imported |= names
        local = mods[f]["top"] | mods[f]["local"] | imported | BUILTINS
        for n in sorted(mods[f]["used"] - local):
            if n in owner and f not in owner[n]:
                forgotten.append("{}: {}（在 {} 里）".format(f, n, "/".join(sorted(owner[n]))))
    check(not forgotten, "跨模块用到的名字都 import 了",
          "; ".join(forgotten) if forgotten else "没有裸引用")

    # f) 同一个模块里不能 export 两次同名（真 ESM 直接报错）。顺手也看一眼
    #    每个模块都必须 export 点什么 —— 一个什么都不导出的模块，多半是
    #    被切错了地方。
    dupx, empty = [], []
    for f in files:
        if mods[f]["dup_export"]:
            dupx.append("{}: {}".format(f, sorted(set(mods[f]["dup_export"]))))
        if not mods[f]["exported"]:
            empty.append(f)
    check(not dupx, "没有模块重复 export 同一个名字", "; ".join(dupx) if dupx else "")
    check(not empty, "每个模块都 export 了东西（切错位置会留下空壳）",
          "found {}".format(empty) if empty else "")

    # g) 文件头仍然声明自己依赖什么
    for f in files:
        head = read("web/" + f)[:1800]
        check("@requires" in head or "import " in head,
              "{} 在文件头声明了它依赖什么".format(f))

    print("\n== 5. 组件只有一个基类 ==")
    # Two .btn blocks with different heights once coexisted: the second silently
    # won, and the home page ended up with its own vocabulary (.pri) for what the
    # rest of the app called .primary.
    n = len(re.findall(r"(^|\n)\.btn\s*\{", css))
    check(n == 1, "样式表里只有一个 .btn 基类", "{} 个".format(n))
    orphan = [c for c in (".projAdd", ".cta")
              if re.search(r"(^|\n)\." + c[1:] + r"\s*\{", css)]
    check(not orphan, "没有各自为政的按钮样式",
          "found {}".format(orphan) if orphan else "")

    print()
    if fails:
        print("===== {} 项未通过 =====".format(len(fails)))
        for f in fails:
            print("  - " + f)
        return 1
    print("===== 全部通过 =====")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
