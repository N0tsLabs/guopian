"""Put the photo my end-to-end test changed back, then test undo properly.

The e2e test pressed right-arrow on the first photo in the list and the undo
did not take, so the counts moved from 74/8/11 to 75/8/10. This restores it and
then runs the undo probe with the payload shape the API actually wants.
"""
import json
import os
import time
import urllib.request

B = 'http://127.0.0.1:8765'
FOLDER = r'D:\photos\shoot'


def call(path, body=None):
    req = urllib.request.Request(
        B + path,
        data=(json.dumps(body).encode() if body is not None else None),
        headers={'Content-Type': 'application/json'},
        method=('POST' if body is not None else 'GET'))
    return json.load(urllib.request.urlopen(req, timeout=60))


def counts():
    return call('/api/state')['counts']['decisions']


def main() -> int:
    print('  当前计数:', counts())

    # which folder a photo sits in is the ground truth for its decision
    for name in ('DSC09856.JPG', 'DSC09868.JPG'):
        for d in ('过', '不过', '精选'):
            if os.path.exists(os.path.join(FOLDER, d, name)):
                print('  {} 在「{}」文件夹里 -> 决定应是 {}'.format(
                    name, d, {'过': 'keep', '不过': 'reject', '精选': 'mark'}[d]))

    q = call('/api/queue?filter=all&sort=time')
    items = q.get('items') or []
    first = items[0]
    print()
    print('  第一张是 {} (id={})，当前决定 {!r}'.format(
        first['name'], first['id'], first.get('decision')))

    if first.get('decision') == 'keep':
        print('  我把它改回了 reject（这是 e2e 测试误改的）')
        call('/api/decide', {'action': 'reject', 'ids': [first['id']]})
        time.sleep(0.5)
    print('  恢复后计数:', counts())

    # ── now the real undo test, with the correct payload ──
    pid = items[3]['id']
    name = items[3]['name']
    original = call('/api/photo/%d' % pid).get('decision')
    newval = 'reject' if original != 'reject' else 'keep'

    print()
    print('  === 撤销测试: {} (id={}, 原值 {!r}) ==='.format(name, pid, original))
    call('/api/decide', {'action': newval, 'ids': [pid]})
    time.sleep(0.6)
    got = call('/api/photo/%d' % pid).get('decision')
    print('  设为 {!r}  ->  读到 {!r}   {}'.format(
        newval, got, 'OK' if got == newval else '**没生效**'))

    r = call('/api/undo', {})
    res = r.get('result') or {}
    print('  撤销 -> ok={} photo_id={} restored_to={!r}'.format(
        r.get('ok'), res.get('photo_id'), res.get('restored_to')))
    time.sleep(0.6)
    got2 = call('/api/photo/%d' % pid).get('decision')
    print('  撤销后读到 {!r}'.format(got2))

    if got2 == original and res.get('photo_id') == pid:
        print('  [OK]   撤销正确恢复了这张照片')
        bad = False
    elif res.get('photo_id') != pid:
        print('  [FAIL] 撤销动的是另一张 (photo_id={}), 不是 {}'.format(
            res.get('photo_id'), pid))
        bad = True
    else:
        print('  [FAIL] 撤销没恢复')
        bad = True

    if got2 != original:
        call('/api/decide', {'action': original or 'clear', 'ids': [pid]})
        time.sleep(0.4)
    print()
    print('  最终计数:', counts(), '(应为 74 / 8 / 11)')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
