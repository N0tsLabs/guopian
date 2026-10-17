/* Real-ESM link check (not part of the required suite; run manually).
 *
 * web_smoke.js runs the modules through a hand-written loader, which proves the
 * import graph resolves *as that loader understands it*. This script is the
 * other half: it hands the files to Node's actual ES module implementation and
 * lets the language validate them — duplicate exports, misspelled imported
 * names, unresolvable specifiers, TDZ order — none of which a regex can check.
 *
 * It only LINKS the modules (evaluates their module bodies). Nothing is called,
 * because the DOM is stubbed with the minimum needed for the module bodies to
 * run. home.js is skipped: its body calls Home.boot(), which needs a DOM.
 */
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const WEB = path.join(import.meta.dirname, '..', 'web');
const stub = new Proxy(function () { return stub; }, {
  get: (t, k) => (k === 'then' ? undefined : stub),
  set: () => true,
  apply: () => stub,
  construct: () => stub,
});
globalThis.window = globalThis;
globalThis.document = stub;
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.IntersectionObserver = function () { this.observe = () => {}; this.disconnect = () => {}; };
globalThis.fetch = () => Promise.reject(new Error('no network in link check'));
globalThis.Image = function () {};

const mods = ['core.js', 'state.js', 'view.js', 'physics.js', 'histogram.js',
              'list.js', 'card.js', 'grid.js', 'keys.js', 'app.js'];

let bad = 0;
for (const m of mods) {
  try {
    await import(pathToFileURL(path.join(WEB, m)).href);
    console.log('  [ok]   ' + m + ' 链接通过（真 ESM）');
  } catch (e) {
    bad++;
    console.log('  [FAIL] ' + m + ': ' + e.message);
  }
}
console.log(bad ? '\n===== ' + bad + ' 个模块链接失败 =====' : '\n===== 真 ESM 链接全部通过 =====');
process.exit(bad ? 1 : 0);
