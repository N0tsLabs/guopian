#!/usr/bin/env python3
"""Verify the three decision animations.

A CSS animation whose selector stops matching, whose keyframes get renamed, or
whose duration drifts out of step with the JS that waits for it produces no
error at all -- the card simply behaves wrong. None of that is visible in a
static screenshot, so it is checked mechanically here.

Two layers:

  static  -- always runs. Reads the stylesheet back through CSSOM and compares
             the animation durations against EXIT_MS in app.js. A mismatch
             means the next photo is rendered while the card is still flying,
             or the card sits frozen for a moment before anything happens.
  live    -- needs the tab in the foreground, because Chromium freezes the
             animation timeline on a hidden tab. Skipped automatically.

    python evaluation/anim_check.py [--shots]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
BRIDGE = os.path.join(HERE, "bridge.py")

EXITS = [("release-reject", "exitReject", "reject", "photoCard"),
         ("release-keep", "exitKeep", "keep", "photoCard"),
         ("release-mark", "exitMark", "mark", "photoCard"),
         # Taking a 收藏 mark back. Not a departure -- the card stays put and
         # only the star leaves -- and it animates a different element, which is
         # why the target has to be named per entry.
         ("release-mark-off", "starOut", "unmark", "previewStamp")]


def ev(js: str) -> str:
    """Run JS in the page.

    Goes through a temp file rather than as a command-line argument: the
    snippets here are long and full of quotes, and both the shell and
    subprocess quoting will happily mangle them.
    """
    tmp = os.path.join(HERE, ".anim_probe.js")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(js)
    r = subprocess.run([PY, BRIDGE, "eval-file", tmp], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip()


def unwrap(raw: str):
    """Parse a bridge reply.

    `bridge.py eval`/`eval-file` already peel off the {"ok":..,"data":{..}}
    envelope and print the inner value, so this must handle BOTH that and a
    bare scalar ("visible", 3) -- and not silently return None for either.
    """
    starts = [i for i in (raw.find("{"), raw.find("[")) if i >= 0]
    if not starts:
        try:
            return json.loads(raw)
        except Exception:
            return raw or None
    try:
        d = json.loads(raw[min(starts):])
    except Exception:
        return None
    if isinstance(d, dict) and "data" in d:
        v = (d.get("data") or {}).get("value")
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v
    return d


def js_labels() -> dict:
    """The decision words, read from their ONLY source: config.py.

    This used to scrape a LABEL literal out of app.js. That literal is gone --
    the words now arrive from the server at startup, so app.js holds an empty
    shell and scraping it would yield nothing. Reading config directly is also
    simply more correct: hard-coding the words here would make this tool lie the
    moment the vocabulary changes, which is exactly what it is meant to catch.
    """
    try:
        sys.path.insert(0, ROOT)
        from guopian import config
        return dict(config.DECISION_LABELS)
    except Exception:
        return {}


def js_exit_ms() -> dict:
    """Read the JS wait times so they can be compared against the CSS."""
    src = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
    out = {}
    for name, key in (("EXIT_MS", None), ("UNMARK_MS", "unmark")):
        m = re.search(name + r"\s*=\s*\{([^}]*)\}", src)
        if m:
            out.update({k: int(v) for k, v in re.findall(r"(\w+)\s*:\s*(\d+)", m.group(1))})
        else:
            m = re.search(name + r"\s*=\s*(\d+)", src)
            if m and key:
                out[key] = int(m.group(1))
    return out


def main() -> int:
    shots = "--shots" in sys.argv
    print("== 静态核验 ==\n")

    # Everything below reads the COMPUTED animation off a live element, so the
    # app view has to be on screen. When it is hidden the elements have no box
    # and Chromium resolves no animation at all -- which looks exactly like
    # broken CSS and is not. Check first and say so.
    app_open = unwrap(ev(
        "!!(document.getElementById('appView')"
        " && !document.getElementById('appView').classList.contains('hidden'))"))
    if not app_open:
        print("  看图界面没打开（还停在首页），所以量不到任何动画 ——")
        print("  元素没有盒子时浏览器不解析 animation。先在界面里打开一个文件夹。")
        return 2

    want = js_exit_ms()
    labels = js_labels()
    print("  app.js EXIT_MS = {}".format(want or "<not found>"))
    print("  app.js LABEL   = {}".format(labels or "<not found>"))

    # Read the COMPUTED animation on the real element rather than the CSSOM
    # rule: `animation: name 280ms var(--drop) both` stores a pending
    # substitution, so rule.style.animationName comes back empty even though the
    # declaration is perfectly valid and does apply.
    keys = unwrap(ev(
        "(()=>{const out={};"
        "for(const ss of document.styleSheets){let rs;try{rs=ss.cssRules}catch(e){continue}"
        "for(const r of rs){"
        " if(r.constructor&&r.constructor.name==='CSSKeyframesRule')out[r.name]=r.cssRules.length;}}"
        "return JSON.stringify(out);})()")) or {}

    bad = 0
    dur_of: dict = {}
    print("\n  {:<13} {:<12} {:<20} {:>8} {:>8} {:>6}  {}".format(
        "keyframes", "target", "computed animation", "css(ms)", "js(ms)", "stops", "verdict"))
    for cls, name, act, target in EXITS:
        got = unwrap(ev(
            "(()=>{const st=document.getElementById('photoStage');"
            "const el=document.getElementById('" + target + "');"
            "st.classList.remove('release-reject','release-keep','release-mark','release-mark-off');"
            "void el.offsetWidth;"
            "st.classList.add('" + cls + "');void el.offsetWidth;"
            "const cs=getComputedStyle(el);"
            "const v={name:cs.animationName,dur:cs.animationDuration};"
            "st.classList.remove('release-reject','release-keep','release-mark','release-mark-off');"
            "return JSON.stringify(v);})()")) or {}
        # `ev()` returns an error STRING when the page cannot be reached -- the
        # bridge refuses to touch a tab that is not ours, or the app view is not
        # open. Without this guard the loop below dies on `str.get` and the run
        # looks like a code failure instead of "could not measure". Exit 2 says
        # "no result", which is not the same as "failed".
        if not isinstance(got, dict):
            print("\n  无法在浏览器里测量：{}".format(str(got)[:160]))
            print("  先确认 guopian 的标签页是当前活动标签页，并且已经打开了一个库。")
            return 2

        aname = got.get("name") or ""
        dur = got.get("dur") or "0s"
        dur_of[name] = dur
        css_ms = int(round(float(re.sub(r"[^0-9.]", "", dur) or 0)
                           * (1000 if "ms" not in dur else 1)))
        js_ms = want.get(act, 0)
        stops = keys.get(name, 0)
        # JS must wait at least as long as the animation, or the next photo is
        # swapped in mid-flight.
        ok = (aname == name) and stops >= 2 and js_ms >= css_ms
        why = ""
        if aname != name:
            why = "动画名是 '{}'".format(aname or "空")
        elif stops < 2:
            why = "keyframes 缺失"
        elif js_ms < css_ms:
            why = "JS 等得比动画短"
        print("  {:<13} {:<12} {:<20} {:>8} {:>8} {:>6}  {}".format(
            name, target, "{} {}".format(aname, dur), css_ms, js_ms, stops,
            "OK" if ok else why))
        if not ok:
            bad += 1

    print("\n== 实机核验 ==")
    p = os.path.join(ROOT, "_cdp.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"method": "Page.bringToFront", "params": {}}, f)
    subprocess.run([PY, BRIDGE, "rawfile", "cdp", p], capture_output=True,
                   text=True, encoding="utf-8")
    time.sleep(0.5)
    visible = unwrap(ev("document.visibilityState")) == "visible"
    # `visibilityState` is not enough. A window that is occluded or minimised
    # still reports "visible", but the compositor stops rendering and the
    # document timeline freezes -- so CSS animations are never even created and
    # getAnimations() comes back empty for perfectly good CSS. Sampling the
    # timeline is the only reliable way to tell that apart from a real break.
    t1 = unwrap(ev("document.timeline.currentTime"))
    time.sleep(0.3)
    t2 = unwrap(ev("document.timeline.currentTime"))
    rendering = isinstance(t1, (int, float)) and isinstance(t2, (int, float)) and t2 > t1
    # An element inside a hidden subtree has no box, and Chromium does not build
    # animations for things it is not rendering -- the CSS still resolves, so
    # the computed animationName looks fine while getAnimations() stays empty.
    print("  标签页可见: {}   时间轴在走: {}   看图界面打开: {}".format(
        visible, rendering, app_open))

    if not app_open:
        print("  先用界面打开一个文件夹再看 —— 应用视图隐藏时元素没有盒子，")
        print("  浏览器不会为它创建动画对象。")
    elif not rendering:
        print("  这个环境里量不到动画的实际运行：Chromium 只在真正合成帧的时候才创建")
        print("  CSS 动画对象，被遮挡的窗口不会。静态核验已经证明 CSS 接得对，")
        print("  实际观感需要在可见窗口里看。")
    else:
        for cls, name, act, target in EXITS:
            # The stamp's label is written by the app when a gesture starts, so
            # set it here too -- otherwise the paused frame shows an empty seal
            # and looks like a rendering bug.
            label = labels.get("mark" if act == "unmark" else act, "")
            ev("(()=>{document.getElementById('previewStamp').textContent='"
               + label + "';"
               "const st=document.getElementById('photoStage');"
               "st.classList.remove('release-reject','release-keep','release-mark','release-mark-off');"
               "void document.getElementById('" + target + "').offsetWidth;"
               "st.classList.add('" + cls + "');return 1})()")
            time.sleep(0.02)
            got = unwrap(ev(
                "(()=>{const a=document.getElementById('" + target + "').getAnimations();"
                "return JSON.stringify({n:a.length,names:a.map(x=>x.animationName)});})()"))
            n = (got or {}).get("n", 0)
            print("  {:<16} {:<12} {} anim(s)  {}".format(
                cls, target, n, "OK" if n > 0 else "<-- NOT RUNNING"))
            if n == 0:
                bad += 1
            elif shots:
                # Freeze mid-flight so the frame can actually be looked at.
                d = dur_of.get(name, "0ms")
                dur = int(round(float(re.sub(r"[^0-9.]", "", d) or 0)
                                * (1000 if "ms" not in d else 1)))
                ev("(()=>{const c=document.getElementById('" + target + "');"
                   "const x=c.getAnimations()[0];x.pause();x.currentTime="
                   + str(int(dur * 0.45)) + ";return 1})()")
                out = subprocess.run([PY, BRIDGE, "shot"], capture_output=True,
                                     text=True, encoding="utf-8").stdout.strip()
                if out and os.path.exists(out):
                    from PIL import Image
                    Image.open(out).crop((600, 40, 1500, 830)).save(
                        os.path.join(ROOT, "_exit_{}.png".format(act)))
            ev("(()=>{const st=document.getElementById('photoStage');"
               "st.classList.remove('release-reject','release-keep','release-mark','release-mark-off');"
               "document.getElementById('" + target + "').getAnimations().forEach("
               "a=>a.cancel());return 1})()")

    print("\n  " + ("全部通过" if not bad else "{} 项有问题".format(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
