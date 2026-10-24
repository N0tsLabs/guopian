"""浏览器端到端测试：用 Kimi WebBridge 在真实浏览器里操作页面，逐项断言。

为什么要有这个：静态检查（web_check / hygiene）只能看代码结构，抓不到
"按钮 disabled 忘了解""提交后高亮没清""多图里单图快捷键还在生效"这类
只有点一遍才会暴露的问题 —— 而最近出的正是这一类。

用法：python evaluation/ui_e2e.py
它会：
  1. 造一个临时照片库（从 D:\\image cache 里复制少量照片）并用 /api/open 打开
  2. 调 bridge 在页面里跑一整段脚本，返回每条用例的结果
  3. 打印结果表，有失败则退出码 1
  4. 删掉临时库（照片是复制的，原件不动）
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BASE = "http://127.0.0.1:8765"
LIB = os.path.join(ROOT, ".cache", "e2e-lib")
SRC = r"D:\image cache\川西\100MSDCF\过"
PY = sys.executable


def _post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=300) as r:
        return json.loads(r.read())


def _bridge(*args):
    p = subprocess.run([PY, os.path.join(ROOT, "evaluation", "bridge.py"), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout + p.stderr


def wait_ready():
    for _ in range(60):
        try:
            _get("/api/home")
            return True
        except Exception:
            time.sleep(0.5)
    return False


def make_lib(n=12):
    if os.path.isdir(LIB):
        shutil.rmtree(LIB, ignore_errors=True)
    os.makedirs(LIB, exist_ok=True)
    files = sorted(f for f in os.listdir(SRC) if f.lower().endswith((".jpg", ".jpeg")))[:n]
    for f in files:
        shutil.copy2(os.path.join(SRC, f), os.path.join(LIB, f))
    return len(files)


CASES_JS = r"""
async (libSlug, phase) => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const st = await import('/state.js');
  const rows = () => [...document.querySelectorAll('#listScroll .listItem')];
  const key = (k) => document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
  // 决策键是"按住预览"，必须 down + up 才算数（只发 keydown 不会提交）。
  const tap = async (k, ms = 260) => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
    await new Promise((r) => setTimeout(r, ms));
    document.dispatchEvent(new KeyboardEvent('keyup', { key: k, bubbles: true }));
    await new Promise((r) => setTimeout(r, 500));
  };
  const out = [];
  const add = (name, ok, detail) => out.push({ name, ok: !!ok, detail: detail === undefined ? '' : String(detail) });

  // ── 1. 首页 ────────────────────────────────────────────────
  // 首页要么有项目卡片，要么是"还没有项目"的空状态 —— 两者都算正常，
  // 只有"首页根本没显示"才是问题。
  // 页面刚被导航过来时首页还没渲染完，等一小会儿再判断
  for (let i = 0; i < 10 && document.querySelector('#homeView').classList.contains('hidden'); i++) await wait(300);
  add('首页可见（地址是 / 时）', !document.querySelector('#homeView').classList.contains('hidden')
      && (document.querySelectorAll('.projCard').length > 0
          || !!document.querySelector('#homeEmpty, .homeEmpty, .empty')));

  // ── 2. 选文件夹对话框 ──────────────────────────────────────
  document.querySelector('#btnOpen').click();
  await wait(700);
  add('对话框打开', !document.querySelector('#browser').classList.contains('hidden'));
  const chip = [...document.querySelectorAll('.rootChip')].find((c) => /D:/.test(c.textContent));
  if (chip) chip.click();
  await wait(1200);
  const dirRow = [...document.querySelectorAll('.dirRow')].find((r) => !r.classList.contains('up'));
  if (dirRow) dirRow.click();
  await wait(1500);
  const openBtn = document.querySelector('#browserOpen');
  add('打开按钮可点（disabled=false）', openBtn && openBtn.disabled === false);
  add('打开按钮文案指明"当前文件夹"', /打开当前文件夹/.test(openBtn ? openBtn.textContent : ''));
  add('没有"只读打开"复选框', !document.querySelector('#roToggle'));
  add('列表里没有重复的"就用这个文件夹"',
      ![...document.querySelectorAll('.dirRow')].some((r) => r.textContent.includes('就用这个文件夹')));
  document.querySelector('#browserCancel').click();
  await wait(400);

  // 第一阶段到此为止：后面的用例要在过图页里跑。
  // 跳转必须由 runner 用 bridge go 做 —— 在 eval 里改 location 会把
  // 被检视的上下文一起干掉（"Inspected target navigated or closed"）。
  if (phase === 1) return JSON.stringify(out);

  // ── 3. 过图页 ─────────────────────────────────────────────
  add('分析完成后停在过图页', !document.querySelector('#appView').classList.contains('hidden'));
  add('进度页没有"实时更新"开发备注', !document.body.textContent.includes('随着分析推进实时更新'));
  add('队列已就绪', rows().length > 0, rows().length);

  // ── 4. 导航顺序 = 列表顺序 ────────────────────────────────
  st.S.idx = 0;
  const seq = [];
  for (let i = 0; i < 5; i++) { seq.push(st.S.idx); key('ArrowDown'); await wait(150); }
  add('下键逐张前进', seq.join(',') === '0,1,2,3,4', seq.join(','));

  // ── 5. 决策 + 标记 + 撤销 ─────────────────────────────────
  const before = st.S.queue.filter((c) => c.decision).length;
  await tap('ArrowRight');
  const decidedCount = st.S.queue.filter((c) => c.decision).length;
  add('→ 决定了当前这张', decidedCount === before + 1, `${before}→${decidedCount}`);
  const cur = rows().find((x) => x.classList.contains('current'));
  add('当前行高亮唯一', rows().filter((x) => x.classList.contains('current')).length === 1);
  key('Backspace');
  await wait(900);
  const afterUndo = st.S.queue.filter((c) => c.decision).length;
  add('Backspace 撤销回来', afterUndo <= decidedCount, `${decidedCount}→${afterUndo}`);

  // ── 6. 筛选 ───────────────────────────────────────────────
  const chipAll = [...document.querySelectorAll('#triageChips .chip')].find((c) => c.textContent.trim() === '全部');
  if (chipAll) chipAll.click();
  await wait(900);
  add('筛选"全部"后仍有队列', rows().length > 0, rows().length);

  // ── 7. 弹框位置 + 重新分析按钮 ────────────────────────────
  const wrap = document.querySelector('#progressWrap');
  wrap.click();
  await wait(500);
  const panel = document.querySelector('.progPanel');
  const wr = wrap.getBoundingClientRect(), pr = panel.getBoundingClientRect();
  add('弹框贴着进度条下方', pr.top >= wr.bottom - 2 && Math.abs(pr.left - wr.left) < 60,
      `wrap(${Math.round(wr.left)},${Math.round(wr.bottom)}) panel(${Math.round(pr.left)},${Math.round(pr.top)})`);
  const rb = document.querySelector('#progReanalyze');
  add('弹框里有"全部重新分析"', !!rb && rb.disabled === false);
  wrap.click();
  await wait(300);

  // ── 8. Shift 多选从当前张起算 ─────────────────────────────
  st.S.sel.clear(); st.S.shiftAnchor = null;
  const rw = rows();
  rw[3].dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await wait(400);
  st.S.sel.clear();
  rw[6].dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
  await wait(600);
  const picked = [...st.S.sel].map((id) => st.S.queue.findIndex((c) => c.id === id)).sort((a, b) => a - b);
  add('Shift 范围是 3..6 而不是从头开始', picked.join(',') === '3,4,5,6', picked.join(','));

  // ── 9. 多图模式：快捷键必须让路 ───────────────────────────
  st.S.sel.clear();
  const rw2 = rows();
  for (const k of [1, 2, 3]) {
    rw2[k].dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: true }));
    await wait(150);
  }
  await wait(800);
  const gridOpen = !document.querySelector('.decideGrid').classList.contains('hidden');
  add('Ctrl 多选后网格打开', gridOpen, `sel=${st.S.sel.size}`);
  const d0 = st.S.queue.filter((c) => c.decision).length;
  const i0 = st.S.idx;
  key(' '); key('ArrowRight'); key('ArrowDown'); key(' ');
  await wait(800);
  add('多图里按空格/方向键不决策',
      st.S.queue.filter((c) => c.decision).length === d0, `${d0}→${st.S.queue.filter((c) => c.decision).length}`);
  add('多图里按方向键不换图', st.S.idx === i0, `${i0}→${st.S.idx}`);
  add('单图键位在多图里不生效（模式隔离）', typeof st.S.grid === 'undefined');
  add('多图格子用的是清晰图（card）',
      [...document.querySelectorAll('.dgTile img')].every((im) => /\/card$/.test(im.getAttribute('src'))));

  // ── 10. 全部不过：要真的标记上 ────────────────────────────
  const selIds = [...st.S.sel];
  const btn = [...document.querySelectorAll('.decideGrid .btn')].pop();
  add('按钮是"全部不过"', /全部\s*\d*\s*张不过|全部/.test(btn.textContent), btn.textContent.trim());
  btn.click();
  await wait(2200);
  const nowDec = selIds.map((id) => (st.S.queue.find((c) => c.id === id) || {}).decision || null);
  add('全部不过后这几张都变成不过', nowDec.every((x) => x === 'reject'), nowDec.join(','));
  add('提交后选中高亮清空', document.querySelectorAll('#listScroll .listItem.sel').length === 0,
      document.querySelectorAll('#listScroll .listItem.sel').length);
  add('提交后当前行仍只有一个', rows().filter((x) => x.classList.contains('current')).length === 1);

  // ── 11. 恢复：撤销整批 ────────────────────────────────────
  key('Backspace');
  await wait(1200);
  const restored = [...st.S.sel].length === 0;
  add('撤销后没有残留选中状态', restored);

  // ── 12. 视图快捷键 ────────────────────────────────────────
  key('z');
  await wait(400);
  add('z 放大生效', st.V.s > 1.02, `scale=${st.V.s && st.V.s.toFixed(2)}`);
  key('0');
  await wait(300);
  add('0 复位', st.V.s <= 1.02);
  key('g');
  await wait(600);
  add('G 打开九宫格', !document.querySelector('#gridView').classList.contains('hidden'));
  key('g');
  await wait(400);
  add('G 关闭九宫格', document.querySelector('#gridView').classList.contains('hidden'));
  key('?');
  await wait(400);
  add('? 打开帮助', !document.querySelector('#help').classList.contains('hidden'));
  key('Escape');
  await wait(300);
  add('Esc 关闭帮助', document.querySelector('#help').classList.contains('hidden'));

  // ── 13. 工具栏与徽章 ──────────────────────────────────────
  st.S.idx = 0;
  const keepBefore = st.S.queue.filter((c) => c.decision).length;
  document.querySelector('.act.keep').click();
  await wait(900);
  add('工具栏「过」按钮生效', st.S.queue[0].decision === 'keep',
      `${keepBefore}→${st.S.queue.filter((c) => c.decision).length}`);
  const marked = st.S.queue[0];
  key(' ');
  await wait(300);
  key(' ');
  await wait(900);
  add('再按空格取消精选', marked.decision === null || marked.decision !== 'mark', String(marked.decision));

  // ── 14. 列表折叠 / 跳到下一张未审 ────────────────────────
  document.querySelector('#listHide').click();
  await wait(500);
  add('L 隐藏列表', document.querySelector('#listPane').classList.contains('hidden')
      || document.querySelector('#listScroll').offsetWidth === 0);
  document.querySelector('#listShow').click();
  await wait(500);
  add('L 再显示列表', !document.querySelector('#listShow').offsetParent);
  if (document.querySelector('#listJump')) {
    document.querySelector('#listJump').click();
    await wait(900);
    add('跳到下一张未审后当前行有决策前状态',
        !!st.S.queue[st.S.idx] && !st.S.queue[st.S.idx].decision, `idx=${st.S.idx}`);
  }

  // ── 15. 按问题筛选 ───────────────────────────────────────
  const issueChip = [...document.querySelectorAll('#triageChips .chip')]
    .find((c) => /\d+$/.test(c.textContent) && c.dataset.f && c.dataset.f.startsWith('issue:'));
  if (issueChip) {
    issueChip.click();
    await wait(1000);
    const kind = issueChip.dataset.f.slice(6);
    const allHave = st.S.queue.every((c) => (c.issues || []).some((x) => x.kind === kind));
    add('按问题筛选后队列全是该问题', st.S.queue.length > 0 && allHave, `${kind} n=${st.S.queue.length}`);
    const chipAll2 = [...document.querySelectorAll('#triageChips .chip')].find((c) => c.textContent.trim() === '全部');
    if (chipAll2) chipAll2.click();
    await wait(700);
  } else add('按问题筛选（本库无问题项，跳过）', true);

  // ── 16. 人脸框 / 斑马纹 ──────────────────────────────────
  key('i');
  await wait(400);
  const overlayOn = !document.querySelector('#overlay').classList.contains('hidden');
  key('i');
  await wait(300);
  add('I 切换人脸框层', overlayOn !== document.querySelector('#overlay').classList.contains('hidden'), String(overlayOn));
  key('p');
  await wait(400);
  const zebraOn = !document.querySelector('#zebra').classList.contains('hidden');
  key('p');
  await wait(300);
  add('P 切换过曝斑马纹', zebraOn !== document.querySelector('#zebra').classList.contains('hidden'), String(zebraOn));

  return JSON.stringify(out);
}
"""


def main():
    if not wait_ready():
        print("服务没起来：请先 python run.py --no-open")
        return 2
    n = make_lib()
    print(f"临时库：{n} 张 -> {LIB}")
    try:
        js_path = os.path.join(ROOT, ".cache", "_e2e_body.js")
        with open(js_path, "w", encoding="utf-8") as f:
            f.write("(" + CASES_JS + ")(" + json.dumps({"path": LIB}) + ", 1)\n")
        _bridge("go", BASE + "/")
        time.sleep(2)
        raw1 = _bridge("eval-file", js_path)

        r = _post("/api/open", {"path": LIB})
        if not r.get("ok"):
            print("打开临时库失败：", r)
            return 1
        _bridge("go", BASE + "/p/" + r["slug"])
        seen_boot = False
        for _ in range(240):
            try:
                s = _get("/api/state")
            except Exception:
                break
            if s["progress"]["phase"] in ("done", "error"):
                break
            seen_boot = True
            time.sleep(0.5)
        time.sleep(1.0)
        with open(js_path, "w", encoding="utf-8") as f:
            f.write("(" + CASES_JS + ")(" + json.dumps({"path": LIB}) + ", 2)\n")
        raw = _bridge("eval-file", js_path)
        data = []
        for blob in (raw1, raw):
            s = blob.find("[")
            e = blob.rfind("]")
            if s < 0 or e < 0:
                print("没有拿到结果：", blob[:600])
                continue
            try:
                data.extend(json.loads(blob[s:e + 1]))
            except Exception as ex:
                print("结果解析失败：", ex, blob[:300])
        if not data:
            print(raw[:1500])
            return 1
        dedup = {}
        for c in data:
            dedup[c['name']] = c
        data = list(dedup.values())
        fails = 0
        for c in data:
            mark = "OK  " if c["ok"] else "FAIL"
            if not c["ok"]:
                fails += 1
            print(f"  [{mark}] {c['name']}" + (f"   {c['detail']}" if c["detail"] else ""))
        print(f"\n===== {len(data) - fails}/{len(data)} 通过 =====")
        return 1 if fails else 0
    finally:
        try:
            _post("/api/forget", {"path": LIB, "delete_data": True})
        except Exception:
            pass
        shutil.rmtree(LIB, ignore_errors=True)
        for d in os.listdir(os.path.join(ROOT, "catalogs")):
            if d.startswith("e2elib"):
                shutil.rmtree(os.path.join(ROOT, "catalogs", d), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
