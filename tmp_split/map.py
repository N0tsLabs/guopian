"""Throwaway helper: list every top-level declaration in a JS file with line ranges."""
import io, re, sys

path = sys.argv[1]
lines = io.open(path, encoding="utf-8").read().split("\n")

decl = re.compile(r"^  (?:async\s+)?(?:function\s+([A-Za-z_$][\w$]*)|const\s+([A-Za-z_$][\w$]*)|let\s+([A-Za-z_$][\w$]*)|var\s+([A-Za-z_$][\w$]*))")

found = []
for i, ln in enumerate(lines, 1):
    m = decl.match(ln)
    if m:
        found.append((i, next(x for x in m.groups() if x)))

for k, (start, name) in enumerate(found):
    end = found[k + 1][0] - 1 if k + 1 < len(found) else len(lines)
    # trim trailing blank lines / comment blocks that belong to the NEXT decl
    while end > start and not lines[end - 1].strip():
        end -= 1
    print("{:5d} {:5d}  {:6d}  {}".format(start, end, end - start + 1, name))
print("total top-level decls:", len(found), file=sys.stderr)
