// 클립보드 복사 + 토스트.
// 사용: <button data-copy-target="#prompt-N">복사</button>
//      <pre id="prompt-N">...</pre>
// 또는: <button data-copy-text="...">복사</button>

(function () {
  function toast(msg, ms) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.hidden = true; }, ms || 2500);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      // fallback (older browser / non-secure context)
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.top = '-1000px';
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
      document.body.removeChild(ta);
      return ok;
    }
  }

  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-copy-target], [data-copy-text]');
    if (!btn) return;
    let text = btn.dataset.copyText;
    if (!text && btn.dataset.copyTarget) {
      const tgt = document.querySelector(btn.dataset.copyTarget);
      if (tgt) text = tgt.textContent;
    }
    if (!text) { toast('복사할 내용 없음'); return; }
    const ok = await copyText(text);
    toast(ok ? '✅ 복사됨. Claude 창에 Ctrl+V' : '⚠️ 복사 실패');
  });
})();

// /subs 검색은 이미 받은 테이블 행만 숨김/표시한다.
(function () {
  function applySubsFilter(root) {
    const input = document.querySelector('[data-subs-search]');
    const rows = Array.from(document.querySelectorAll('[data-subs-row]'));
    const count = document.querySelector('[data-subs-count]');
    const empty = document.querySelector('[data-subs-empty]');
    if (!input || rows.length === 0) return;

    const q = (input.value || '').trim().toLowerCase();
    let visible = 0;
    rows.forEach((row) => {
      const haystack = row.dataset.search || '';
      const matched = !q || haystack.includes(q);
      row.hidden = !matched;
      if (matched) visible += 1;
    });
    if (count) count.textContent = String(visible);
    if (empty) empty.hidden = visible !== 0;
  }

  function bindSubsFilter(root) {
    const scope = root || document;
    const input = scope.querySelector ? scope.querySelector('[data-subs-search]') : null;
    const form = scope.querySelector ? scope.querySelector('[data-subs-filters]') : null;
    const searchButton = scope.querySelector ? scope.querySelector('[data-subs-search-submit]') : null;
    if (!input || input.dataset.boundSubsSearch === '1') return;
    input.dataset.boundSubsSearch = '1';

    input.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        applySubsFilter(document);
      }
    });
    if (searchButton) {
      searchButton.addEventListener('click', () => applySubsFilter(document));
    }

    if (form) {
      form.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
        checkbox.addEventListener('change', () => {
          if (form.requestSubmit) form.requestSubmit();
          else form.submit();
        });
      });
    }
    applySubsFilter(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => bindSubsFilter(document));
  } else {
    bindSubsFilter(document);
  }
  document.addEventListener('htmx:afterSwap', (ev) => bindSubsFilter(ev.target));
})();
