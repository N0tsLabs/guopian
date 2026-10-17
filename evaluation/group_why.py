import os
import sqlite3
import sys

sys.path.insert(0, '.')
from guopian import config, paths, phash  # noqa: E402

cp = os.path.join(paths.catalog_dir(r'D:\photos\shoot'), 'catalog.db')
con = sqlite3.connect('file:{}?mode=ro'.format(cp.replace('\\', '/')), uri=True)
con.row_factory = sqlite3.Row

names = ['DSC09886', 'DSC09888', 'DSC09889', 'DSC09890', 'DSC09891']
rows = []
for n in names:
    r = con.execute(
        'SELECT id, name, taken_at, taken_ts, width, height, phash, group_id, group_size '
        'FROM photos WHERE name LIKE ?', (n + '%',)).fetchone()
    if r:
        rows.append(dict(r))

print('  这 5 张的基本情况:')
print('  {:<16} {:<21} {:>5} {:>5}  {}'.format('照片', '拍摄时间', '组', '大小', '宽高'))
for r in rows:
    print('  {:<16} {:<21} {:>5} {:>5}  {}x{}'.format(
        r['name'], r['taken_at'] or '?', r['group_id'], r['group_size'],
        r['width'], r['height']))

print()
print('  两两比较（时间差 + 感知哈希距离）:')
print('  {:<16} {:<16} {:>8} {:>10}  {}'.format('A', 'B', '时间差', '哈希距离', '判定'))
for i in range(len(rows)):
    for j in range(i + 1, len(rows)):
        a, b = rows[i], rows[j]
        dt = None
        if a['taken_ts'] and b['taken_ts']:
            dt = abs(a['taken_ts'] - b['taken_ts'])
        hd = None
        if a['phash'] and b['phash']:
            hd = phash.hamming(a['phash'], b['phash'])

        time_ok = dt is not None and dt <= config.BURST_WINDOW_SEC
        hash_ok = hd is not None and hd <= config.PHASH_SIMILAR
        ar_a = (a['width'] or 1) / (a['height'] or 1)
        ar_b = (b['width'] or 1) / (b['height'] or 1)
        ar_ok = abs(ar_a - ar_b) <= config.GROUP_ASPECT_TOL

        if time_ok and hash_ok and ar_ok:
            verdict = '**应该同组**'
        else:
            why = []
            if not time_ok:
                why.append('时间差 {:.0f}s > {}'.format(dt or 0, config.BURST_WINDOW_SEC))
            if not hash_ok:
                why.append('哈希 {} > {}'.format(hd, config.PHASH_SIMILAR))
            if not ar_ok:
                why.append('宽高比差 {:.3f}'.format(abs(ar_a - ar_b)))
            verdict = '不同组：' + '，'.join(why)
        print('  {:<16} {:<16} {:>8} {:>10}  {}'.format(
            a['name'], b['name'],
            '?' if dt is None else '{:.0f}s'.format(dt),
            '?' if hd is None else hd, verdict))
