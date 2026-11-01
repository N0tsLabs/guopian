#!/usr/bin/env python3
"""把人工标注变成数字：每个问题类型的 TP / FP / FN。

为什么需要它：`evaluation/README.md` 说得很对 —— 合成测试图只能证明代码没崩，
真正的阈值来自真实照片的假阳性/假阴性统计。但在这之前，仓库里没有任何脚本把
"人眼标注"变成"能比较的分数"，于是每次调阈值都只能靠感觉，改完也没法回归。

    # 1) 先对着一张张照片人工标一遍（格式见下）
    # 2) 跑分
    python evaluation/score.py "D:\\照片" --labels evaluation/labels.csv

    # 带上一份基线，看这次改动是变好还是变坏
    python evaluation/score.py "D:\\照片" --labels labels.csv --json > after.json
    python evaluation/score.py --compare before.json after.json

labels.csv 的列（`evaluation/README.md` 里也有示例）::

    file,decision,issues,note
    DSC09871.JPG,keep,,
    DSC09882.JPG,reject,blurry,跑动时拍的，确实糊了
    DSC09926.JPG,keep,eye_maybe_closed,太阳下眯眼 → 误报

  file      文件名，或相册内的相对路径（两种都能对上）
  decision  keep / reject / mark；留空表示这张不关心判定
  issues    分号分隔的问题 kind（blurry;eye_closed）；留空 = 这些都没有
  note      随便写，会跟在 FP/FN 明细里，方便回头核对

只统计 labels.csv 里出现过的照片：没标的不算 FP。所以标注集要覆盖整库，
或者至少是随机抽样 —— 挑着标会让数字失真，这一点脚本替不了你。

退出码：0 正常；1 有类型的精确率低于 --min-precision；2 输入有问题。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _open_catalog(lib_path: str) -> sqlite3.Connection:
    from guopian import paths

    db = os.path.join(paths.catalog_dir(lib_path), "catalog.db")
    if not os.path.exists(db):
        raise SystemExit(
            "这个库还没有分析数据：{}\n先跑一次：python run.py \"{}\" --report".format(
                db, lib_path))
    con = sqlite3.connect(db, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def _load_labels(path: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("file") or "").strip().replace("\\", "/")
            if not name:
                continue
            kinds = set()
            for part in (row.get("issues") or "").replace(",", ";").split(";"):
                part = part.strip()
                if part:
                    kinds.add(part)
            out[os.path.basename(name)] = {
                "decision": (row.get("decision") or "").strip().lower(),
                "issues": kinds,
                "note": (row.get("note") or "").strip(),
            }
    return out


def _detected(con: sqlite3.Connection) -> tuple[dict[str, set], dict[str, str]]:
    kinds: dict[str, set] = {}
    suggest: dict[str, str] = {}
    for r in con.execute("SELECT id, name, rel_path, suggest FROM photos"):
        kinds[os.path.basename(r["name"] or r["rel_path"] or "")] = set()
        suggest[os.path.basename(r["name"] or r["rel_path"] or "")] = r["suggest"]
    for r in con.execute("SELECT p.name, p.rel_path, i.kind FROM issues i "
                         "JOIN photos p ON p.id = i.photo_id"):
        key = os.path.basename(r["name"] or r["rel_path"] or "")
        kinds.setdefault(key, set()).add(r["kind"])
    return kinds, suggest


def score(lib_path: str, labels_path: str) -> dict:
    con = _open_catalog(lib_path)
    labels = _load_labels(labels_path)
    detected, suggest = _detected(con)

    missing = sorted(set(labels) - set(detected))
    per_kind: dict[str, dict] = {}
    fp_detail, fn_detail = [], []
    dec_ok = dec_bad = dec_maybe = 0

    for name, lab in labels.items():
        det = detected.get(name)
        if det is None:
            continue
        for k in lab["issues"]:
            row = per_kind.setdefault(k, {"tp": 0, "fp": 0, "fn": 0})
            if k in det:
                row["tp"] += 1
            else:
                row["fn"] += 1
                fn_detail.append({"file": name, "kind": k, "note": lab["note"]})
        for k in det - lab["issues"]:
            row = per_kind.setdefault(k, {"tp": 0, "fp": 0, "fn": 0})
            row["fp"] += 1
            fp_detail.append({"file": name, "kind": k, "note": lab["note"]})

        # 判定：只比"留 / 不留"这一层；精选是人的决定，不算预测。
        want = lab["decision"]
        if want not in ("keep", "reject", "mark"):
            continue
        want = "reject" if want == "reject" else "keep"
        got = suggest.get(name) or ""
        if got == "maybe":
            dec_maybe += 1
        elif got == want:
            dec_ok += 1
        else:
            dec_bad += 1

    for k, v in per_kind.items():
        tp, fp, fn = v["tp"], v["fp"], v["fn"]
        v["precision"] = round(tp / (tp + fp), 3) if tp + fp else None
        v["recall"] = round(tp / (tp + fn), 3) if tp + fn else None
        v["support"] = tp + fn

    return {
        "library": os.path.abspath(lib_path),
        "labels": os.path.abspath(labels_path),
        "labeled_photos": len(labels),
        "matched_photos": len(labels) - len(missing),
        "missing_in_catalog": missing[:20],
        "kinds": per_kind,
        "decision": {"agree": dec_ok, "disagree": dec_bad, "maybe": dec_maybe},
        "false_positives": fp_detail,
        "false_negatives": fn_detail,
    }


def _print_report(res: dict) -> None:
    print("\n  库: {}  标注: {} 张（对上 {} 张）".format(
        res["library"], res["labeled_photos"], res["matched_photos"]))
    if res["missing_in_catalog"]:
        print("  !! 有 {} 张标注在库里找不到：{}".format(
            len(res["missing_in_catalog"]), ", ".join(res["missing_in_catalog"][:5])))

    print("\n  {:<22} {:>5} {:>5} {:>5} {:>10} {:>8}".format(
        "问题", "TP", "FP", "FN", "精确率", "召回率"))
    print("  " + "-" * 62)
    for k in sorted(res["kinds"], key=lambda x: (-(res["kinds"][x]["fp"]), x)):
        v = res["kinds"][k]
        prec = "-" if v["precision"] is None else "{:.0%}".format(v["precision"])
        rec = "-" if v["recall"] is None else "{:.0%}".format(v["recall"])
        flag = "  <- 误报多" if (v["precision"] is not None and v["precision"] < 0.8) else ""
        print("  {:<22} {:>5} {:>5} {:>5} {:>10} {:>8}{}".format(
            k[:22], v["tp"], v["fp"], v["fn"], prec, rec, flag))

    d = res["decision"]
    total = d["agree"] + d["disagree"]
    if total:
        print("\n  判定一致率: {:.0%}（{} / {}，另有 {} 张判成「建议复查」）".format(
            d["agree"] / total, d["agree"], total, d["maybe"]))

    for title, key in (("误报（标了没问题，它报了）", "false_positives"),
                       ("漏报（标了有问题，它没报）", "false_negatives")):
        items = res[key]
        if not items:
            continue
        print("\n  {}: {}".format(title, len(items)))
        for it in items[:12]:
            print("    {:<24} {:<20} {}".format(it["file"][:24], it["kind"], it["note"][:40]))
        if len(items) > 12:
            print("    …还有 {} 条".format(len(items) - 12))
    print()


def _compare(before: dict, after: dict) -> int:
    """两份分数对比：正数表示精确率变好了。"""
    print("\n  {:<22} {:>12} {:>12} {:>8}".format("问题", "之前", "现在", "变化"))
    print("  " + "-" * 60)
    worse = 0
    for k in sorted(set(before["kinds"]) | set(after["kinds"])):
        b = before["kinds"].get(k, {}).get("precision")
        a = after["kinds"].get(k, {}).get("precision")
        if b is None and a is None:
            continue
        bs = "-" if b is None else "{:.0%}".format(b)
        as_ = "-" if a is None else "{:.0%}".format(a)
        delta = ""
        if b is not None and a is not None:
            d = a - b
            delta = "{:+.0f}pt".format(d * 100)
            if d < -0.02:
                worse += 1
                delta += "  <-" 
        print("  {:<22} {:>12} {:>12} {:>8}".format(k[:22], bs, as_, delta))
    print()
    return 1 if worse else 0


def _read_json(path: str) -> dict:
    """读 JSON，容忍 BOM 和 UTF-16。

    Windows PowerShell 的 `>` 重定向会写出 UTF-16LE（带 0xFF 0xFE），而
    `json.load(open(path))` 默认按 UTF-8 读 —— 于是 `--json > a.json` 之后
    `--compare a.json b.json` 会死在 codec 上，看起来像脚本坏了。
    """
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:
            continue
    raise SystemExit("看不懂这个 JSON（编码不对？）: {}".format(path))


def main() -> int:
    ap = argparse.ArgumentParser(description="按人工标注给每个问题类型打分")
    ap.add_argument("library", nargs="?", help="照片库目录（跑过分析的）")
    ap.add_argument("--labels", help="labels.csv 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON（可存成基线）")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="比较两份 --json 输出")
    ap.add_argument("--min-precision", type=float, default=0.0,
                    help="任何类型的精确率低于这个值就以 1 退出（默认不卡）")
    args = ap.parse_args()

    if args.compare:
        before = _read_json(args.compare[0])
        after = _read_json(args.compare[1])
        return _compare(before, after)

    if not args.library or not args.labels:
        ap.error("要么给 library + --labels，要么用 --compare")
    if not os.path.isdir(args.library):
        print("不是有效的文件夹:", args.library)
        return 2
    if not os.path.exists(args.labels):
        print("找不到标注文件:", args.labels)
        return 2

    res = score(args.library, args.labels)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        _print_report(res)

    if args.min_precision > 0:
        bad = [k for k, v in res["kinds"].items()
               if v["precision"] is not None and v["precision"] < args.min_precision]
        if bad:
            print("精确率低于 {:.0%}: {}".format(args.min_precision, ", ".join(sorted(bad))))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
