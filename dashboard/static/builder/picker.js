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
    // visual: active 시 crosshair cursor — 사용자 mode 활성 확인
    try {
      document.body.style.cursor = (mode === 'idle') ? '' : 'crosshair';
    } catch (_) {}
    // ack — parent 가 picker.js 살아있는지 + mode 받았는지 확인
    window.parent.postMessage({type: 'picker:mode-ack', mode}, '*');
    console.log('[picker] mode →', mode);
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
  // idle 일 때도 navigate 차단 — 사용자가 mode 안 누른 채 click 시 페이지 떠나는
  // 혼란 방지. parent 에 nomode 알림 → status panel 안내.
  e.preventDefault();
  e.stopImmediatePropagation();
  if (mode === 'idle') {
    window.parent.postMessage({type: 'picker:nomode'}, '*');
    return;
  }
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

// load 확인용 console log — F12 console 에 안 보이면 picker.js 자체 load 실패
console.log('[picker] loaded — mode=idle (모드 버튼 누르세요)');

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
