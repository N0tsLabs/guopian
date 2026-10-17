"""Throwaway: for each top-level declaration, list which OTHER top-level names it touches.

Naive: strips comments and string/regex literals, collects identifiers, filters out
a known-globals list and the declaration's own name. Params that shadow a top-level
name would show up as a false edge; check them by hand.
"""
import io, re, sys

path = sys.argv[1]
src = io.open(path, encoding="utf-8").read()
lines = src.split("\n")

decl = re.compile(r"^  (?:async\s+)?(?:function\s+([A-Za-z_$][\w$]*)|const\s+([A-Za-z_$][\w$]*)|let\s+([A-Za-z_$][\w$]*)|var\s+([A-Za-z_$][\w$]*))")
found = []
for i, ln in enumerate(lines, 1):
    m = decl.match(ln)
    if m:
        found.append((i, next(x for x in m.groups() if x)))
names = {n for _, n in found}

GLOBALS = set("""
window document console performance localStorage fetch setTimeout clearTimeout
setInterval clearInterval requestAnimationFrame cancelAnimationFrame Image
IntersectionObserver Promise Math JSON Date Object Array String Number Boolean
RegExp Intl Error TypeError Symbol Map Set WeakMap WeakSet parseFloat parseInt
isNaN undefined null true false new typeof instanceof this return if else for
while do switch case break continue function const let var class extends super
try catch finally throw delete void in of await async yield
""".split())

IDENT = re.compile(r"[A-Za-z_$][\w$]*")

def strip_literals(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i)
            i = n if j < 0 else j + 2
        elif c in "'\"`":
            q = c
            i += 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)

report = {}
for k, (start, name) in enumerate(found):
    end = found[k + 1][0] - 1 if k + 1 < len(found) else len(lines)
    body = strip_literals("\n".join(lines[start - 1:end]))
    idents = set(IDENT.findall(body)) - GLOBALS - {name}
    inner = set(re.findall(r"(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)", body))
    idents -= inner
    report[name] = sorted(idents & names)

for name, deps in report.items():
    print("{:24s} -> {}".format(name, " ".join(deps)))
