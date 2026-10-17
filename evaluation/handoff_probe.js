// Record the hand-off from the outgoing card to the arriving one.
//
// Nothing here depends on a timer: the tab this runs in throttles setTimeout to
// roughly a second, so any measurement built on delays is worthless. Everything
// is captured through MutationObserver, which fires regardless.
//
// The decisive number is `widthAtArrival`: the width of the image layer at the
// instant the arrival animation starts. If the layout is correct it is already
// the NEW photo's width; if fitStage() is waiting on the preview it is still the
// PREVIOUS photo's, and the card then gets resized part-way through the arrival.
(() => {
  const card = document.getElementById('photoCard');
  const layer = document.getElementById('photoLayer');
  const stage = document.getElementById('photoStage');
  if (!card || !layer || !stage) return 'no stage';

  const t0 = performance.now();
  const tl = [];
  const snap = (why) => tl.push({
    why,
    t: +(performance.now() - t0).toFixed(1),
    w: layer.style.width || '',
    h: layer.style.height || '',
    entering: card.classList.contains('entering'),
    stage: (stage.className || '').replace('photoStage', '').trim(),
  });

  snap('start');
  const mo = new MutationObserver(() => snap('mut'));
  mo.observe(layer, { attributes: true, attributeFilter: ['style'] });
  mo.observe(card, { attributes: true, attributeFilter: ['class'] });

  // Drive the decision with no timers: down and up in the same tick.
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
  document.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowRight', bubbles: true, cancelable: true }));

  window.__handoff = null;
  // The commit sits behind a setTimeout (EXIT_MS) and this tab throttles those
  // to about a second, so the window has to be generous. No requestAnimationFrame:
  // it does not fire at all in a tab that is not compositing.
  setTimeout(() => {
    mo.disconnect();
    const widths = tl.map(x => x.w).filter(Boolean);
    const uniq = widths.filter((w, i) => i === 0 || w !== widths[i - 1]);
    const firstNew = tl.find(x => x.entering && x.w);
    window.__handoff = {
      uniqueWidths: uniq,
      widthAtArrival: firstNew ? firstNew.w : null,
      resizedAfterArrival: uniq.length > 1 ? uniq.slice(1) : null,
      tail: tl.slice(-30),
    };
  }, 12000);
  return 'started';
})()
