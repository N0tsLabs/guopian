/* Compact layout audit -- one flat line per metric, easy to read in a console. */
(() => {
  const R = (el) => {
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return [Math.round(b.width), Math.round(b.height)];
  };
  const cs = (el, p) => (el ? getComputedStyle(el)[p] : null);
  const item = document.querySelector('.listItem');
  const items = [...document.querySelectorAll('.listItem')];
  const scroll = document.querySelector('.listScroll');
  const rowH = item ? item.getBoundingClientRect().height : 0;
  const pitch = items.length > 1 && items[0] && items[1]
    ? items[1].getBoundingClientRect().top - items[0].getBoundingClientRect().top : rowH;

  const lines = [
    'viewport        ' + innerWidth + 'x' + innerHeight + ' dpr' + devicePixelRatio,
    'listPane        ' + JSON.stringify(R(document.querySelector('.listPane')))
      + '  basis=' + cs(document.querySelector('.listPane'), 'flexBasis')
      + '  minW=' + cs(document.querySelector('.listPane'), 'minWidth'),
    'listHead        ' + JSON.stringify(R(document.querySelector('.listHead'))),
    'listSummary     ' + JSON.stringify(R(document.querySelector('.listSummary'))),
    'listScroll      ' + JSON.stringify(R(scroll)) + ' pad=' + cs(scroll, 'padding'),
    'listJump        ' + JSON.stringify(R(document.querySelector('.listJump'))),
    'row             h=' + rowH.toFixed(1) + ' pitch=' + pitch.toFixed(1)
      + ' pad=' + cs(item, 'padding'),
    'rowsVisible     ' + Math.floor(scroll.clientHeight / pitch) + ' / ' + items.length,
    'thumb           ' + JSON.stringify(R(document.querySelector('.thumbWrap'))),
    'fonts           name=' + cs(document.querySelector('.listItem .nm'), 'fontSize')
      + ' flag=' + cs(document.querySelector('.listItem .fl'), 'fontSize'),
    'stage           ' + JSON.stringify(R(document.querySelector('.photoStage'))),
    'decisionCol     ' + JSON.stringify(R(document.querySelector('.decisionCol'))),
    'decideBtns      ' + [...document.querySelectorAll('.decide')].map(b =>
      Math.round(b.getBoundingClientRect().height)).join(','),
    'hintbar         ' + JSON.stringify(R(document.querySelector('.hintbar'))),
    'verdictBadge    ' + JSON.stringify(R(document.querySelector('.verdictBadge'))),
    'decisionBadge   ' + JSON.stringify(R(document.querySelector('.decisionBadge')))
      + ' hidden=' + document.querySelector('.decisionBadge').classList.contains('hidden'),
    'histo           ' + JSON.stringify(R(document.querySelector('.histo'))),
    'overflowX       ' + (document.documentElement.scrollWidth > innerWidth),
    'listOverflow    pane=' + (document.querySelector('.listPane').scrollWidth)
      + ' > client=' + (document.querySelector('.listPane').clientWidth),
  ];
  return lines.join('\n');
})()
