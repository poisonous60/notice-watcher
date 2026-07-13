"""probe.extract.html_repeating_patterns — 시그니처 그룹핑 + href 수집."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import html_repeating_patterns

    cases: list[tuple[str, bool, str]] = []

    # 1. 정적 글 목록 — ul.list > li.item × 6
    html = '<ul class="list">' + ''.join(
        f'<li class="item"><a href="/view/{i}">title {i}</a></li>'
        for i in range(1, 7)
    ) + '</ul>'
    out = html_repeating_patterns(html, "https://x.com/board")
    cases.append(("ul_li_x6", len(out) >= 1 and out[0]["child_count"] == 6,
                  f"got {len(out)} candidates"))
    if out:
        c = out[0]
        cases.append(("sample_url_absolute",
                      c["sample_url"] == "https://x.com/view/1",
                      f"got sample_url={c.get('sample_url')!r}"))
        cases.append(("href_pattern_guess",
                      c["href_pattern_guess"] == "/view/{n}",
                      f"got {c.get('href_pattern_guess')!r}"))
        cases.append(("common_prefix",
                      c["href_common_prefix"] == "/view/",
                      f"got {c.get('href_common_prefix')!r}"))

    # 2. javascript: href + data-id 속성 (post_id 가 data-* 에 있는 케이스)
    html = '<ul class="list">' + ''.join(
        f'<li class="item" data-id="{i}"><a href="javascript:goView({i})">t{i}</a></li>'
        for i in range(1, 7)
    ) + '</ul>'
    out = html_repeating_patterns(html, "https://x.com/board")
    cases.append(("js_href_detected", len(out) >= 1 and out[0].get("href_is_js") is True,
                  f"got {out!r}"))
    if out and out[0].get("row_data_attrs"):
        cases.append(("row_data_attrs_has_id",
                      "data-id" in (out[0]["row_data_attrs"] or {}),
                      f"got {out[0]['row_data_attrs']!r}"))

    # 3. row 안 카테고리 링크가 글 링크보다 먼저 나와도 sample_url 은 글 링크를 고른다.
    html = '<ul class="list">' + ''.join(
        f'''<li class="item">
              <div><a href="/news/category/other">category</a></div>
              <a href="https://x.com/news/20260{i:03d}/"></a>
            </li>'''
        for i in range(1, 7)
    ) + '</ul>'
    out = html_repeating_patterns(html, "https://x.com/news/")
    cases.append(("prefers_article_href_over_category",
                  len(out) >= 1 and out[0]["sample_url"] == "https://x.com/news/20260001/",
                  f"got {out[0].get('sample_url') if out else None!r}"))
    if out:
        cases.append(("article_href_pattern",
                      out[0]["href_pattern_guess"] == "https://x.com/news/{n}/",
                      f"got {out[0].get('href_pattern_guess')!r}"))

    # 4. min_children — 기본 3 (rowsig-bench 2026-07-13 로 5→3 완화): 2개는 탈락, 4개는 후보.
    html2 = '<ul>' + ''.join(f'<li class="x"><a href="/v/{i}">t</a></li>' for i in range(2)) + '</ul>'
    out = html_repeating_patterns(html2, "https://x.com")
    cases.append(("too_few_children", len(out) == 0, f"got {len(out)} candidates"))
    html4 = '<ul>' + ''.join(f'<li class="x"><a href="/v/{i}">t</a></li>' for i in range(4)) + '</ul>'
    out = html_repeating_patterns(html4, "https://x.com")
    cases.append(("four_children_pass_default", len(out) == 1 and out[0]["child_count"] == 4,
                  f"got {out!r}"))
    out = html_repeating_patterns(html4, "https://x.com", min_children=5)
    cases.append(("min_children_knob_respected", len(out) == 0, f"got {len(out)} candidates"))

    # 4b. sibling_variants/merged_count — 같은 부모+태그의 클래스 변형 분열(tr.odd/tr.even) 주석.
    html_oe = '<table><tbody>' + ''.join(
        f'<tr class="{"odd" if i % 2 else "even"}"><td><a href="/post/{i}">t{i}</a></td></tr>'
        for i in range(10)
    ) + '</tbody></table>'
    out = html_repeating_patterns(html_oe, "https://x.com/board")
    oe = [c for c in out if c["selector"].endswith("tr.odd") or c["selector"].endswith("tr.even")]
    cases.append(("odd_even_both_emitted", len(oe) == 2, f"got {[c['selector'] for c in out]!r}"))
    if len(oe) == 2:
        cases.append(("sibling_variants_cross_ref",
                      oe[0]["sibling_variants"] and oe[1]["sibling_variants"]
                      and oe[0]["merged_count"] == 10 and oe[1]["merged_count"] == 10,
                      f"got {[(c['sibling_variants'], c['merged_count']) for c in oe]!r}"))
    # 변형 없는 단일 시그니처 그룹은 None (스키마 노이즈 방지)
    out_single = html_repeating_patterns(html4, "https://x.com")
    cases.append(("no_variants_is_none",
                  out_single and out_single[0]["sibling_variants"] is None
                  and out_single[0]["merged_count"] is None,
                  f"got {out_single!r}"))

    # 5. 빈 HTML
    cases.append(("empty_html", html_repeating_patterns("", "https://x.com") == [], ""))

    # 6. skeleton descendant reject (2026-05-25 Radiolab plan) —
    #    row sig 자체엔 skeleton 없지만 descendant `<div class="p-skeleton">` 박힘.
    #    SPA hydration 전 캡처된 가짜 row → 후보 list 에서 제외.
    html_skeleton = '<div class="grid">' + ''.join(
        f'''<div class="col-12 mb-6">
              <div class="p-skeleton p-component card" aria-hidden="true"></div>
            </div>'''
        for _ in range(8)
    ) + '</div>'
    out = html_repeating_patterns(html_skeleton, "https://x.com/list")
    cases.append(("skeleton_descendant_rejected",
                  len(out) == 0,
                  f"got {len(out)} candidates (skeleton 후보가 reject 안 됨): {out!r}"))

    # 7. row 안에 loading/placeholder/shimmer 있는 경우도 reject
    for token in ("loading", "placeholder", "shimmer", "p-skeleton"):
        html_t = '<div class="grid">' + ''.join(
            f'<div class="col-12 mb-6"><div class="{token}-row"></div></div>'
            for _ in range(8)
        ) + '</div>'
        out_t = html_repeating_patterns(html_t, "https://x.com/list")
        cases.append((f"reject_descendant_{token.replace('-', '_')}",
                      len(out_t) == 0,
                      f"got {len(out_t)} for token={token!r}"))

    # 8. 진짜 row 는 reject 안 됨 (false-positive 가드) — class 에 loading 없는 정상 row
    html_real = '<div class="recent">' + ''.join(
        f'<article class="post-card"><h2><a href="/posts/{i}">post {i}</a></h2></article>'
        for i in range(6)
    ) + '</div>'
    out_real = html_repeating_patterns(html_real, "https://x.com/")
    cases.append(("real_row_not_rejected",
                  len(out_real) >= 1 and out_real[0]["child_count"] == 6,
                  f"got {out_real!r}"))

    # 9. Vue scoped rows: large head style/meta/link groups are chrome noise;
    #    scoped data-v attrs must not prevent post anchors from grouping.
    html_vue = (
        "<html><head>"
        + "".join(f"<style data-vue-ssr-id='{i}'>.x{i}{{}}</style>" for i in range(8))
        + "</head><body><div class='post-contents__body' data-v-20f7ef50>"
        + "".join(
            f'''<a class="post post--pc" data-v-4a15cb84 data-v-20f7ef50 href="/en/news/{10000 + i}">
                  <strong>PUBG notice {i}</strong>
                </a>'''
            for i in range(6)
        )
        + "</div></body></html>"
    )
    out_vue = html_repeating_patterns(html_vue, "https://www.pubg.com/en/news")
    cases.append(("ignores_head_chrome_noise",
                  all(not str(c.get("selector", "")).startswith("head >") for c in out_vue),
                  f"got {out_vue!r}"))
    cases.append(("vue_scoped_post_rows_grouped",
                  len(out_vue) >= 1
                  and out_vue[0]["selector"] == "div.post-contents__body > a.post.post--pc"
                  and out_vue[0]["sample_url"] == "https://www.pubg.com/en/news/10000"
                  and out_vue[0]["href_pattern_guess"] == "/en/news/{n}",
                  f"got {out_vue[:2]!r}"))

    # 10. SVG decoration can have a larger sibling count than real article cards.
    #     It must not outrank rows that carry text and article href evidence.
    html_svg_decoy = (
        "<main>"
        "<svg><g>"
        + "".join(f"<path d='M{i} 0h1v1z'></path>" for i in range(15))
        + "</g></svg>"
        "<section class='news-grid'>"
        + "".join(
            f'''<a class="sc-card" data-testid="card" href="/ko-kr/news/{i}">
                  <h2>Patch notes {i}</h2>
                </a>'''
            for i in range(12)
        )
        + "</section></main>"
    )
    out_svg_decoy = html_repeating_patterns(html_svg_decoy, "https://www.leagueoflegends.com/ko-kr/news/")
    cases.append(("article_rows_outrank_svg_decoration",
                  len(out_svg_decoy) >= 1
                  and out_svg_decoy[0]["selector"] == "section.news-grid > a.sc-card"
                  and out_svg_decoy[0]["child_count"] == 12
                  and out_svg_decoy[0]["sample_url"] == "https://www.leagueoflegends.com/ko-kr/news/0",
                  f"got {out_svg_decoy[:3]!r}"))

    return cases
