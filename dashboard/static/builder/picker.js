// iframe-side picker — proxy 가 inject. capture-phase listener 로 navigate 차단,
// finder 로 selector 추출 후 parent (dashboard /builder/edit/{sid}) 로 postMessage.
//
// codex review fix #5: stopImmediatePropagation + auxclick + keydown 차단 (마우스
// middle/right click, Enter/Space 활성화 모두 막음). pointer-events 동작 흐름:
//   capture-phase click → preventDefault + stopImmediatePropagation → 페이지 JS 안 탐.
//   (window.open / location.href programmatic 은 막을 수 없지만 picker.js 가 모든
//    페이지 JS 를 strip 후 inject 되므로 그 path 자체가 없음.)
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

function pickAndPost(e) {
  if (mode === 'idle') return;
  e.preventDefault();
  e.stopImmediatePropagation();
  const t = e.target;
  if (!t) return;
  let sel = '';
  try { sel = finder(t); }
  catch (err) { sel = '/* finder err: ' + (err && err.message) + ' */'; }
  const linkEl = t.tagName === 'A' ? t : (t.closest && t.closest('a'));
  window.parent.postMessage({
    type: 'picker:picked',
    mode,
    selector: sel,
    text: (t.innerText || t.textContent || '').slice(0, 200),
    href: linkEl ? linkEl.href : null,
    tag: (t.tagName || '').toLowerCase(),
  }, '*');
}

document.addEventListener('click', pickAndPost, true);
document.addEventListener('auxclick', pickAndPost, true);  // middle/right click

document.addEventListener('keydown', (e) => {
  if (mode === 'idle') return;
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    e.stopImmediatePropagation();
  }
}, true);

document.addEventListener('submit', (e) => {
  e.preventDefault();
  e.stopImmediatePropagation();
}, true);

function clearOutline() {
  if (lastHovered && lastHovered.style) {
    lastHovered.style.outline = '';
    lastHovered = null;
  }
}
