/* 过片 Guopian — the settings screen.
 *
 * @requires web/core.js    G ( $ api toast esc )
 * @requires web/index.html the #settings modal shell
 * @requires /api/settings  the schema, the current values, the named factors
 * @requires /api/cache/clear
 *
 * Every field here is wired to something on the server. That is the rule for
 * adding one: a switch that stores a value nobody reads is worse than no switch
 * at all, because it makes this screen look like it does more than it does.
 *
 * Three-way choices are shown as three-way choices. `EYE_BLINK_MAYBE = 0.40` is
 * not something a person can reason about, so it is never a number here -- it is
 * 宽松 / 标准 / 严格, and the server owns what that means.
 */

import { G } from './core.js';
import { Tour } from './tour.js';

const Settings = (() => {
  const { $, api, toast, esc } = G;

  let SCHEMA = null;      // what the server sent last
  let OPEN = false;

  // label + hint are UI copy, so they live here; values and defaults come from
  // the server. Nothing in this table may be a number the user is expected to
  // interpret.
  const GROUPS = [
    ['行为', [
      { k: 'dir_keep', t: 'text', label: '「过」的照片放到',
        hint: '归档时「要」的照片进这个文件夹。只写文件夹名，不能带路径。' },
      { k: 'dir_reject', t: 'text', label: '「不过」的照片放到',
        hint: '归档时「不要」的照片进这个文件夹。不会删除任何东西。' },
      { k: 'dir_mark', t: 'text', label: '「精选」的照片放到',
        hint: '归档时「精选」的照片进这个文件夹。' },
      { k: 'confirm_apply', t: 'bool', label: '移动文件前再确认一次' },
      { k: 'read_only', t: 'bool', label: '以只读方式打开库',
        hint: '连隔离文件夹都不会建，适合先筛一遍移动硬盘。' },
      { k: 'default_filter', t: 'pick', label: '打开库时显示',
        opts: [['all', '全部'], ['pending', '未审']] },
      { k: 'default_sort', t: 'pick', label: '默认排序',
        opts: [['time', '按拍摄时间'], ['name', '按文件名']] },
      { k: 'density', t: 'pick', label: '界面密度', factors: 'density',
        opts: [['compact', '紧凑'], ['standard', '标准'], ['roomy', '宽松']] },
    ]],
    ['判定', [
      { k: 'strictness', t: 'pick', label: '判定严格程度', factors: 'strictness',
        opts: [['relaxed', '宽松'], ['standard', '标准'], ['strict', '严格']],
        hint: '严格 = 更多照片被标出问题。它一次影响一组阈值 —— 模糊、闭眼、曝光、色偏。' },
      { k: 'burst_window', t: 'number', label: '连拍分组窗口', unit: '秒',
        hint: '拍摄时间相隔不超过这个秒数的照片算同一组，只在组内排名。' },
      { k: 'phash_similar', t: 'number', label: '相似判定阈值', unit: '（0–32）',
        hint: '越小越严。调高会把姿势略有不同的同场景照片也算成一组；'
            + '调低只认几乎一模一样的。改完要重新分析才生效。' },
      { k: 'analysis_edge', t: 'number', label: '分析分辨率', unit: 'px',
        hint: '检测用的长边。调大更准也更慢，改完要重新分析才生效。' },
    ]],
    ['高级', [
      { k: 'workers', t: 'number', label: '分析进程数', unit: '（0 = 自动）' },
      { k: '__tour', t: 'action', label: '新手教程', action: 'tour',
        hint: '再走一遍：从认界面到归档，用一批演示照片。' },
    ]],
  ];

  function rows() {
    const s = SCHEMA.settings;
    let html = '';
    for (const [title, items] of GROUPS) {
      html += `<div class="setGroup"><div class="setGroupTitle">${esc(title)}</div>`;
      for (const f of items) {
        html += `<div class="setRow"><div class="setLabel">${esc(f.label)}`;
        if (f.hint) html += `<span class="setHint">${esc(f.hint)}</span>`;
        html += `</div><div class="setCtl">`;
        const v = s[f.k];
        if (f.t === 'bool') {
          html += `<button class="switch ${v ? 'on' : ''}" data-k="${f.k}" data-t="bool"
                     role="switch" aria-checked="${v ? 'true' : 'false'}"><i></i></button>`;
        } else if (f.t === 'pick') {
          html += `<div class="seg">` + f.opts.map(([val, lab]) =>
            `<button class="${v === val ? 'on' : ''}" data-k="${f.k}" data-t="pick"
               data-v="${val}">${esc(lab)}</button>`).join('') + `</div>`;
        } else if (f.t === 'action') {
          html += `<button class="btn ghost" data-k="${f.k}" data-t="action"
                     data-action="${f.action}">打开</button>`;
        } else if (f.t === 'number') {
          html += `<input class="setNum" type="number" data-k="${f.k}" data-t="number"
                     value="${esc(v)}"><span class="setUnit">${esc(f.unit || '')}</span>`;
        } else {
          html += `<input class="setText" type="text" data-k="${f.k}" data-t="text"
                     value="${esc(v)}" spellcheck="false">`;
        }
        html += `</div></div>`;
      }
      html += `</div>`;
    }
    return html;
  }

  function render() {
    if (!SCHEMA) return;
    $('#setBody').innerHTML = rows();
    const body = $('#setBody');

    body.querySelectorAll('.switch').forEach(el => {
      el.onclick = () => {
        const on = !el.classList.contains('on');
        el.classList.toggle('on', on);
        el.setAttribute('aria-checked', on ? 'true' : 'false');
        save({ [el.dataset.k]: on });
      };
    });
    body.querySelectorAll('.seg button').forEach(el => {
      el.onclick = () => {
        el.parentNode.querySelectorAll('button').forEach(b => b.classList.remove('on'));
        el.classList.add('on');
        save({ [el.dataset.k]: el.dataset.v });
      };
    });
    body.querySelectorAll('button[data-t="action"]').forEach(el => {
      el.onclick = () => {
        const act = el.dataset.action;
        if (act === 'tour') { close(); Tour.open({ withDemo: true }); }
      };
    });
    body.querySelectorAll('input.setNum').forEach(el => {
      el.onchange = () => save({ [el.dataset.k]: Number(el.value) });
    });
    // Text is committed on blur rather than on every keystroke: the trash folder
    // name is written to prefs.json, and typing "不" would otherwise save it.
    body.querySelectorAll('input.setText').forEach(el => {
      el.onchange = el.onblur = () => save({ [el.dataset.k]: el.value });
    });
  }

  async function save(patch) {
    try {
      const r = await api('/api/settings', { method: 'POST', body: JSON.stringify(patch) });
      SCHEMA.settings = r.settings;
      delete SCHEMA.settings._renamed;
      applyDensity(r.settings.density);
      // A folder rename moves real files, so say so -- a silent save here
      // would leave the user wondering whether anything happened.
      const ren = r.settings && r.settings._renamed;
      if (ren && ren.length) {
        const bad = ren.filter(x => x.error);
        if (bad.length) {
          toast('已保存，但 {} 个文件夹没能改名：{}'.format(bad.length, bad[0].error), 'err');
        } else {
          const n = ren.reduce((a, x) => a + (x.photos || 0), 0);
          toast('已保存，并把 ' + n + ' 张照片挪到了新文件夹里');
        }
      } else {
        toast('已保存');
      }
    } catch (e) {
      toast('保存失败：' + (e.message || e), 'err');
      render();     // put the UI back to what the server actually holds
    }
  }

  /** Density is one multiplier on the spacing scale, not a second stylesheet. */
  function applyDensity(d) {
    const f = (SCHEMA && SCHEMA.density && SCHEMA.density[d]) || 1;
    const r = document.documentElement.style;
    for (const n of [1, 2, 3, 4, 5, 6]) r.setProperty('--s' + n, (f * 4 * n) + 'px');
  }

  async function load() {
    SCHEMA = await api('/api/settings');
    return SCHEMA;
  }

  async function open() {
    if (!SCHEMA) await load();
    render();
    $('#settings').classList.remove('hidden');
    OPEN = true;
  }

  function close() {
    $('#settings').classList.add('hidden');
    OPEN = false;
  }

  function bind() {
    $('#setClose').onclick = close;
    $('#setClear').onclick = async () => {
      try {
        const r = await api('/api/cache/clear', { method: 'POST', body: '{}' });
        toast('已清理 ' + r.dirs + ' 个缓存目录（' +
              (r.bytes / 1048576).toFixed(1) + ' MB），缩略图会按需重建');
      } catch (e) { toast('清理失败', 'err'); }
    };
    $('#setReset').onclick = async () => {
      await save({ ...SCHEMA.defaults });
      render();
    };
    // Click the backdrop to dismiss, like every other modal in this app.
    $('#settings').onclick = (e) => { if (e.target.id === 'settings') close(); };
  }

  return { load, open, close, bind, applyDensity, isOpen: () => OPEN,
           schema: () => SCHEMA };
})();

export { Settings };
