"""engine.recognizers.stackexchange — /questions tab/sort maps to API sort."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.config_schema import validate_config
    from engine.recognizers import recognize

    cases: list[tuple[str, bool, str]] = []

    cfg = recognize("https://stackoverflow.com/questions")
    cases.append(("default_creation_shape",
                  cfg is not None
                  and "sort=creation" in cfg.get("list", {}).get("url_template", "")
                  and cfg.get("_slug_board") == "stackoverflow.com_questions",
                  f"got {cfg!r}"))
    if cfg is not None:
        try:
            validate_config(cfg)
            cases.append(("default_config_valid", True, "OK"))
        except Exception as e:  # noqa: BLE001
            cases.append(("default_config_valid", False, f"{type(e).__name__}: {e}"))

    cfg_active = recognize("https://stackoverflow.com/questions?tab=Active&utm_source=x")
    cases.append(("tab_active_preserved",
                  cfg_active is not None
                  and "sort=activity" in cfg_active.get("list", {}).get("url_template", "")
                  and cfg_active.get("_slug_board") == "stackoverflow.com_questions_sort_activity",
                  f"got {cfg_active!r}"))

    cfg_votes = recognize("https://superuser.com/questions?sort=votes")
    cases.append(("sort_query_preserved",
                  cfg_votes is not None
                  and "sort=votes" in cfg_votes.get("list", {}).get("url_template", "")
                  and cfg_votes.get("_slug_board") == "superuser.com_questions_sort_votes",
                  f"got {cfg_votes!r}"))

    cfg_track = recognize("https://askubuntu.com/questions?utm_source=x&fbclid=y")
    cases.append(("tracking_params_dropped",
                  cfg_track is not None
                  and "sort=creation" in cfg_track.get("list", {}).get("url_template", "")
                  and cfg_track.get("_slug_board") == "askubuntu.com_questions",
                  f"got {cfg_track!r}"))

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
