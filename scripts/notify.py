"""발송 helper 라이브러리 — 본문 텍스트화 / LLM 요약 / 필터 / 메시지 포맷 / 다이제스트 청크.

ADR 0006 이전엔 이 파일이 realtime 즉시 발송 CLI(`main()` + collected 처리 + flush_digests +
heartbeat)도 겸했지만, 폴링↔발송 분리(ADR 0006)로 그 경로는 폐지됐다 — 발송은 이제 봇 내부 1분
tick(`bot/delivery_tick.py`)이 수신처 발송 시각 도래 시 `scripts/deliver_due.py` 로 한다.

지금 이 모듈은 *순수 helper* 만 남긴다 (단일 진실원천 — 발송 로직 중복 X):
  - `summarize_post` / `filter_pass` / `digest_chunks` → `scripts/deliver_due.py` 가 import.
  - `format_message` / `summarize_post` → `bot/site_ops.py` 가 import.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generate import LLMClient, LLMError, parse_json  # noqa: E402
from generate.prompts import load_prompt, render_prompt  # noqa: E402
from bot.messages import render as msg  # noqa: E402
from engine.tracing import current_trace  # noqa: E402


# --------------------------------------------------------------------------- #
# 본문 → 텍스트 / 요약 / 필터 / 포맷
# --------------------------------------------------------------------------- #
def body_text_from_html(html: Optional[str], limit: int = 6000) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text("\n", strip=True)[:limit]


# 프롬프트 본문은 repo 루트 prompts/notify_*.txt 에 산다 (generate/prompts.py 가 로드/치환).
SUMMARY_SYSTEM = load_prompt("notify_summary.system")
FILTER_SYSTEM = load_prompt("notify_filter.system")


def summarize_post(client: LLMClient, post: dict, *, slug: Optional[str] = None) -> str:
    title = (post.get("title") or "").strip()
    body = body_text_from_html(post.get("content_html"))
    if len(body) < 30:
        return body or title or "(내용 없음)"
    user_text = render_prompt("notify_summary.user", title=title, body=body)
    tr = current_trace()
    with tr.span("summarize_llm",
                 attrs={"slug": slug, "post_id": str(post.get("post_id")),
                        "body_chars": len(body)}) as sp:
        try:
            resp = client.generate(system_instruction=SUMMARY_SYSTEM, user_text=user_text,
                                   temperature=0.3, json_mode=False,
                                   call_site="notify_summarize", slug=slug)
            sp.set_attr("model", getattr(resp, "model", None))
            s = resp.text.strip()
            return s or (body[:400] + ("…" if len(body) > 400 else ""))
        except LLMError as e:
            sp.set_attr("fallback", "body_excerpt")
            sp.set_attr("err_short", type(e).__name__)
            print(f"  [warn] LLM 요약 실패({post.get('post_id')}), 본문 발췌로 폴백: {e}", file=sys.stderr)
            return body[:400] + ("…" if len(body) > 400 else "")


def filter_pass(client: LLMClient, filter_prompt: str, post: dict, summary: str,
                *, slug: Optional[str] = None) -> bool:
    title = (post.get("title") or "").strip()
    cat = post.get("category") or ""
    user_text = render_prompt("notify_filter.user", filter_prompt=filter_prompt,
                              title=title, category=cat, summary=summary)
    tr = current_trace()
    with tr.span("filter_llm",
                 attrs={"slug": slug, "post_id": str(post.get("post_id"))}) as sp:
        try:
            resp = client.generate(system_instruction=FILTER_SYSTEM, user_text=user_text,
                                   temperature=0.0, json_mode=True,
                                   call_site="notify_filter", slug=slug)
            sp.set_attr("model", getattr(resp, "model", None))
            res = parse_json(resp.text)
            passed = bool(res.get("include", True)) if isinstance(res, dict) else True
            sp.set_attr("passed", passed)
            return passed
        except (LLMError, Exception) as e:  # noqa: BLE001
            sp.set_attr("err_short", type(e).__name__)
            sp.set_attr("fallback", "pass_through")
            print(f"  [warn] 필터 판단 실패({post.get('post_id')}) → 통과시킴: {e}", file=sys.stderr)
            return True  # fail-open


def format_message(post: dict, summary: str) -> str:
    title = (post.get("title") or "(제목 없음)").strip()
    url = post.get("url") or ""
    date_short = (post.get("published_at") or "")[:10]
    cat = post.get("category")
    head = msg("notify_alert_head_cat", cat=cat, title=title) if cat else msg("notify_alert_head", title=title)
    lines = [head]
    if date_short:
        lines.append(msg("notify_alert_date", date=date_short))
    if url:
        lines.append(msg("notify_alert_url", url=url))
    if summary:
        lines.append(msg("notify_alert_summary", summary=summary))
    return "\n".join(lines)


def digest_chunks(rows: list, *, max_len: int = 1850) -> list[str]:
    """글 행들(slug,post_id,title,url,published_at,summary) → 다이제스트 메시지(들)."""
    header = msg("notify_digest_header", count=len(rows))
    blocks: list[str] = []
    for r in rows:
        t = (r["title"] or "(제목 없음)").strip()
        d = (r["published_at"] or "")[:10]
        u = r["url"] or ""
        s = (r["summary"] or "").strip()
        b = f"• **{t}**" + (f"  ({d})" if d else "") + (f"\n  <{u}>" if u else "") + (f"\n  {s}" if s else "")
        blocks.append(b)
    chunks: list[str] = []
    cur = header
    for b in blocks:
        if len(cur) + 2 + len(b) > max_len:
            chunks.append(cur)
            cur = b
        else:
            cur = cur + "\n\n" + b
    if cur:
        chunks.append(cur)
    return chunks
