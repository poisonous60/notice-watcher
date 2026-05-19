"""probe.extract.root_marketing_homepage — root 도메인 마케팅 랜딩/허브 페이지 검출.

트리거 조건 (AND):
  1. URL path == '/' (또는 빈 path)
  2. html_repeating_patterns top7 중 nav/footer/header/dropdown/subnav/menu/carousel/swiper/
     tile/promo/hero/banner 키워드 ≥ 2
  3. nav_only_same_host.total_same_host ≤ 15 (또는 None) — 진짜 article-grid root false-positive 차단

scripts/register.py `_root_marketing_homepage_check` gate 가 이 신호 보고 LLM 호출 전 REJECTED.

false-positive 0 필수 — 진짜 board (HackerNews 류 root article list, 카테고리 path 등) 절대 거부 X.
"""
from __future__ import annotations


def _patterns(*selectors_with_count) -> list[dict]:
    """fixture 만들기 — (selector, child_count) 튜플 리스트 → html_repeating_patterns 형식 dict 리스트."""
    return [{"selector": s, "child_count": c, "sample_url": None} for s, c in selectors_with_count]


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import root_marketing_homepage

    cases: list[tuple[str, bool, str]] = []

    # 1. CNN root (실제 probe 신호 reproduce) — nav-heavy + total_same_host=8 → 매칭.
    cnn_patterns = _patterns(
        ("head > script", 53),
        ("head > link", 38),
        ("head > meta", 25),
        ("ul.container__field-links.container_vertical-shelf-carousel__field-links > li.card", 25),
        ("ul.subnav__sections > li.subnav__section", 21),
        ("div.header__nav-container > div.header__nav-item", 16),
        ("div.header__nav-item-dropdown-inner > a.header__nav-item-dropdown-item", 16),
    )
    out = root_marketing_homepage(
        base_url="https://edition.cnn.com/",
        html_candidates=cnn_patterns,
        nav_only_same_host={"base_host": "edition.cnn.com", "total_same_host": 8,
                            "in_nav": 5, "outside_nav": 3, "nav_only_same_host": False,
                            "sample_nav_ancestors": ["nav", "nav", "nav"]},
        body_empty_likely=False,
    )
    cases.append(("cnn_root_matches",
                  out is not None and out["is_root_marketing_homepage"] is True
                  and out["marketing_hits"] >= 2,
                  f"got {out!r}"))

    # 2. NatGeo root (carousel 우세) — total_same_host=4 → 매칭.
    natgeo_patterns = _patterns(
        ("div.SwiperWrapper > div.SwiperSlide.TileStackCarousel__Card", 49),
        ("div.swipper__DotWrapper > span.Swiper__DotContainer__Dot", 49),
        ("head > meta", 43),
        ("ul.Carousel__Inner.flex.CarouselModule__Inner--padding > li.CarouselSlide", 15),
        ("ul > li.GlobalFooter__Menu__List__Item", 13),
    )
    out = root_marketing_homepage(
        base_url="https://www.nationalgeographic.com/",
        html_candidates=natgeo_patterns,
        nav_only_same_host={"base_host": "www.nationalgeographic.com", "total_same_host": 4,
                            "in_nav": 1, "outside_nav": 3, "nav_only_same_host": False,
                            "sample_nav_ancestors": ["aside"]},
        body_empty_likely=False,
    )
    cases.append(("natgeo_root_matches",
                  out is not None and out["is_root_marketing_homepage"] is True
                  and out["marketing_hits"] >= 2,
                  f"got {out!r}"))

    # 3. Reuters root — body_empty + nav-heavy.
    reuters_patterns = _patterns(
        ("ul.nav-dropdown-module__subsections__ElxDL > li", 11),
        ("ul.link-group-module__list > li.link-group-module__item", 11),
        ("#vertical_homepage-VideoShortsCarouselContainer > li", 10),
        ("ul.nav-dropdown-module__sections-group > li", 8),
    )
    out = root_marketing_homepage(
        base_url="https://www.reuters.com/",
        html_candidates=reuters_patterns,
        nav_only_same_host={"base_host": "www.reuters.com", "total_same_host": 8,
                            "in_nav": 5, "outside_nav": 3, "nav_only_same_host": False,
                            "sample_nav_ancestors": ["nav", "footer", "nav"]},
        body_empty_likely=True,
    )
    cases.append(("reuters_root_matches",
                  out is not None and out["is_root_marketing_homepage"] is True
                  and out["body_empty_likely"] is True,
                  f"got {out!r}"))

    # 4. Vimeo root — nav_only_same_host=None (=같은-host article rows 0건) → total_same=0 통과.
    vimeo_patterns = _patterns(
        ("body > script", 66),
        ("head > meta", 36),
        ("div > a.no-underline.flex.text-footer-sub-content", 12),
        ("div.flex.flex-col.gap-1 > a.no-underline.text-footer-sub-content", 12),
    )
    out = root_marketing_homepage(
        base_url="https://vimeo.com/",
        html_candidates=vimeo_patterns,
        nav_only_same_host=None,
        body_empty_likely=False,
    )
    cases.append(("vimeo_root_matches",
                  out is not None and out["is_root_marketing_homepage"] is True
                  and out["marketing_hits"] >= 2,
                  f"got {out!r}"))

    # 5. false-positive 가드 — 진짜 article-grid board (HackerNews 류) — total_same_host=30, 마케팅
    # 키워드 적음 → None.
    hn_patterns = _patterns(
        ("table.itemlist > tr.athing", 30),  # 마케팅 키워드 X
        ("table.fatitem > tr", 8),
    )
    out = root_marketing_homepage(
        base_url="https://news.ycombinator.com/",
        html_candidates=hn_patterns,
        nav_only_same_host={"base_host": "news.ycombinator.com", "total_same_host": 30,
                            "in_nav": 0, "outside_nav": 30, "nav_only_same_host": False,
                            "sample_nav_ancestors": []},
        body_empty_likely=False,
    )
    cases.append(("hn_root_does_not_match", out is None, f"got {out!r}"))

    # 6. false-positive 가드 — 진짜 article-grid 인데 nav 도 많은 사이트 (total_same_host=30) → None.
    article_grid_patterns = _patterns(
        ("main.feed > article.card", 50),
        ("nav.topnav > a", 10),  # nav 있음
        ("footer.f > a", 8),     # footer 있음
    )
    out = root_marketing_homepage(
        base_url="https://big-news.example.com/",
        html_candidates=article_grid_patterns,
        nav_only_same_host={"base_host": "big-news.example.com", "total_same_host": 30,
                            "in_nav": 10, "outside_nav": 20, "nav_only_same_host": False,
                            "sample_nav_ancestors": ["nav", "footer"]},
        body_empty_likely=False,
    )
    cases.append(("big_news_grid_root_blocked_by_total_guard",
                  out is None, f"got {out!r}"))

    # 7. 카테고리 path (root 아님) — path='/world/' → None (path != '/').
    out = root_marketing_homepage(
        base_url="https://edition.cnn.com/world/",
        html_candidates=cnn_patterns,
        nav_only_same_host={"base_host": "edition.cnn.com", "total_same_host": 8,
                            "in_nav": 5, "outside_nav": 3, "nav_only_same_host": False,
                            "sample_nav_ancestors": ["nav"]},
        body_empty_likely=False,
    )
    cases.append(("category_path_not_root", out is None, f"got {out!r}"))

    # 8. marketing_hits < 2 → None.
    plain_patterns = _patterns(
        ("ul.posts > li.post", 20),
        ("article.entry", 10),
    )
    out = root_marketing_homepage(
        base_url="https://plain.example.com/",
        html_candidates=plain_patterns,
        nav_only_same_host={"base_host": "plain.example.com", "total_same_host": 5,
                            "in_nav": 0, "outside_nav": 5, "nav_only_same_host": False,
                            "sample_nav_ancestors": []},
        body_empty_likely=False,
    )
    cases.append(("no_marketing_keywords_returns_none", out is None, f"got {out!r}"))

    # 9. html_candidates 비어있으면 → None.
    out = root_marketing_homepage(
        base_url="https://example.com/",
        html_candidates=[],
        nav_only_same_host=None,
        body_empty_likely=False,
    )
    cases.append(("empty_html_candidates_returns_none", out is None, f"got {out!r}"))

    # 10. base_url 없음 → None.
    out = root_marketing_homepage(
        base_url="",
        html_candidates=cnn_patterns,
        nav_only_same_host=None,
        body_empty_likely=False,
    )
    cases.append(("empty_base_url_returns_none", out is None, f"got {out!r}"))

    return cases
