// iframe-side picker — proxy 가 inject. capture-phase listener 로 navigate 차단.
//
// 1-click 자동 매핑 (사용자 UX 우선):
//   - row click 1회 → :nth-* strip 으로 같은-form row 다 자동 selector
//   - 그 selector 매칭된 row 다 outline 표시 (사용자 시각 confirm)
//   - row 안 child 자동 heuristic 매핑: title=가장 긴 <a>, link=같은 href,
//     post_id=<a href> query string 의 흔한 key (pkid/id/seq/no) 또는 row data-* attr,
//     date=\d{4}[-./]\d{1,2}[-./]\d{1,2} 매칭 text element
//   - parent 에 row_selector + auto fields + matched count 한 번에 postMessage
//
// 모드 (3종):
//   row   — row 한 곳 클릭 → 위 자동 처리
//   field:<name>  — 사용자가 자동 매핑 틀린 field 만 수동 재선택
//   idle  — 클릭 차단 (nomode 알림만)
import { finder } from './finder.min.js';

let mode = 'idle';
let lastHovered = null;
let matchedOutlineRows = [];

window.addEventListener('message', (e) => {
  const m = e.data || {};
  if (m.type === 'picker:mode') {
    mode = m.mode || 'idle';
    clearOutline();
    // matched outline 은 보존 — parent 가 row pick 후 자동 idle 보내 outline
    // 즉시 사라지던 bug. 명시적 picker:clear-matched 받을 때만 clear.
    if (m.clear_matched) clearMatchedOutline();
    try {
      document.body.style.cursor = (mode === 'idle') ? '' : 'crosshair';
    } catch (_) {}
    window.parent.postMessage({type: 'picker:mode-ack', mode}, '*');
    console.log('[picker] mode →', mode);
  }
});

document.addEventListener('mouseover', (e) => {
  if (mode === 'idle') return;
  clearOutline();
  const t = e.target;
  if (!t || !t.style) return;
  if (matchedOutlineRows.indexOf(t) !== -1) return;  // matched 색 보존
  lastHovered = t;
  // outline → target CSS 의 `outline:0` reset 에 묻힘. box-shadow inset 으로 강제 표시.
  t.style.setProperty('box-shadow', 'inset 0 0 0 2px #f60', 'important');
}, true);

function _normalizeSelector(sel) {
  // finder 출력의 :nth-child(N) / :nth-of-type(N) strip → 같은 form 매칭
  return sel.replace(/:nth-(child|of-type)\(\d+\)/g, '');
}

function _safeQueryAll(sel) {
  try { return Array.from(document.querySelectorAll(sel)); }
  catch (_) { return []; }
}

function _heuristicFields(rowEl) {
  const out = {};
  // title + link = row 안 가장 긴 text 의 <a href>
  const anchors = rowEl.querySelectorAll('a[href]');
  let titleA = null;
  let maxLen = 0;
  for (const a of anchors) {
    const t = (a.innerText || a.textContent || '').trim().length;
    if (t > maxLen) { maxLen = t; titleA = a; }
  }
  if (titleA) {
    try {
      const aSel = finder(titleA);
      out.title = aSel;
      out.link = aSel;
    } catch (_) {}
    // post_id heuristic 1: href query string 의 흔한 key
    const href = titleA.getAttribute('href') || '';
    const keys = [
      'pkid', 'id', 'seq', 'no', 'nttId', 'articleNo', 'bbsSeq', 'documentSrl',
      'gid', 'idx', 'num', 'code', 'articleId', 'article_id', 'newsId', 'news_id',
      'view_id', 'boardSeq', 'cntntsId', 'bbsId', 'pid', 'aid',
    ];
    for (const k of keys) {
      const re = new RegExp('[?&]' + k + '=([^&#]+)');
      const m = href.match(re);
      if (m) {
        out.post_id = out.title;
        out.post_id_attr = 'href';
        out.post_id_regex = '[?&]' + k + '=([^&#]+)';
        break;
      }
    }
    // post_id heuristic 2: path 의 마지막 숫자 segment (예: /news/view/123456)
    if (!out.post_id) {
      const pathMatch = href.match(/\/(\d{3,})(?:[/?#]|$)/);
      if (pathMatch) {
        out.post_id = out.title;
        out.post_id_attr = 'href';
        out.post_id_regex = '/(\\d{3,})(?:[/?#]|$)';
      }
    }
  }
  // row 자체 data-* attr (post_id heuristic 2)
  if (!out.post_id) {
    const dataKeys = ['data-id', 'data-seq', 'data-post-id', 'data-no', 'data-article-id', 'data-nttid'];
    for (const dk of dataKeys) {
      if (rowEl.hasAttribute(dk)) {
        try { out.post_id = finder(rowEl); out.post_id_attr = dk; } catch (_) {}
        break;
      }
    }
  }
  // date — text 안 패턴 매칭
  const datePat = /\d{4}[-./]\d{1,2}[-./]\d{1,2}/;
  const tw = document.createTreeWalker(rowEl, NodeFilter.SHOW_TEXT, null);
  let n;
  while ((n = tw.nextNode())) {
    if (datePat.test(n.textContent)) {
      const parent = n.parentElement;
      if (parent && parent !== rowEl) {
        try { out.date = finder(parent); } catch (_) {}
        break;
      }
    }
  }
  return out;
}

function _outlineMatched(rows) {
  // target page CSS 가 `outline: 0` 박는 흔한 reset 때문에 outline 안 보임 → box-shadow
  // inset + background 으로 강제 표시. setProperty(... , 'important') 로 우선순위 ↑.
  clearMatchedOutline();
  for (const r of rows) {
    if (!r.style) continue;
    r.style.setProperty('box-shadow', 'inset 0 0 0 2px #2a7', 'important');
    r.style.setProperty('background-color', 'rgba(42,170,119,0.12)', 'important');
    matchedOutlineRows.push(r);
  }
}

function clearMatchedOutline() {
  for (const r of matchedOutlineRows) {
    if (r && r.style) {
      r.style.removeProperty('box-shadow');
      r.style.removeProperty('background-color');
    }
  }
  matchedOutlineRows = [];
}

function _ascendToRow(t) {
  // 안쪽 text/icon click 했을 때도 *row-like* ancestor 로 ascent.
  // 룰: list-item tag (tr/li/article/section) OR class 에 list/item/row/post/article
  // 단어 포함. 가장 가까운 ancestor 사용. 없으면 t 자체.
  const tagRe = /^(tr|li|article|section)$/i;
  const clsRe = /(list|item|row|post|article|entry|notice|news)/i;
  let cur = t;
  for (let depth = 0; depth < 10 && cur; depth++) {
    if (tagRe.test(cur.tagName || '')) return cur;
    const cls = cur.className || '';
    if (typeof cls === 'string' && clsRe.test(cls)) return cur;
    cur = cur.parentElement;
  }
  return t;
}

function _handleRowClick(rawT) {
  const t = _ascendToRow(rawT);
  let rawSel = '';
  try { rawSel = finder(t); }
  catch (err) {
    window.parent.postMessage({type: 'picker:err', error: 'finder fail: ' + (err && err.message)}, '*');
    return;
  }
  const rowSel = _normalizeSelector(rawSel);
  const matched = _safeQueryAll(rowSel);
  _outlineMatched(matched);
  const sample = matched[0] || t;
  const fields = _heuristicFields(sample);
  window.parent.postMessage({
    type: 'picker:row-auto',
    raw_selector: rawSel,
    row_selector: rowSel,
    n_matched: matched.length,
    ascended: t !== rawT,
    fields,
  }, '*');
}

function _handleFieldClick(t, fieldName) {
  let sel = '';
  try { sel = finder(t); }
  catch (err) { sel = '/* finder err: ' + (err && err.message) + ' */'; }
  const linkEl = t.tagName === 'A' ? t : (t.closest && t.closest('a'));
  window.parent.postMessage({
    type: 'picker:field',
    field: fieldName,
    selector: sel,
    text: (t.innerText || t.textContent || '').slice(0, 200),
    href: linkEl ? linkEl.href : null,
    tag: (t.tagName || '').toLowerCase(),
  }, '*');
}

function pickAndPost(e) {
  e.preventDefault();
  e.stopImmediatePropagation();
  if (mode === 'idle') {
    window.parent.postMessage({type: 'picker:nomode'}, '*');
    return;
  }
  const t = e.target;
  if (!t) return;
  if (mode === 'row') {
    _handleRowClick(t);
  } else if (mode.startsWith('field:')) {
    _handleFieldClick(t, mode.split(':')[1]);
  }
}

document.addEventListener('click', pickAndPost, true);
document.addEventListener('auxclick', pickAndPost, true);

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
    // box-shadow 가 matched outline 과 겹칠 수 있어 hover 만 clear — matchedOutlineRows
    // 의 box-shadow 는 _outlineMatched 가 다시 박는다.
    lastHovered.style.removeProperty('box-shadow');
    lastHovered = null;
  }
}

console.log('[picker] loaded — modes: row | field:<name> | idle');
