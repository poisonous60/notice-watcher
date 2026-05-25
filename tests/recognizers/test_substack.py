"""engine.recognizers.substack - Substack RSS fast-path."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def run():
    from engine.recognizers import recognize

    cases = []

    r = recognize("https://astralcodexten.substack.com/archive")
    cases.append((
        "archive_normalizes_to_feed",
        r is not None
        and r.get("_recognized_platform") == "host_substack-com"
        and r.get("site") == "astralcodexten.substack.com"
        and r.get("board") == "astralcodexten"
        and r.get("_slug_board") == "astralcodexten"
        and r.get("list", {}).get("url_template") == "https://astralcodexten.substack.com/feed"
        and r.get("list", {}).get("row_selector") == "channel > item",
        f"got {r}",
    ))

    r = recognize("https://noahpinion.substack.com/feed")
    cases.append((
        "feed_url_recognized",
        r is not None
        and r.get("board") == "noahpinion"
        and r.get("_source_url") == "https://noahpinion.substack.com/feed",
        f"got {r}",
    ))

    r = recognize("https://www.substack.com/")
    cases.append(("www_substack_not_publication", r is None, f"got {r}"))

    r = recognize("https://example.com/feed")
    cases.append(("other_feed_not_substack", r is None, f"got {r}"))

    return cases


if __name__ == "__main__":
    failed = False
    for name, ok, msg in run():
        print(("PASS" if ok else "FAIL"), name, "-", msg)
        failed = failed or not ok
    raise SystemExit(1 if failed else 0)
