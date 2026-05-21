from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from adapters.google_cloud_release_notes import GoogleCloudReleaseNotesAdapter


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize, recognize_reject
    from engine.slug import url_to_slug

    cases: list[tuple[str, bool, str]] = []
    url = "https://cloud.google.com/release-notes"
    cfg = recognize(url)

    cases.append((
        "recognize_release_notes",
        cfg is not None and cfg.get("_recognized_platform") == "host_cloud-google-co",
        f"got {cfg and cfg.get('_recognized_platform')!r}",
    ))
    cases.append((
        "slug_stability",
        url_to_slug(url) == "host_cloud-google-co_release-notes_68689125",
        url_to_slug(url),
    ))
    cases.append((
        "docs_host_variant",
        recognize("https://docs.cloud.google.com/release-notes") is not None,
        "docs.cloud.google.com should share the release notes feed",
    ))
    cases.append((
        "product_docs_negative",
        recognize("https://cloud.google.com/run/docs/release-notes") is None,
        "product-specific release notes are separate pages",
    ))
    cases.append((
        "no_reject_conflict",
        recognize_reject(url) is None,
        f"got {recognize_reject(url)!r}",
    ))

    xml = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>May 20, 2026</title>
        <id>tag:google.com,2016:gcp-release-notes#May_20_2026</id>
        <updated>2026-05-20T00:00:00-07:00</updated>
        <link rel="alternate" href="https://docs.cloud.google.com/release-notes#May_20_2026" />
        <content type="html">
          &lt;h2 class="release-note-product-title"&gt;BigQuery&lt;/h2&gt;
          &lt;h3&gt;Feature&lt;/h3&gt;
          &lt;p&gt;&lt;strong&gt;Python UDFs&lt;/strong&gt; are now generally available.&lt;/p&gt;
          &lt;h3&gt;Change&lt;/h3&gt;
          &lt;p&gt;A SQL behavior changed for preview customers.&lt;/p&gt;
          &lt;h2 class="release-note-product-title"&gt;Cloud Run&lt;/h2&gt;
          &lt;h3&gt;Announcement&lt;/h3&gt;
          &lt;p&gt;New regions are available.&lt;/p&gt;
        </content>
      </entry>
    </feed>
    """
    adapter = GoogleCloudReleaseNotesAdapter()
    posts = adapter._parse_feed(xml, page_size=10)
    cases.append(("parse_sections", len(posts) == 3, f"got {len(posts)} posts"))
    cases.append((
        "product_kind_fields",
        posts[0].author == "BigQuery" and posts[0].category == "Feature" and posts[2].author == "Cloud Run",
        f"got {[(p.author, p.category) for p in posts]}",
    ))
    cases.append((
        "stable_unique_ids",
        len({p.post_id for p in posts}) == len(posts) and all(p.post_id for p in posts),
        f"ids={[p.post_id for p in posts]}",
    ))
    cases.append((
        "published_at_carried",
        all(p.published_at == "2026-05-20T00:00:00-07:00" for p in posts),
        f"got {[p.published_at for p in posts]}",
    ))
    return cases
