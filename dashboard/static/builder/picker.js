// iframe-side picker — proxy 가 inject. capture-phase listener 로 click navigate 차단,
// finder 로 selector 추출 후 parent (dashboard /builder/edit/{sid}) 로 postMessage.
import { finder } from './finder.min.js';

let mode = 'idle';
let lastHovered = null;

window.addEventListener('message', (e) => {
  const m = e.data || {};
  if (m.type === 'picker:mode') {
    mode = m.mode || 'idle';
    clearOutline();
  }
});

document.addEventListener('mouseover', (e) => {
  if (mode === 'idle') return;
  clearOutline();
  const t = e.target;
  if (!t || !t.style) return;
  lastHovered = t;
  t.style.outline = '2px solid #f60';
  t.style.outlineOffset = '-2px';
}, true);

document.addEventListener('click', (e) => {
  if (mode === 'idle') return;
  e.preventDefault();
  e.stopPropagation();
  const t = e.target;
  let sel = '';
  try { sel = finder(t); }
  catch (err) { sel = '/* finder err: ' + (err && err.message) + ' */'; }
  const linkEl = t.tagName === 'A' ? t : (t.closest && t.closest('a'));
  const data = {
    type: 'picker:picked',
    mode,
    selector: sel,
    text: (t.innerText || t.textContent || '').slice(0, 200),
    href: linkEl ? linkEl.href : null,
    tag: (t.tagName || '').toLowerCase(),
  };
  window.parent.postMessage(data, '*');
}, true);

document.addEventListener('submit', (e) => {
  e.preventDefault();
  e.stopPropagation();
}, true);

function clearOutline() {
  if (lastHovered && lastHovered.style) {
    lastHovered.style.outline = '';
    lastHovered = null;
  }
}
