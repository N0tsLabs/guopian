"""Find photos whose decision disagrees with the folder they were filed into.

The folders are ground truth: applying decisions moved each photo into 过 /
不过 / 精选, so a mismatch means a decision was changed after the fact. That is
how the photo my end-to-end test nudged gets found without guessing which one.
"""
import json
import os
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, '.')
from guopian import paths  # noqa: E402

B = 'http://127.0.0.1:8765'
FOLDER = r'D:\image cache\川西\100MSDCF'
BY_DIR = {'过': 'keep', '不过': 'reject', '精选': 'mark'}


def call(path, body=None):
    req = urllib.request.Request(
        B + path,
        data=(json.dumps(body).encode() if body is not None else None),
        headers={'Content-Type': 'application/json'},
        method=('POST' if body is not None else 'GET'))
    return json.load(urllib.request.urlopen(req, timeout=60))


def main() -> int:
    cp = os.path.join(paths.catalog_dir(FOLDER), 'catalog.db')
    con = sqlite3.connect('file:{}?mode=ro'.format(cp.replace('\\', '/')), uri=True)
    con.row_factory = sqlite3.Row

    bad = []
    for r in con.execute('SELECT id, name, decision, rel_path FROM photos ORDER BY id'):
        rel = (r['rel_path'] or '').replace('\\', '/')
        top = rel.split('/')[0] if '/' in rel else ''
        want = BY_DIR.get(top)
        if want and r['decision'] != want:
            bad.append((r['id'], r['name'], top, want, r['decision']))

    print('  决定与文件夹不一致的:')
    if not bad:
        print('     没有 —— 计数差异来自别处')
    for pid, name, folder, want, got in bad:
        print('     id={:<4} {:<16} 在「{}」-> 应为 {:<7} 实际 {!r}'.format(
            pid, name, folder, want, got))

    if bad:
        print()
        print('  按文件夹恢复:')
        for pid, name, folder, want, got in bad:
            call('/api/decide', {'action': want, 'ids': [pid]})
            time.sleep(0.3)
            print('     {} -> {}'.format(name, want))

    st = call('/api/state')
    print()
    print('  最终计数:', st['counts']['decisions'], ' (应为 74 / 8 / 11)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
