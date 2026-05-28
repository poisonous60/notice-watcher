"""probe.extract.detect_storyblok_platform + Storyblok all-stories config."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

covers = ["detect_storyblok_platform", "storyblok_build_config"]


def run() -> list[tuple[str, bool, str]]:
    from engine import validate_config
    from engine.config_adapter import make_adapter
    from engine.recognizers.storyblok import build_config
    from probe.extract import detect_storyblok_platform

    cases: list[tuple[str, bool, str]] = []

    html = """
    <html><body>
      <div class="grid w-full gap-6 md:grid-cols-2 xl:grid-cols-3 pt-5">
        <article class="news-card storyblok__outline"><a href="/news/alpha">Alpha</a></article>
      </div>
    </body></html>
    """
    detected = detect_storyblok_platform(html, "https://wayforward.com/news/")
    cases.append((
        "storyblok_outline_detects",
        bool(detected and detected["story_data_url"] == "https://wayforward.com/story-data/all-stories.json"
             and detected["board"] == "news"),
        f"got {detected!r}",
    ))

    plain = "<html><body><article class='news-card'><a href='/news/a'>A</a></article></body></html>"
    cases.append(("plain_news_card_no_match", detect_storyblok_platform(plain, "https://example.com/news/") is None, ""))

    cfg = build_config("https://wayforward.com/news/", story_data_url="https://wayforward.com/story-data/all-stories.json")
    try:
        validate_config(cfg or {})
        adapter = make_adapter(cfg or {})
        cases.append((
            "storyblok_config_valid_adapter",
            cfg is not None
            and cfg.get("strategy") == "handwritten"
            and cfg.get("adapter") == "StoryblokAllStoriesAdapter"
            and adapter.__class__.__name__ == "StoryblokAllStoriesAdapter",
            f"got {cfg!r} adapter={adapter.__class__.__name__ if cfg else None}",
        ))
    except Exception as e:  # noqa: BLE001
        cases.append(("storyblok_config_valid_adapter", False, repr(e)))

    return cases


if __name__ == "__main__":
    failed = False
    for name, ok, msg in run():
        print(("PASS" if ok else "FAIL"), name, "-", msg)
        failed = failed or not ok
    raise SystemExit(1 if failed else 0)
