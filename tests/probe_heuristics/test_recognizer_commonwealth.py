"""engine.recognizers.commonwealth -- Common discussion URLs."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine import make_adapter
    from engine.config_schema import validate_config
    from engine.recognizers import recognize
    from engine.recognizers.commonwealth import build_config

    cases: list[tuple[str, bool, str]] = []

    cfg = build_config("https://forum.sushi.com", "sushi", source_url="https://forum.sushi.com/discussions")
    cases.append(("build_config_shape",
                  cfg is not None
                  and cfg.get("strategy") == "handwritten"
                  and cfg.get("adapter") == "CommonwealthAdapter"
                  and cfg.get("kwargs", {}).get("base_url") == "https://forum.sushi.com"
                  and cfg.get("kwargs", {}).get("community_id") == "sushi"
                  and cfg.get("_slug_board") == "forum.sushi.com_sushi",
                  f"got {cfg!r}"))
    if cfg is not None:
        try:
            validate_config(cfg)
            adapter = make_adapter(cfg)
            cases.append(("make_adapter",
                          adapter.__class__.__name__ == "CommonwealthAdapter"
                          and adapter.board == "sushi",
                          f"adapter={adapter!r}"))
        except Exception as e:  # noqa: BLE001
            cases.append(("make_adapter", False, f"{type(e).__name__}: {e}"))

    cfg_common = recognize("https://common.xyz/osmosis/discussions")
    cases.append(("common_xyz_matches",
                  cfg_common is not None
                  and cfg_common.get("kwargs", {}).get("base_url") == "https://common.xyz"
                  and cfg_common.get("kwargs", {}).get("community_id") == "osmosis",
                  f"got {cfg_common!r}"))

    cfg_legacy = recognize("https://commonwealth.im/dydx/discussions")
    cases.append(("commonwealth_im_matches",
                  cfg_legacy is not None
                  and cfg_legacy.get("kwargs", {}).get("base_url") == "https://commonwealth.im"
                  and cfg_legacy.get("kwargs", {}).get("community_id") == "dydx",
                  f"got {cfg_legacy!r}"))

    cfg_custom = recognize("https://forum.sushi.com/discussions")
    cases.append(("custom_domain_not_url_recognized",
                  cfg_custom is None,
                  f"got {cfg_custom!r}"))

    cfg_article = recognize("https://common.xyz/osmosis/discussion/123-foo")
    cases.append(("discussion_article_no_match",
                  cfg_article is None,
                  f"got {cfg_article!r}"))

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
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
