// Drag-gesture probe. Dispatches real mouse events at the stage and reads back
// what the gesture produced: the card transform, the drag progress numbers, and
// which overlay is showing.
//
// The point is the MIDDLE of the gesture. The old implementation used an 18px
// threshold, so merely wobbling across the centre flipped the whole overlay to
// the other colour -- which is exactly what the probe checks is gone.
(() => {
  const st = document.getElementById('photoStage');
  const card = document.getElementById('photoCard');
  if (!st || !card) return JSON.stringify({ err: 'stage missing' });

  const r = st.getBoundingClientRect();
  const cy = r.top + r.height / 2;
  const x0 = r.left + r.width / 2;
  const out = [];

  const ev = (type, x, target) =>
    (target || window).dispatchEvent(new MouseEvent(type, {
      bubbles: true, cancelable: true, button: 0, buttons: type === 'mouseup' ? 0 : 1,
      clientX: x, clientY: cy,
    }));

  const read = (label, dx) => {
    const cs = getComputedStyle(card);
    out.push({
      label: label, dx: dx,
      transform: cs.transform === 'none' ? '-' : cs.transform,
      pl: st.style.getPropertyValue('--pl'),
      pr: st.style.getPropertyValue('--pr'),
      reject: st.classList.contains('hold-reject'),
      keep: st.classList.contains('hold-keep'),
      dragging: st.classList.contains('dragging'),
      stamp: document.getElementById('previewStamp').textContent,
    });
  };

  ev('mousedown', x0, st);
  read('press', 0);
  for (const dx of [-12, -24, -40, -70, -110, -150, -200]) {
    ev('mousemove', x0 + dx);
    read(dx < 0 ? 'left' : 'right', dx);
  }
  // walk back to the middle -- this is where the old build flipped to "keep"
  for (const dx of [-150, -60, -20, -8, 0, 8, 20, 60]) {
    ev('mousemove', x0 + dx);
    read('back', dx);
  }
  ev('mouseup', x0 + 20);
  const after = {
    dragging: st.classList.contains('dragging'),
    pl: st.style.getPropertyValue('--pl'),
    pr: st.style.getPropertyValue('--pr'),
    transform: getComputedStyle(card).transform,
    commit: false,
  };
  return JSON.stringify({ trail: out, after }, null, 1);
})()
