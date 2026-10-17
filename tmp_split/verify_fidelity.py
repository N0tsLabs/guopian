"""Verify the split lost nothing: every non-blank line of the original app.js
must appear (after removing the IIFE's 2-space indent) in exactly one module."""
import io, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
orig = io.open(os.path.join(ROOT, "tmp_split", "app.js.orig"), encoding="utf-8").read().split("\n")
mods = ["state.js", "physics.js", "view.js", "histogram.js", "list.js",
        "card.js", "grid.js", "keys.js", "app.js"]

pool = collections.Counter()
where = collections.defaultdict(list)
for m in mods:
    txt = io.open(os.path.join(ROOT, "web", m), encoding="utf-8").read().split("\n")
    for ln in txt:
        if ln.strip():
            pool[ln] += 1
            where[ln].append(m)

# lines deliberately changed:
#   the module envelope (imports/exports/headers)
#   + the 4 lines whose name moved to another module
INTENTIONAL = (set(range(1, 28)) | set(range(1758, 1761))
               | {166,      # Home.refresh()      -> onLibraryClosed()
                  1645,     # if (drag) onDragEnd -> cancelDrag()
                  1678,     # if (hold)           -> if (holding())
                  1744})    # hold.action         -> held

missing, dupes = [], []
for i, ln in enumerate(orig, 1):
    if not ln.strip() or i in INTENTIONAL:
        continue
    body = ln[2:] if ln.startswith("  ") else ln
    if pool[body] == 0:
        missing.append((i, ln))
    elif pool[body] > 1:
        dupes.append((i, ln, where[body]))

print("original non-blank lines (outside the envelope): {}".format(
    sum(1 for i, l in enumerate(orig, 1) if l.strip() and i not in INTENTIONAL)))
print("lines NOT found in any module : {}".format(len(missing)))
for i, ln in missing[:40]:
    print("   {:5d} | {}".format(i, ln))
print("lines found in MORE THAN ONE  : {}".format(len(dupes)))
for i, ln, w in dupes[:20]:
    print("   {:5d} | {} -> {}".format(i, ln, w))
sys.exit(1 if missing else 0)
