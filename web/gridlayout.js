/* 过片 Guopian — working out how big the decision grid's tiles should be.
 *
 * @requires nothing. Pure arithmetic, so it can be tested without a browser.
 *
 * The grid shows however many photos the user selected in the list. There is no
 * cap: on a large screen thirty tiles are fine, and capping at twelve would make
 * the feature useless exactly for the person with a large monitor. So the tile
 * size is derived from the count and the space available, and the count decides
 * how big the tiles are -- not the other way round.
 *
 * Preference order:
 *   1. two rows, if that leaves tiles big enough to judge
 *   2. three rows, ditto
 *   3. three rows at the minimum size, and let the grid scroll sideways
 *
 * Rows never go above three: a fourth row leaves tiles so short that faces
 * become unreadable, and a tile you cannot read is worse than one you have to
 * scroll to.
 *
 * MIN_TILE is the point below which an eye or a mouth stops being legible. Below
 * it, scrolling beats shrinking.
 */

const MIN_TILE = 96;
const GAP = 10;
const MAX_ROWS = 3;

/**
 * @param {number} count    how many photos are selected
 * @param {number} width    available width in CSS px
 * @param {number} height   available height in CSS px
 * @returns {{cols:number, rows:number, tile:number, overflow:boolean}}
 *   `overflow: true` means the grid is wider than the space and must scroll.
 */
function computeGridLayout(count, width, height) {
  const n = Math.max(1, Math.floor(count) || 1);
  const w = Math.max(1, width);
  const h = Math.max(1, height);

  const sizeFor = (rows) => {
    const cols = Math.ceil(n / rows);
    const byWidth = (w - GAP * (cols - 1)) / cols;
    const byHeight = (h - GAP * (rows - 1)) / rows;
    // Tiles are 4:3 landscape in the list, but the grid shows full photos, so
    // the constraint is the smaller of the two fits rather than an aspect box.
    return { cols, rows, size: Math.floor(Math.min(byWidth, byHeight)) };
  };

  // Start at two rows, not one. A single row is always "wide enough" and would
  // win the search every time, producing a long thin strip -- eight photos
  // across the screen at 150px each instead of a 4x2 block at 250px. Two rows
  // is the shape the grid is for; one row only makes sense for one or two
  // photos, where stacking them would be silly.
  for (let rows = n <= 2 ? 1 : 2; rows <= MAX_ROWS; rows++) {
    const r = sizeFor(rows);
    if (r.size >= MIN_TILE) {
      return { cols: r.cols, rows: r.rows, tile: r.size, overflow: false };
    }
  }

  // Too many to fit: hold three rows at the floor and scroll.
  const cols = Math.ceil(n / MAX_ROWS);
  return { cols, rows: MAX_ROWS, tile: MIN_TILE, overflow: n > MAX_ROWS * Math.floor(w / (MIN_TILE + GAP)) };
}

export { computeGridLayout, MIN_TILE, GAP, MAX_ROWS };
