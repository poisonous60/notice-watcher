"""engine.recognizers.medium - Medium RSS/publication fast-path."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def run():
    from engine.recognizers import recognize

    cases = []

    r = recognize("https://medium.com/feed/tag/programming")
    cases.append((
        "feed_tag_programming",
        r is not None
        and r.get("_recognized_platform") == "host_medium-com"
        and r.get("board") == "tag/programming"
        and r.get("list", {}).get("url_template") == "https://medium.com/feed/{board}"
        and r.get("list", {}).get("row_selector") == "channel > item"
        and r.get("_slug_board") == "feed",
        f"got {r}",
    ))

    r = recognize("https://medium.com/airbnb-engineering")
    cases.append((
        "publication_normalizes_to_feed",
        r is not None
        and r.get("board") == "airbnb-engineering"
        and r.get("_source_url") == "https://medium.com/airbnb-engineering",
        f"got {r}",
    ))

    r = recognize("https://medium.com/feed/airbnb-engineering")
    cases.append((
        "feed_publication",
        r is not None
        and r.get("board") == "airbnb-engineering"
        and r.get("_slug_board") == "airbnb-engineering",
        f"got {r}",
    ))

    for url in [
        "https://medium.com/@alice",
        "https://medium.com/p/462e6ecbeb9d",
        "https://medium.com/tag/programming",
        "https://example.com/feed/tag/programming",
    ]:
        r = recognize(url)
        cases.append((f"negative:{url}", r is None, f"got {r}"))

    return cases


if __name__ == "__main__":
    failed = False
    for name, ok, msg in run():
        print(("PASS" if ok else "FAIL"), name, "-", msg)
        failed = failed or not ok
    raise SystemExit(1 if failed else 0)
