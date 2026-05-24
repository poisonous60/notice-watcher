"""site_kind digest classification for RSS/podcast/static/SPAs."""
from __future__ import annotations


covers = ["site_kind"]


def _feed(url: str, *, validated: bool = True, item_count: int = 2, title: str = "Example") -> dict:
    return {
        "url": url,
        "validated": validated,
        "item_count": item_count,
        "root_tag": "rss",
        "title": title,
    }


def _rows(n: int, sample_url: str = "https://example.com/posts/1") -> list[dict]:
    return [{"child_count": n, "sample_url": sample_url, "href_pattern_guess": "/posts/{id}"}]


def run() -> list[tuple[str, bool, str]]:
    from engine.digest import classify_site_kind
    from scripts.register import _enforce_site_kind_config, _make_cfg_post_processor

    cases: list[tuple[str, bool, str]] = []

    cbs = classify_site_kind({
        "url": "https://www.cbsnews.com/podcasts/",
        "feed_candidates": [_feed("https://www.cbsnews.com/podcasts/rss", validated=False, item_count=0)],
        "list_candidates": {"html_repeating_patterns": _rows(10, "https://www.cbsnews.com/news/1")},
    })
    cases.append(("cbs_empty_feed_is_static_not_rss",
                  cbs.get("kind") == "static_html" and cbs.get("confidence") == "high",
                  f"got {cbs!r}"))

    dotnetrocks = classify_site_kind({
        "url": "https://www.dotnetrocks.com/RSS",
        "feed_candidates": [_feed("https://www.dotnetrocks.com/RSS", validated=False, item_count=0)],
        "list_candidates": {},
    })
    cases.append(("dotnetrocks_html_rss_path_unknown",
                  dotnetrocks.get("kind") == "unknown",
                  f"got {dotnetrocks!r}"))

    tal = classify_site_kind({
        "url": "https://www.thisamericanlife.org/",
        "feed_candidates": [_feed("https://feeds.thisamericanlife.org/talpodcast", title="This American Life")],
        "list_candidates": {"html_repeating_patterns": []},
    })
    cases.append(("thisamericanlife_validated_feed_is_rss_high",
                  tal.get("kind") == "rss" and tal.get("confidence") == "high"
                  and tal.get("primary_feed_url") == "https://feeds.thisamericanlife.org/talpodcast",
                  f"got {tal!r}"))

    oxide = classify_site_kind({
        "url": "https://oxide.computer/podcast/",
        "feed_candidates": [_feed("https://oxide.computer/podcast/rss.xml")],
        "list_candidates": {
            "audio_share_host_detected": {
                "audio_share_host_detected": True,
                "confidence": "structural",
                "host": "share.transistor.fm",
            },
        },
    })
    cases.append(("oxide_structural_audio_share_is_podcast",
                  oxide.get("kind") == "podcast" and oxide.get("confidence") == "high",
                  f"got {oxide!r}"))

    radiolab = classify_site_kind({
        "url": "https://radiolab.org/podcast/",
        "verdict": "정적 응답이 빈 shell — JS 실행 필요",
        "recommended_strategy": "playwright (S4)",
        "feed_candidates": [],
        "list_candidates": {"html_repeating_patterns": []},
    })
    cases.append(("radiolab_static_shell_is_spa_rendered",
                  radiolab.get("kind") == "spa_rendered" and radiolab.get("confidence") == "high",
                  f"got {radiolab!r}"))

    next_page = classify_site_kind({
        "url": "https://example.com/archive",
        "notes": ["next page link exists"],
        "feed_candidates": [],
        "list_candidates": {"html_repeating_patterns": []},
    })
    cases.append(("next_page_text_is_not_js_signal",
                  next_page.get("kind") == "unknown",
                  f"got {next_page!r}"))

    static = classify_site_kind({
        "url": "https://example.com/news/",
        "feed_candidates": [],
        "list_candidates": {"html_repeating_patterns": _rows(12)},
    })
    cases.append(("html_rows_without_feed_is_static",
                  static.get("kind") == "static_html" and static.get("confidence") == "high",
                  f"got {static!r}"))

    hybrid = classify_site_kind({
        "url": "https://example.com/news/",
        "feed_candidates": [_feed("https://example.com/news/feed.xml", title="Example News")],
        "list_candidates": {"html_repeating_patterns": _rows(12)},
    })
    cases.append(("html_rows_plus_semantic_feed_is_hybrid",
                  hybrid.get("kind") == "hybrid" and hybrid.get("confidence") == "high"
                  and "semantic_match:high" in (hybrid.get("evidence") or []),
                  f"got {hybrid!r}"))

    unknown = classify_site_kind({
        "url": "https://example.com/about",
        "feed_candidates": [],
        "list_candidates": {"html_repeating_patterns": []},
    })
    cases.append(("weak_signals_are_unknown",
                  unknown.get("kind") == "unknown" and unknown.get("confidence") == "low",
                  f"got {unknown!r}"))

    host_known = classify_site_kind({
        "url": "https://oxide.computer/podcast/",
        "feed_candidates": [_feed("https://oxide.computer/podcast/rss.xml")],
        "list_candidates": {
            "audio_share_host_detected": {
                "audio_share_host_detected": True,
                "confidence": "host_known",
                "host": "feeds.transistor.fm",
            },
        },
    })
    cases.append(("host_known_audio_share_stays_rss",
                  host_known.get("kind") == "rss",
                  f"got {host_known!r}"))

    link_rel = classify_site_kind({
        "url": "https://example.com/podcast",
        "feed_candidates": [],
        "list_candidates": {"rss_feed_urls": [{
            "url": "https://example.com/feed.xml",
            "source": "head-alternate",
            "validated": False,
        }]},
    })
    cases.append(("unvalidated_link_rel_feed_is_rss_med",
                  link_rel.get("kind") == "rss" and link_rel.get("confidence") == "med"
                  and link_rel.get("primary_feed_url") == "https://example.com/feed.xml",
                  f"got {link_rel!r}"))

    backfilled_validated = classify_site_kind({
        "url": "https://example.com/podcast",
        "feed_candidates": [],
        "list_candidates": {"rss_feed_urls": [{
            "url": "https://example.com/feed.xml",
            "source": "feed_candidates",
            "validated": True,
            "item_count": 2,
            "root_tag": "rss",
        }]},
    })
    cases.append(("validated_backfill_feed_is_rss_high",
                  backfilled_validated.get("kind") == "rss"
                  and backfilled_validated.get("confidence") == "high",
                  f"got {backfilled_validated!r}"))

    enforced = _enforce_site_kind_config(
        {"site": "oxide.computer", "list": {"url_template": "https://oxide.computer/podcast/"},
         "article": {"content": [{"selector": "main"}]}},
        {"site_kind": {
            "kind": "podcast",
            "confidence": "high",
            "primary_feed_url": "https://oxide.computer/podcast/rss.xml",
        }},
    )
    cases.append(("podcast_enforcement_sets_feed_and_empty_body",
                  enforced.get("list", {}).get("url_template") == "https://oxide.computer/podcast/rss.xml"
                  and enforced.get("article", {}).get("body_empty_acceptable") is True
                  and enforced.get("article", {}).get("content") == [{"selector": "main"}],
                  f"got {enforced!r}"))

    rss_cfg = _enforce_site_kind_config(
        {"site": "tal", "list": {"url_template": "https://www.thisamericanlife.org/"}},
        {"site_kind": {
            "kind": "rss",
            "confidence": "high",
            "primary_feed_url": "https://feeds.thisamericanlife.org/talpodcast",
        }},
    )
    cases.append(("rss_enforcement_sets_primary_feed_only",
                  rss_cfg.get("list", {}).get("url_template") == "https://feeds.thisamericanlife.org/talpodcast"
                  and not (rss_cfg.get("article") or {}).get("body_empty_acceptable"),
                  f"got {rss_cfg!r}"))

    processor = _make_cfg_post_processor({"site_kind": {
        "kind": "podcast",
        "confidence": "high",
        "primary_feed_url": "https://example.com/feed.xml",
    }})
    processed = processor({"site": "example.com", "list": {}, "article": {}})
    cases.append(("post_processor_uses_site_kind_enforcement",
                  processed.get("list", {}).get("url_template") == "https://example.com/feed.xml"
                  and processed.get("article", {}).get("body_empty_acceptable") is True,
                  f"got {processed!r}"))

    med_cfg = _enforce_site_kind_config(
        {"site": "example", "list": {"url_template": "https://example.com/podcast"}},
        {"site_kind": {
            "kind": "rss",
            "confidence": "med",
            "primary_feed_url": "https://example.com/feed.xml",
        }},
    )
    cases.append(("rss_med_does_not_enforce_primary_feed",
                  med_cfg.get("list", {}).get("url_template") == "https://example.com/podcast",
                  f"got {med_cfg!r}"))

    return cases


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(results)} tests, {len(failed)} failed")
        sys.exit(1)
    print(f"\n{len(results)} passed")
