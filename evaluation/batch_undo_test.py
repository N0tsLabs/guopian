"""Batch undo: decide N photos in one batch, undo, expect the exact prior state.

Every photo is flipped to the OPPOSITE of what it currently is, so the batch is
guaranteed to write N log rows. Picking photos that already hold the target
value makes the test pass without exercising anything -- set_decision() skips
the log when nothing changes.
"""

import json
import uuid
import urllib.request

B = 'http://127.0.0.1:8765'


def call(path, body=None):
    req = urllib.request.Request(
        B + path,
        data=(json.dumps(body).encode() if body is not None else None),
        headers={'Content-Type': 'application/json'},
        method=('POST' if body is not None else 'GET'))
    return json.load(urllib.request.urlopen(req, timeout=120))


def counts():
    return call('/api/state')['counts']['decisions']


def main() -> int:
    before = counts()
    print('  before:', before)

    items = (call('/api/queue?filter=all&sort=time').get('items') or [])[:5]
    ids = [i['id'] for i in items]
    orig = {i['id']: (i.get('decision') or None) for i in items}
    print('  ids={} decisions={}'.format(ids, orig))

    to_reject = [i for i in ids if orig[i] != 'reject']
    to_keep = [i for i in ids if orig[i] == 'reject']
    n_changed = len(to_reject) + len(to_keep)
    print('  flipping {} -> reject, {} -> keep'.format(len(to_reject), len(to_keep)))

    batch = 'test-' + uuid.uuid4().hex[:8]
    if to_reject:
        call('/api/decide', {'action': 'reject', 'ids': to_reject, 'batch': batch})
    if to_keep:
        call('/api/decide', {'action': 'keep', 'ids': to_keep, 'batch': batch})
    mid = counts()
    print('  after batch decide:', mid)
    differs = mid != before
    print('  [{}] the batch actually changed something'.format('OK' if differs else 'FAIL'))

    r = call('/api/undo', {'batch': batch})
    res = r.get('result') or {}
    print('  undo -> restored={} of {} expected'.format(res.get('restored'), n_changed))
    print('  [{}] restored every row the batch wrote'.format(
        'OK' if res.get('restored') == n_changed else 'FAIL'))

    after = counts()
    print('  after undo:', after)
    print('  [{}] counts back to exact start'.format('OK' if after == before else 'FAIL'))

    ok_rows = True
    for pid in ids:
        d = call('/api/photo/%d' % pid).get('decision')
        if (d or None) != orig[pid]:
            ok_rows = False
            print('    !! id={} is {!r}, was {!r}'.format(pid, d, orig[pid]))
    print('  [{}] every photo back to its own decision'.format('OK' if ok_rows else 'FAIL'))

    good = differs and res.get('restored') == n_changed and after == before and ok_rows
    print()
    print('  ' + ('ALL OK' if good else 'FAILED'))
    return 0 if good else 1


if __name__ == '__main__':
    raise SystemExit(main())
