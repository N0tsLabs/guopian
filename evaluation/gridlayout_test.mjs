/* Layout maths for the decision grid. No DOM, no browser. */
import { computeGridLayout, MIN_TILE } from '../web/gridlayout.js';

let fail = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) fail++;
  console.log(`  [${ok ? 'OK' : 'FAIL'}] ${label}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`);
};

console.log('===== determine grid layout =====');

// A typical desktop: 1200x700 for the photo area.
let L = computeGridLayout(4, 1200, 700);
check('4 photos -> 2 rows', { r: L.rows, o: L.overflow }, { r: 2, o: false });
check('4 photos -> 2 columns', L.cols, 2);
check('4 photos -> big tiles', L.tile >= 300, true);

L = computeGridLayout(8, 1200, 700);
check('8 -> two rows of four', { c: L.cols, r: L.rows }, { c: 4, r: 2 });
check('8 -> tiles still readable', L.tile >= MIN_TILE, true);

L = computeGridLayout(12, 1200, 700);
check('12 -> two rows of six', { c: L.cols, r: L.rows }, { c: 6, r: 2 });

// More than two rows can hold -> three rows.
L = computeGridLayout(18, 1200, 700);
check('18 -> two rows of nine (still above the floor)', { c: L.cols, r: L.rows }, { c: 9, r: 2 });

// A large screen fits more, at the same count, without shrinking.
const small = computeGridLayout(12, 800, 500);
const big = computeGridLayout(12, 2400, 1000);
check('same count, larger screen -> larger tiles', big.tile > small.tile, true);

// Three rows appear only when two cannot hold readable tiles.
L = computeGridLayout(30, 900, 600);
check('30 on a small area -> three rows', L.rows, 3);
check('30 on a small area -> tiles at or above the floor', L.tile >= MIN_TILE, true);

// Beyond the floor: hold three rows, scroll.
L = computeGridLayout(60, 1200, 700);
check('60 -> three rows at the floor', { r: L.rows, t: L.tile }, { r: 3, t: MIN_TILE });
check('60 -> needs scrolling', L.overflow, true);

// Degenerate inputs must not produce NaN or a zero tile.
L = computeGridLayout(0, 1200, 700);
check('0 photos -> still 1 tile, no NaN', { n: Number.isFinite(L.tile) && L.tile > 0, c: L.cols }, { n: true, c: 1 });
L = computeGridLayout(5, 0, 0);
check('zero-size area -> no NaN', Number.isFinite(L.tile) && L.tile > 0, true);

// Every column count must cover every photo: no photo may fall off the grid.
for (const n of [1, 2, 3, 5, 7, 9, 12, 17, 25, 40, 60]) {
  const g = computeGridLayout(n, 1400, 800);
  check(`${n} photos fit in ${g.rows}x${g.cols}`, g.cols * g.rows >= n, true);
}

console.log();
console.log(fail ? `===== ${fail} 项失败 =====` : '===== 全部通过 =====');
process.exit(fail ? 1 : 0);
