"""생성된 config 의 *실행 검증* (3층위).

층위 1 — 내부 일관성 (하드): fetch_list 동작 / ≥1건 / post_id 유니크·비어있지 않음·안정적 모양 /
         title 비어있지 않음 / published_at(있으면) ISO8601 파싱 / 첫 글 본문 ≥100자(또는 전부 skip).
층위 2 — probe 교차검증 (소프트=경고): 생성 목록의 글 URL 이 probe 의 first_article_url 과 관련 있나 /
         건수가 probe 후보 child_count 와 같은 ballpark 인가.

ValidationReport.ok = 층위1 하드 체크 전부 통과. 층위2 는 정보/경고용(ok 안 뒤집음).
실패 리포트는 generator 의 재시도 피드백(M5)에 그대로 쓰인다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlsplit

from engine import make_adapter, NoticePost
from engine.extract_helpers import parse_html
from engine.tracing import current_trace


_STABLE_ID_RE = re.compile(r"^[\w\-./:%]{1,200}$")  # 공백 없는 정수/문자열 ID. 'title with spaces' 같은 실수 차단.
# 200 cap = 메이저 뉴스미디어의 date+title-slug URL path 패턴 수용 (CNN/NYT/WaPo/Reuters 류, ≤130자 관측). 64 cap 은 URL-slug-as-id 정상 케이스를 차단했다.

# row_selector 가 네비게이션/메뉴 chrome 을 지목 — 글 목록 아님(nav junk) 신호 (ADR 0011 fix A).
# 정밀 토큰만: <nav> 단독 태그, menubar/navbar/p-menubar/breadcrumb, [role=navigation].
# 'menu' 단독은 과매칭(.dropdown-menu 등)이라 제외. 단독 사용 X — 항상 conjunction(날짜0+숫자0)과 함께.
_NAV_SELECTOR_RE = re.compile(
    r"(?:^|[\s>~+])nav(?=[\s>~+.:#\[]|$)"      # <nav> 요소 (태그 경계)
    r"|menubar|navbar|p-menubar|breadcrumb"     # 메뉴바/브레드크럼 컴포넌트
    r"|role\s*=\s*['\"]?navigation",            # [role=navigation]
    re.I,
)


def _is_nav_junk_rows(row_selector: str, post_ids: list[str], any_dated: bool) -> bool:
    """row_selector 가 nav/메뉴 chrome 을 가리키고 항목에 날짜·숫자가 전혀 없으면 nav junk (글 목록 아님).
    conjunction 으로 false-reject 방지: clojure(`nav.w-nav-menu` 인데 dated 뉴스 — id 에 숫자) ·
    version-board(bun-v1.3.14 — nav-token 없음) 는 면제."""
    if not post_ids or not _NAV_SELECTOR_RE.search(row_selector or ""):
        return False
    if any_dated:
        return False
    return not any(any(c.isdigit() for c in i) for i in post_ids)


def _is_year_archive(post_ids: list[str]) -> bool:
    """post_id 가 전부 4자리 *그럴듯한 연도* 뿐 → 연도 아카이브 인덱스(개별 글 아님). netbsd 2025/2024/2023 류.

    "그럴듯한 연도" = 1990..2030 범위. 그 외 4자리 (Discourse topic id 5619/6976/7022 같은 것)
    는 *연도가 아니므로* 연도 아카이브로 보지 X — false-positive 봉합 (2026-05-23 crypto batch
    의 forum.safe.global / celestia / thegraph 가 Discourse topic id 5000~9000 영역이라
    이 게이트에 잘못 걸려 DiscourseAdapter 폴백 후 LLM 실패).
    """
    if not post_ids:
        return False
    for raw in post_ids:
        m = re.fullmatch(r"\s*(\d{4})\s*", raw or "")
        if m is None:
            return False
        year = int(m.group(1))
        if not (1990 <= year <= 2030):
            return False
    return True


@dataclass
class Check:
    name: str
    ok: bool
    hard: bool
    detail: str = ""


@dataclass
class ValidationReport:
    ok: bool = False
    checks: list[Check] = field(default_factory=list)
    n_posts: int = 0
    all_post_ids: list[str] = field(default_factory=list)  # fetch_list 결과 전체 post_id (baseline 용)
    sample_posts: list[dict] = field(default_factory=list)  # 앞 몇 건 to_dict (피드백용)
    article_bodies: dict[str, int] = field(default_factory=dict)  # post_id -> body len
    error: Optional[str] = None

    def add(self, name: str, ok: bool, *, hard: bool, detail: str = "") -> None:
        self.checks.append(Check(name, ok, hard, detail))

    def hard_failures(self) -> list[Check]:
        return [c for c in self.checks if c.hard and not c.ok]

    def soft_failures(self) -> list[Check]:
        return [c for c in self.checks if not c.hard and not c.ok]

    def feedback_text(self) -> str:
        """모델 재생성 피드백용 요약."""
        lines = []
        if self.error:
            lines.append(f"실행 중 에러: {self.error}")
        for c in self.checks:
            mark = "OK " if c.ok else ("FAIL" if c.hard else "warn")
            if not c.ok:
                lines.append(f"  [{mark}] {c.name}: {c.detail}")
        if self.sample_posts:
            lines.append("실제로 추출된 앞 글들(필드 확인):")
            for sp in self.sample_posts[:5]:
                lines.append(f"  post_id={sp.get('post_id')!r} title={sp.get('title')!r} "
                             f"url={sp.get('url')!r} published_at={sp.get('published_at')!r} "
                             f"category={sp.get('category')!r}")
        if self.article_bodies:
            lines.append(f"본문 길이: " + ", ".join(f"{k}={v}자" for k, v in self.article_bodies.items()))
        return "\n".join(lines)


def _parse_iso(s: str) -> bool:
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        return False


def _norm_url(u: Optional[str]) -> str:
    if not u:
        return ""
    return u.split("#", 1)[0].rstrip("/").lower()


def _external_host_hint(post_url: Optional[str], cfg: dict) -> Optional[str]:
    """post.url host 가 list URL host (= cfg.site 또는 list.url_template 호스트) 와 다르면 hint 반환.

    검색결과/aggregator 페이지(Google Scholar, 뉴스 모음 등) 의 row url 은 외부 도메인 — article body
    통합 추출 불가. retry feedback 에 박혀 LLM 이 다음 attempt 에서 `article.skip_status:[200]` 박거나
    article 섹션 생략하도록 유도. probe 의 list_candidates.row_external_host 신호와 평행 (D-layer)."""
    if not post_url:
        return None
    from urllib.parse import urlsplit
    post_host = urlsplit(post_url).netloc
    if not post_host:
        return None
    list_url_tpl = ((cfg.get("list") or {}).get("url_template") or "")
    list_host = urlsplit(list_url_tpl).netloc or str(cfg.get("site") or "")
    if not list_host:
        return None
    if post_host == list_host:
        return None
    return (f"post.url host={post_host!r} 가 list host={list_host!r} 와 다름 — 검색결과/aggregator 가능성. "
            f"article body 통합 추출 X. article.skip_status:[200] 박아 본문 fetch 즉시 skip 또는 "
            f"article 섹션 생략. 알림은 list.fields 의 title/url/author/summary 로 충분.")


def _expected_count_hint(digest: Optional[dict]) -> Optional[int]:
    if not digest:
        return None
    lc = digest.get("list_candidates") or {}
    best = 0
    for c in (lc.get("html_repeating_patterns") or []):
        n = c.get("child_count") or 0
        # head>meta(18) 같은 노이즈 후보 제외 — 글 목록은 보통 anchor 가 있음
        if c.get("sample_url") and 5 <= n <= 300:
            best = max(best, n)
    for c in (lc.get("traffic_json_api_candidates") or []):
        n = c.get("count") or c.get("child_count") or 0
        if 5 <= n <= 300:
            best = max(best, n)
    return best or None


def _digest_html_safe(section: Any) -> bool:
    """True when digest HTML is complete enough to use as hard evidence.

    Agentic workdirs may contain prompt-compressed HTML. That is useful for the
    model, but not safe as negative evidence because repeated rows can be
    collapsed or the sample can be char-capped without the original digest
    `truncated` flag changing.
    """
    if not isinstance(section, dict):
        return False
    html = section.get("html")
    if not isinstance(html, str) or not html.strip():
        return False
    if section.get("truncated") or section.get("prompt_compressed"):
        return False
    if "<!-- [digest] HTML truncated -->" in html or "<!-- collapsed " in html:
        return False
    return True


def _selector_count(html: str, selector: str) -> Optional[int]:
    if not selector or selector == ":self":
        return None
    try:
        return len(parse_html(html).select(selector))
    except Exception:
        return None


def _source_basename(section: Any) -> str:
    if not isinstance(section, dict):
        return ""
    raw = str(section.get("source") or "")
    return raw.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _rendered_list_evidence(section: Any) -> bool:
    return _source_basename(section) in {"list.html", "list.captured.html"}


def _rendered_article_evidence(section: Any) -> bool:
    return _source_basename(section) in {"article_click.html", "article.captured.html"}


def _content_css_selectors(specs: Any) -> list[str]:
    out: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, list):
            for item in v:
                walk(item)
            return
        if not isinstance(v, dict):
            return
        if v.get("from") == "css" and isinstance(v.get("selector"), str):
            out.append(v["selector"])

    walk(specs)
    return out


def _norm_ground_url(u: Optional[str]) -> str:
    if not u:
        return ""
    placeholder = "__SCHEME_SEP__"
    return re.sub(r"/+", "/", u.split("#", 1)[0].rstrip("/").lower().replace("://", placeholder)).replace(placeholder, "://")


def _url_template_matches(template: str, url: str) -> bool:
    if not template or not url:
        return False
    t = _norm_ground_url(template)
    u = _norm_ground_url(url)
    if t == u:
        return True
    pattern = re.escape(t)
    for key in ("post_id", "id", "board", "page"):
        pattern = pattern.replace(r"\{" + key + r"\}", r"[^/?#&]+")
    return re.fullmatch(pattern, u) is not None


def _same_endpoint_family(template: str, url: str) -> bool:
    try:
        tt = urlsplit(template.replace("{post_id}", "0"))
        uu = urlsplit(url)
    except Exception:
        return False
    if not tt.netloc or tt.netloc.lower() != uu.netloc.lower():
        return False
    t_path = re.sub(r"\{post_id\}|\d+", "*", tt.path.rstrip("/").lower())
    u_path = re.sub(r"\d+", "*", uu.path.rstrip("/").lower())
    return t_path == u_path


def _article_api_grounded(template: str, candidates: list[Any]) -> bool:
    urls = [str(c.get("url") or "") for c in candidates if isinstance(c, dict)]
    return any(_url_template_matches(template, u) or _same_endpoint_family(template, u) for u in urls)


def _add_probe_grounding_checks(rep: ValidationReport, cfg: dict, digest: Optional[dict]) -> None:
    """Fail fast on generated candidates that contradict concrete probe evidence.

    This is deliberately a narrow guardrail, not a strategy override. Missing or
    compressed evidence is treated as unknown so existing configs and legitimate
    inferred selectors keep the old validation path.
    """
    if not isinstance(digest, dict):
        return

    strategy = str(cfg.get("strategy") or "")
    lst = cfg.get("list") or {}
    art = cfg.get("article") or {}
    list_html = digest.get("list_html") or {}
    article_sample = digest.get("article_sample") or {}

    if _digest_html_safe(list_html):
        html = str(list_html.get("html") or "")
        row_selector = str(lst.get("row_selector") or "")
        list_negative_is_safe = strategy != "playwright_html" or _rendered_list_evidence(list_html)
        if row_selector and list_negative_is_safe:
            n = _selector_count(html, row_selector)
            if n == 0:
                rep.add(
                    "probe_grounding_list_row_selector",
                    False,
                    hard=True,
                    detail=f"row_selector {row_selector!r} matched 0 nodes in probe list_html; choose a selector grounded in digest evidence",
                )
        wait_selector = str(lst.get("wait_selector") or "")
        if strategy == "playwright_html" and wait_selector and _rendered_list_evidence(list_html):
            n = _selector_count(html, wait_selector)
            if n == 0:
                rep.add(
                    "probe_grounding_list_wait_selector",
                    False,
                    hard=True,
                    detail=f"list.wait_selector {wait_selector!r} matched 0 nodes in probe list_html; this would burn Playwright selector wait",
                )

    article_negative_is_safe = strategy != "playwright_html" or _rendered_article_evidence(article_sample)

    if strategy == "playwright_html" and _digest_html_safe(article_sample) and _rendered_article_evidence(article_sample):
        html = str(article_sample.get("html") or "")
        wait_selector = str(art.get("wait_selector") or "")
        if wait_selector:
            n = _selector_count(html, wait_selector)
            if n == 0:
                rep.add(
                    "probe_grounding_article_wait_selector",
                    False,
                    hard=True,
                    detail=f"article.wait_selector {wait_selector!r} matched 0 nodes in probe article_sample.html; this would burn Playwright selector wait",
                )

    if str(art.get("fetch_kind") or "html") != "json" and not art.get("body_empty_acceptable"):
        if _digest_html_safe(article_sample) and article_negative_is_safe:
            html = str(article_sample.get("html") or "")
            selectors = [s for s in _content_css_selectors(art.get("content")) if s and s != ":self"]
            if selectors:
                hits = [(s, _selector_count(html, s)) for s in selectors]
                if all(n == 0 for _, n in hits):
                    rep.add(
                        "probe_grounding_article_content_selector",
                        False,
                        hard=True,
                        detail="article.content CSS selectors matched 0 nodes in probe article_sample.html: "
                               + ", ".join(repr(s) for s, _ in hits[:5]),
                    )

    if str(art.get("fetch_kind") or "") == "json":
        candidates = article_sample.get("api_candidates") or []
        template = str(art.get("url_template") or "")
        if template and isinstance(candidates, list) and candidates:
            useful = [
                c for c in candidates
                if isinstance(c, dict) and c.get("url") and (c.get("url_id_match") or c.get("body_looks_html") or c.get("body_field_path"))
            ]
            if useful and not _article_api_grounded(template, useful):
                rep.add(
                    "probe_grounding_article_json_api",
                    False,
                    hard=True,
                    detail=f"article JSON url_template {template!r} is not grounded in article_sample.api_candidates",
                )


async def validate_built_config(
    cfg: dict,
    *,
    digest: Optional[dict] = None,
    fetch_articles: int = 1,
    list_page_size: int = 30,
    existing_posts: Optional[list[NoticePost]] = None,
) -> ValidationReport:
    """existing_posts 주면 fetch_list 재호출 안 함 (caller 가 이미 받은 결과 재사용)."""
    rep = ValidationReport()
    tr = current_trace()
    try:
        with tr.span("validate_build_adapter", attrs={"strategy": cfg.get("strategy")}):
            adapter = make_adapter(cfg)
    except Exception as e:
        rep.error = f"make_adapter 실패: {type(e).__name__}: {e}"
        rep.add("build_adapter", False, hard=True, detail=rep.error)
        return rep

    _add_probe_grounding_checks(rep, cfg, digest)
    if rep.hard_failures():
        rep.ok = False
        return rep

    posts: list[NoticePost] = []
    try:
        async with adapter as a:
            if existing_posts is not None:
                posts = existing_posts
            else:
                with tr.span("validate_fetch_list", attrs={"page_size": list_page_size}):
                    posts = await a.fetch_list(page=1, page_size=list_page_size)
            rep.n_posts = len(posts)
            rep.all_post_ids = [str(p.post_id) for p in posts]
            rep.sample_posts = [p.to_dict() for p in posts[:5]]
            rep.add("fetch_list", True, hard=True, detail=f"{len(posts)}건")

            # 본문 — skip_status(접근제한)로 비워진 글은 건너뛰고 다음 글 시도. "진짜 본문" 하나 검증되면 충분.
            # article.body_empty_acceptable=true 면 본문 길이 검증을 hard=False 로 완화 (본문이 본질적으로 없는 사이트 opt-in).
            body_optional = bool((cfg.get("article") or {}).get("body_empty_acceptable"))
            if posts and fetch_articles > 0:
                want = max(1, fetch_articles)
                budget = min(len(posts), want + 1)  # skip 대비 1건 여유. agentic validator 에서 5-page burn 방지.
                real_seen = 0
                verdict_added = False
                for p in posts[:budget]:
                    try:
                        with tr.span("validate_fetch_article", attrs={"post_id": str(p.post_id)}):
                            full = await a.fetch_article(p)
                    except Exception as e:
                        rep.add(f"fetch_article[{p.post_id}]", False, hard=False, detail=f"{type(e).__name__}: {e}")
                        continue
                    blen = len(full.content_html or "")
                    rep.article_bodies[p.post_id] = blen
                    if blen == 0 and (full.raw or {}).get("fetch_note"):
                        continue  # 접근제한 글 — 다음 글로
                    real_seen += 1
                    ok = blen >= 100
                    detail = f"post_id={p.post_id} {blen}자"
                    if not ok:
                        ext_hint = _external_host_hint(p.url, cfg)
                        detail += " (<100 — content selector 의심)"
                        if ext_hint:
                            detail += f" / {ext_hint}"
                    if body_optional and not ok:
                        rep.add("article_body_len", True, hard=False,
                                detail=detail + " — body_empty_acceptable=true 로 완화 (본문 없는 사이트 opt-in)")
                    else:
                        rep.add("article_body_len", ok, hard=True, detail=detail)
                    ch = full.content_html or ""
                    if "<nav" in ch and "<footer" in ch:
                        rep.add("article_body_chrome", False, hard=False,
                                detail="content 에 <nav>+<footer> 둘 다 있음 — 페이지 통째 긁었을 수 있음")
                    verdict_added = True
                    if real_seen >= want:
                        break
                if not verdict_added:
                    # 진짜 본문 글을 하나도 못 봄
                    if rep.article_bodies and all(v == 0 for v in rep.article_bodies.values()):
                        rep.add("article_body_len", True, hard=False, detail="첫 글들이 전부 접근제한(skip_status) — 본문 검증 보류")
                    elif body_optional:
                        rep.add("article_body_len", True, hard=False,
                                detail="fetch_article 로 본문을 못 얻음 — body_empty_acceptable=true 로 완화")
                    else:
                        rep.add("article_body_len", False, hard=True, detail="fetch_article 로 본문을 못 얻음")
    except Exception as e:
        rep.error = f"실행 실패: {type(e).__name__}: {e}"
        rep.add("fetch_list", False, hard=True, detail=rep.error)
        return rep

    # 층위 1 — 목록 일관성
    rep.add("posts_nonempty", len(posts) >= 1, hard=True, detail=f"{len(posts)}건")
    ids = [str(p.post_id) for p in posts]
    rep.add("post_id_nonempty", all(i.strip() for i in ids), hard=True,
            detail="비어있는 post_id 있음" if not all(i.strip() for i in ids) else "")
    rep.add("post_id_unique", len(set(ids)) == len(ids), hard=True,
            detail=f"중복 {len(ids) - len(set(ids))}건" if len(set(ids)) != len(ids) else "")
    bad_shape = [i for i in ids if not _STABLE_ID_RE.match(i)]
    rep.add("post_id_stable_shape", not bad_shape, hard=True,
            detail=f"안정적 ID 모양 아님(공백 등): {bad_shape[:5]}" if bad_shape else "")
    empty_titles = [p.post_id for p in posts if not (p.title and p.title.strip())]
    rep.add("title_nonempty", not empty_titles, hard=True,
            detail=f"title 빈 글: {empty_titles[:5]}" if empty_titles else "")
    dated = [p.published_at for p in posts if p.published_at]
    bad_dates = [d for d in dated if not _parse_iso(d)]
    rep.add("published_at_iso", not bad_dates, hard=True,
            detail=f"ISO8601 파싱 실패: {bad_dates[:3]}" if bad_dates else (f"{len(dated)}/{len(posts)} 글에 날짜 있음" if dated else "날짜 추출된 글 없음(허용)"))

    # 층위 1b — nav/연도-아카이브 *오추출* false-accept 차단 (ADR 0011 직교 트랙).
    # 글-board 인데 row_selector 가 nav/메뉴 chrome 을 가리키거나(openbsd `nav>ul>li`·garuda
    # `p-menubar-item`) 항목이 연도 인덱스(netbsd 2025/2024/2023)면 폴링해도 nav junk·연도링크만 잡음.
    # hard fail → retry feedback 으로 LLM 이 진짜 글 목록 재선택 기회 (없으면 gen_fail → hand-config).
    # nav 는 conjunction(nav-selector AND 날짜 0 AND post_id 숫자 0) 으로 좁혀 false-reject 방지:
    #   clojure(`nav.w-nav-menu` 인데 dated 뉴스 — id 에 2026 숫자) · version-board(bun-v1.3.14 — nav-token 없음) 면제.
    row_sel = str((cfg.get("list") or {}).get("row_selector") or "")
    nav_junk = _is_nav_junk_rows(row_sel, ids, any(p.published_at for p in posts))
    nav_sel = _NAV_SELECTOR_RE.search(row_sel)
    rep.add("row_selector_not_nav", not nav_junk, hard=True,
            detail=(f"row_selector 가 nav/메뉴 chrome 지목({nav_sel.group(0)!r}) + 항목 날짜·숫자 0 → 글 목록 아닌 nav junk: {ids[:5]} (진짜 글 목록의 row_selector 를 다시 찾아라)" if nav_junk else ""))
    year_only = _is_year_archive(ids)
    rep.add("post_id_not_year_archive", not year_only, hard=True,
            detail=(f"post_id 전부 연도뿐 → 연도 아카이브 인덱스(글 아님): {ids[:5]} (개별 글 행을 가리키는 row_selector 로 바꿔라)" if year_only else ""))

    # 층위 2 — probe 교차검증 (소프트)
    if digest:
        lc = digest.get("list_candidates") or {}
        fau = _norm_url(lc.get("first_article_url"))
        if fau:
            urls = {_norm_url(p.url) for p in posts if p.url}
            related = fau in urls or any(fau and (fau in u or u in fau) for u in urls if u)
            rep.add("matches_probe_first_article", related, hard=False,
                    detail=("" if related else f"probe first_article_url={lc.get('first_article_url')!r} 와 일치하는 글 URL 없음"))
        hint = _expected_count_hint(digest)
        if hint:
            rep.add("count_ballpark", len(posts) >= max(1, int(hint * 0.2)), hard=False,
                    detail=f"{len(posts)}건 (probe 후보 child_count≈{hint})")

    rep.ok = not rep.hard_failures()
    return rep
