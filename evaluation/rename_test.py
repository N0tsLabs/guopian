"""Renaming a decision folder must carry the photos and the catalog with it.

Runs entirely on a synthetic library under .cache: fake jpegs, a fake catalog,
then a settings change, then checks the folder moved, the files are still inside
it, and every catalog row now points somewhere that exists.
"""
import json
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from guopian import config, paths, session  # noqa: E402

LIB = os.path.join(ROOT, '.cache', 'rentest', 'shoot')


def main() -> int:
    shutil.rmtree(os.path.join(ROOT, '.cache', 'rentest'), ignore_errors=True)

    # 1. a library with the three decision folders already populated
    os.makedirs(LIB)
    made = []
    for folder, n in (('过', 3), ('不过', 2), ('精选', 1)):
        d = os.path.join(LIB, folder)
        os.makedirs(d)
        for i in range(n):
            name = '{}_%02d.jpg'.format(folder) % i
            p = os.path.join(d, name)
            open(p, 'wb').write(b'\xff\xd8\xff\xd9')
            made.append((folder, name, p))

    # 2. a catalog whose rows point at them
    cat = paths.catalog_dir(LIB)
    os.makedirs(cat, exist_ok=True)
    db = os.path.join(cat, 'catalog.db')
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)')
    con.execute('CREATE TABLE photos (id INTEGER PRIMARY KEY, path TEXT, rel_path TEXT, name TEXT, decision TEXT)')
    con.execute("INSERT INTO meta VALUES('root', ?)", (LIB,))
    for i, (folder, name, p) in enumerate(made, 1):
        con.execute('INSERT INTO photos VALUES(?,?,?,?,?)',
                    (i, p, os.path.join(folder, name), name,
                     {'过': 'keep', '不过': 'reject', '精选': 'mark'}[folder]))
    con.commit()
    con.close()

    # 3. register it as a remembered library
    session.remember(LIB)

    before = session.get_settings()
    print('  改名前: dir_keep={!r} dir_reject={!r} dir_mark={!r}'.format(
        before['dir_keep'], before['dir_reject'], before['dir_mark']))
    print('  磁盘上:', sorted(os.listdir(LIB)))

    # 4. the actual change
    print()
    print('  把「过」改成「保留」…')
    after = session.save_settings({'dir_keep': '保留'})
    renamed = after.pop('_renamed', [])
    for r in renamed:
        if r.get('root') == LIB:
            print('    {} -> {}  照片 {} 张  {}'.format(
                r['old'], r['new'], r.get('photos'), r.get('error') or 'OK'))

    print()
    print('  磁盘上:', sorted(os.listdir(LIB)))
    ok_dir = os.path.isdir(os.path.join(LIB, '保留')) and not os.path.isdir(os.path.join(LIB, '过'))
    print('  [{}] 文件夹改名了'.format('OK' if ok_dir else 'FAIL'))

    inside = os.listdir(os.path.join(LIB, '保留')) if ok_dir else []
    ok_files = len(inside) == 3
    print('  [{}] 里面的 {} 张照片跟过来了'.format('OK' if ok_files else 'FAIL', len(inside)))

    con = sqlite3.connect(db)
    rows = con.execute('SELECT id, path, rel_path FROM photos').fetchall()
    bad = [r for r in rows if not os.path.exists(r[1])]
    ok_cat = not bad
    print('  [{}] catalog 的 {} 条路径都指向存在的文件'.format(
        'OK' if ok_cat else 'FAIL', len(rows)))
    for r in bad[:3]:
        print('       失联: {}'.format(r[1]))
    con.close()

    # 5. run it again with no change -- must be a no-op
    again = session.save_settings({'dir_keep': '保留'})
    noop = again.pop('_renamed', [])
    print('  [{}] 同样的值再存一次不会重复改名'.format('OK' if not noop else 'FAIL'))

    # 6. put it back
    session.save_settings({'dir_keep': before['dir_keep']})
    session.forget(LIB)
    print()
    print('  恢复: dir_keep={!r}  磁盘上 {}'.format(
        session.get_settings()['dir_keep'], sorted(os.listdir(LIB))))

    shutil.rmtree(os.path.join(ROOT, '.cache', 'rentest'), ignore_errors=True)
    shutil.rmtree(cat, ignore_errors=True)
    return 0 if (ok_dir and ok_files and ok_cat and not noop) else 1


if __name__ == '__main__':
    raise SystemExit(main())
