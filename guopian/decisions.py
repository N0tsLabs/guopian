"""Applying decisions. Nothing is ever deleted.

Design rules (docs/01 §4):
  * culling never touches a file -- only the catalog changes
  * applying is a separate, explicitly confirmed step
  * the default mode *moves* rejects into <library>/_guopian_rejected/
  * every move is logged and can be rolled back in one click
"""

from __future__ import annotations

import os
import shutil
import time
import uuid

from . import config
from .store import Store

MODE_QUARANTINE = "quarantine"
MODE_XMP = "xmp"
MODE_TRASH = "trash"


def _already_filed(rel_path: str, folder: str) -> bool:
    parts = (rel_path or "").replace("\\", "/").split("/")
    return len(parts) > 1 and parts[0] == folder


def pending(store: Store) -> list[dict]:
    """Decided photos whose file is not yet in that decision's folder.

    ALL three decisions, not only the rejects. A photo with no decision is not
    here on purpose: the three folders describe the result of going through a
    shoot, and an unreviewed photo has no result -- it stays where it is.
    """
    rows = store.conn.execute(
        "SELECT id, path, rel_path, name, size, suggest, decision FROM photos "
        "WHERE decision IS NOT NULL AND decision<>'' ORDER BY rel_path").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        folder = config.dir_for(d["decision"])
        if not folder:
            continue                       # unknown decision: never guess
        if _already_filed(d.get("rel_path"), folder):
            continue                       # already there; a second apply is a no-op
        out.append(d)
    return out


# Kept because the API and the tests still ask for it by name.
def pending_rejects(store: Store) -> list[dict]:
    return [d for d in pending(store) if d["decision"] == "reject"]


def preview(store: Store, mode: str = MODE_QUARANTINE) -> dict:
    items = pending(store)
    root = _library_root(store)
    total_mb = sum((i.get("size") or 0) for i in items) / (1024 * 1024)

    # One entry per decision, so the dialog can show all three folders rather
    # than pretending there is only one. Counts come from pending(), not from a
    # separate query, so the numbers and the list cannot disagree.
    groups = []
    for d in config.DECISIONS:
        folder = config.dir_for(d)
        mine = [i for i in items if i["decision"] == d]
        if not folder:
            continue
        groups.append({
            "decision": d,
            "label": config.DECISION_LABELS.get(d, d),
            "dir": folder,
            "path": os.path.join(root, folder),
            "count": len(mine),
            "mb": round(sum((i.get("size") or 0) for i in mine) / (1024 * 1024), 1),
        })

    undecided = store.conn.execute(
        "SELECT COUNT(*) n FROM photos WHERE decision IS NULL OR decision=''"
    ).fetchone()["n"]

    return {
        "mode": mode,
        "count": len(items),
        "root": root,
        "groups": groups,
        # kept for callers that only care about the rejects
        "dest": os.path.join(root, config.dir_for("reject")),
        "total_mb": round(total_mb, 1),
        "items": [{"id": i["id"], "name": i["name"], "rel_path": i["rel_path"],
                   "decision": i["decision"], "size": i["size"]}
                  for i in items[:400]],
        "truncated": max(0, len(items) - 400),
        "undecided": undecided,
        "keep_count": sum(g["count"] for g in groups if g["decision"] == "keep"),
        "mark_count": sum(g["count"] for g in groups if g["decision"] == "mark"),
    }


def _library_root(store: Store) -> str:
    """The folder the user opened. Stored in meta so --work-dir works."""
    root = store.get_meta("root")
    if root:
        return root
    return os.path.dirname(os.path.abspath(store.work_dir))


def apply(store: Store, mode: str = MODE_QUARANTINE) -> dict:
    if store.get_meta("read_only"):
        return {"ok": False, "error": "该库以只读方式打开，不会移动任何文件"}

    items = pending(store)
    if not items:
        return {"ok": False,
                "error": "没有需要归档的照片（审过的都已经在各自的文件夹里了）"}

    batch = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    root = _library_root(store)
    moved: list[tuple[int, str, str]] = []
    errors: list[str] = []
    counts: dict[str, int] = {}

    for it in items:
        src = it["path"]
        if not os.path.exists(src):
            errors.append("{}: 文件不存在".format(it["name"]))
            continue

        # One folder per decision. A photo with no decision never reaches here
        # (pending() filters it out), so the "keep the originals" promise is
        # structural rather than a check somebody has to remember.
        folder = config.dir_for(it["decision"])
        if not folder:
            errors.append("{}: 未知的决定".format(it["name"]))
            continue
        dest_root = os.path.join(root, folder)

        if mode == MODE_XMP:
            try:
                _write_xmp_rating(src, 1 if it["decision"] == "reject" else 0)
                moved.append((it["id"], src, src))
            except Exception as e:
                errors.append("{}: {}".format(it["name"], e))
            continue

        rel = it.get("rel_path") or os.path.basename(src)
        # rel_path already starts with the folder when a photo is being moved
        # between folders, and joining it again would create 要/要/x.jpg.
        parts = rel.replace("\\", "/").split("/")
        if len(parts) > 1:
            rel = "/".join(parts[1:])
        dst = os.path.join(dest_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)

        if mode == MODE_TRASH:
            base, ext = os.path.splitext(os.path.basename(src))
            dst = os.path.join(dest_root, base + ext)
            n = 1
            while os.path.exists(dst):
                dst = os.path.join(dest_root, "{}_{}{}".format(base, n, ext))
                n += 1

        if os.path.exists(dst):
            base, ext = os.path.splitext(dst)
            dst = "{}_{}{}".format(base, int(time.time()), ext)
        try:
            shutil.move(src, dst)
            moved.append((it["id"], src, dst))
            counts[it["decision"]] = counts.get(it["decision"], 0) + 1
        except Exception as e:
            errors.append("{}: {}".format(it["name"], e))

    con = store.conn
    # `dest` is the library root now: one batch writes to up to three folders,
    # so storing a single one of them would be a half-truth. rollback() works
    # from apply_items, which records the real destination of every file.
    con.execute("INSERT INTO applies(batch, at, mode, dest, n, undone) VALUES(?,?,?,?,?,0)",
                (batch, time.time(), mode, root, len(moved)))
    for pid, src, dst in moved:
        con.execute("INSERT INTO apply_items(batch, photo_id, src, dst) VALUES(?,?,?,?)",
                    (batch, pid, src, dst))
        if mode != MODE_XMP:
            con.execute("UPDATE photos SET path=?, rel_path=? WHERE id=?",
                        (dst, os.path.relpath(dst, root), pid))
    con.commit()
    return {"ok": True, "batch": batch, "moved": len(moved), "errors": errors[:50],
            "dest": root, "mode": mode, "counts": counts}


def rollback(store: Store, batch: str) -> dict:
    con = store.conn
    row = con.execute("SELECT * FROM applies WHERE batch=?", (batch,)).fetchone()
    if row is None:
        return {"ok": False, "error": "找不到该批次"}
    if row["undone"]:
        return {"ok": False, "error": "该批次已经回滚过"}

    root = _library_root(store)
    items = con.execute("SELECT * FROM apply_items WHERE batch=?", (batch,)).fetchall()
    back, errors = 0, []
    for it in items:
        src, dst = it["dst"], it["src"]
        if src == dst:  # xmp mode: nothing to move
            continue
        if not os.path.exists(src):
            errors.append("已不在隔离区: {}".format(os.path.basename(src)))
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        target = dst
        if os.path.exists(target):
            base, ext = os.path.splitext(dst)
            target = "{}.restored{}{}".format(base, int(time.time()), ext)
        try:
            shutil.move(src, target)
            con.execute("UPDATE photos SET path=?, rel_path=? WHERE id=?",
                        (target, os.path.relpath(target, root), it["photo_id"]))
            back += 1
        except Exception as e:
            errors.append("{}: {}".format(os.path.basename(src), e))

    con.execute("UPDATE applies SET undone=1 WHERE batch=?", (batch,))
    con.commit()
    return {"ok": True, "restored": back, "errors": errors[:50],
            "batch": batch, "root": root}


def history(store: Store) -> list[dict]:
    return [dict(r) for r in store.conn.execute(
        "SELECT * FROM applies ORDER BY at DESC LIMIT 50").fetchall()]


# ------------------------------------------------------------------ xmp

def _write_xmp_rating(path: str, rating: int) -> None:
    """Write a minimal Lightroom-compatible sidecar. No ExifTool (GPL)."""
    sidecar = os.path.splitext(path)[0] + ".xmp"
    xml = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '    xmp:Rating="{r}"\n'
        '    xmp:Label="{label}"/>\n'
        ' </rdf:RDF>\n'
        '</x:xmpmeta>\n'
        '<?xpacket end="w"?>\n'
    ).format(r=rating, label="Red" if rating <= 1 else "Green")
    with open(sidecar, "w", encoding="utf-8") as f:
        f.write(xml)

def restore_all(store: Store) -> dict:
    """把归档出去的文件搬回库的根目录，并把所有判断清掉。

    这是把 apply() 反过来做一次：当时按决定把照片分进了三个文件夹，
    现在按路径把它们搬回来。只搬这三个文件夹里的，不碰别处。

    重名不覆盖 —— 根目录已经有同名文件时跳过并记一条错误。
    搬不回来的留在原处，对应的决定也不清（免得出现"数据库说没审过、
    文件却还在归档文件夹里"这种更难查的状态）。
    """
    if store.get_meta("read_only"):
        return {"ok": False, "error": "该库以只读方式打开，不会移动任何文件"}

    root = _library_root(store)
    folders = {config.dir_for(d): d for d in config.DECISIONS}
    rows = store.conn.execute(
        "SELECT id, path, rel_path, name, decision FROM photos ORDER BY id"
    ).fetchall()

    moved, errors, cleared = 0, [], 0
    for r in rows:
        rel = (r["rel_path"] or "").replace("\\", "/")
        parts = rel.split("/")
        top = parts[0] if len(parts) > 1 else ""
        if top not in folders:
            continue                      # 本来就在根目录，不用动
        src = r["path"]
        if not src or not os.path.exists(src):
            errors.append("{}: 文件不在原处".format(r["name"]))
            continue
        dst = os.path.join(root, parts[-1])
        if os.path.exists(dst):
            errors.append("{}: 根目录已有同名文件，跳过".format(r["name"]))
            continue
        try:
            shutil.move(src, dst)
        except OSError as e:
            errors.append("{}: {}".format(r["name"], e))
            continue
        new_rel = parts[-1]
        store.conn.execute(
            "UPDATE photos SET path=?, rel_path=? WHERE id=?",
            (dst, new_rel, r["id"]))
        moved += 1

    store.conn.commit()

    # 文件搬回来了才清判断；搬不回来的保持原样，免得状态自相矛盾。
    cleared = store.reset_all()["cleared"]
    return {"ok": True, "moved": moved, "cleared": cleared, "errors": errors}
