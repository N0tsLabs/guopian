"""Cross-check the frontend: ids referenced from JS must exist in the HTML.

拆成模块之后这个检查必须扫整个 web/ 目录 —— 只读 app.js + home.js 的话，
它会在"全部通过"的同时什么也没看：$('#...') 现在散在 view/list/card/grid
各个模块里，统计到的 id 会从 87 掉到 85，"JS 会切换的 class" 会从 22 掉到 6。
一个静默失明的检查比没有检查更糟，所以这里改成遍历 web/*.js。

另外，有些 id 是 JS 自己写进 innerHTML 的（应用决策对话框、重命名输入框、
回滚按钮）。原来它们被报成"JS 引用但 HTML 没有"，是误报 —— 现在从 JS 的
字符串里把 `id="..."` 也收集起来，算作已知 id。
"""
import os
import re
import sys

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        return fh.read()


html = read("index.html")
scripts = sorted(f for f in os.listdir(WEB) if f.endswith(".js"))
js = "\n".join(read(f) for f in scripts)
css = read("style.css")

ids = set(re.findall(r'id="([^"]+)"', html))
refs = set(re.findall(r"""[$]\(\s*['"]#([A-Za-z0-9_-]+)['"]""", js))
minted = set(re.findall(r"""id="([A-Za-z0-9_-]+)\"""", js))

missing = sorted(refs - ids - minted)
unused = sorted(i for i in ids - refs
                if not re.search(r"""['"]""" + re.escape(i) + r"""['"]""", js))

print("扫描的模块        : {}".format(", ".join(scripts)))
print("HTML 里的 id      : {}".format(len(ids)))
print("JS 动态生成的 id  : {}".format(len(minted) if minted else 0))
print("JS 引用的 id      : {}".format(len(refs)))
print("JS 引用但没人定义  : {}".format(missing if missing else "无"))
print("HTML 有但 JS 没用  : {}".format(", ".join(unused) if unused else "无"))

# classes toggled from JS should have a rule somewhere
toggled = set()
for m in re.findall(r"classList\.(?:add|toggle|remove)\(([^)]*)\)", js):
    for lit in re.findall(r"""['"]([A-Za-z0-9_-]+)['"]""", m):
        toggled.add(lit)
for m in re.findall(r"""className\s*=\s*['"]([^'"]+)['"]""", js):
    toggled.update(m.split())

no_rule = sorted(c for c in toggled
                 if c not in ("hidden",) and ("." + c) not in css)
print("\nJS 会切换的 class : {}".format(len(toggled)))
print("CSS 里没有对应规则 : {}".format(no_rule if no_rule else "无"))

sys.exit(1 if missing else 0)
