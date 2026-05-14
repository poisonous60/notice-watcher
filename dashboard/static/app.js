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
