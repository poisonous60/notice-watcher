from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from adapters.anthropic_docs import AnthropicDocsReleaseNotesAdapter


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize, recognize_reject

    cases: list[tuple[str, bool, str]] = []
    url = "https://docs.anthropic.com/en/release-notes/overview"
    cfg = recognize(url)

    cases.append((
        "recognize_release_notes",
        cfg is not None and cfg.get("_recognized_platform") == "host_docs-anthropic-",
        f"got {cfg and cfg.get('_recognized_platform')!r}",
    ))
    cases.append((
        "slug_stability",
        __import__("engine.slug", fromlist=["url_to_slug"]).url_to_slug(url) == "host_docs-anthropic-_en_571d0ac4",
        __import__("engine.slug", fromlist=["url_to_slug"]).url_to_slug(url),
    ))
    cases.append((
        "same_host_docs_negative",
        recognize("https://docs.anthropic.com/en/docs/intro") is None,
        "generic docs pages must not match release notes recognizer",
    ))
    cases.append((
        "no_reject_conflict",
        recognize_reject(url) is None,
        f"got {recognize_reject(url)!r}",
    ))

    html = """
    <article id="content-container">
      <h3>May 19, 2026</h3>
      <ul>
        <li><a href="/docs/en/example">Example feature</a> is now available for testing.</li>
        <li>Second feature is generally available with no link.</li>
      </ul>
      <h3>May 18, 2026</h3>
      <ul><li>Earlier note.</li></ul>
    </article>
    """
    adapter = AnthropicDocsReleaseNotesAdapter()
    posts = adapter._parse_raw_list(html, page_size=10)
    cases.append((
        "parse_rows",
        len(posts) == 3,
        f"got {len(posts)} posts",
    ))
    cases.append((
        "date_carry",
        posts[0].published_at == "2026-05-19T00:00:00+00:00" and posts[2].published_at == "2026-05-18T00:00:00+00:00",
        f"got {[p.published_at for p in posts]}",
    ))
    cases.append((
        "stable_unique_ids",
        len({p.post_id for p in posts}) == len(posts) and all(p.post_id for p in posts),
        f"ids={[p.post_id for p in posts]}",
    ))
    cases.append((
        "relative_url_join",
        posts[0].url == "https://docs.anthropic.com/docs/en/example",
        f"got {posts[0].url!r}",
    ))
    return cases
