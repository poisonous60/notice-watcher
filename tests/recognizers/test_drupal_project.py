"""engine.recognizers.drupal_project — Drupal.org project release-history XML."""
from __future__ import annotations

from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize, recognize_reject

    cases: list[tuple[str, bool, str]] = []

    cfg = recognize("https://drupal.org/project/drupal/releases")
    cases.append((
        "recognize_integration",
        cfg is not None and cfg.get("_recognized_platform") == "host_drupal-org",
        f"got {cfg and cfg.get('_recognized_platform')!r}",
    ))
    cases.append((
        "slug_board_compat",
        cfg is not None and cfg.get("_slug_board") == "project",
        f"got {cfg and cfg.get('_slug_board')!r}",
    ))
    cases.append((
        "release_history_url",
        cfg is not None
        and cfg["board"] == "drupal"
        and cfg["list"]["url_template"] == "https://updates.drupal.org/release-history/drupal/current"
        and cfg["list"]["row_selector"] == "project > releases > release",
        f"got board={cfg and cfg.get('board')!r}",
    ))

    cfg2 = recognize("https://www.drupal.org/project/token/releases")
    cases.append((
        "project_extract_www",
        cfg2 is not None
        and cfg2["board"] == "token"
        and cfg2["list"]["url_template"] == "https://updates.drupal.org/release-history/token/current",
        f"got {cfg2 and cfg2.get('board')!r}",
    ))

    neg = [
        "https://www.drupal.org/project/drupal",
        "https://www.drupal.org/project/drupal/releases/11.3.0",
        "https://www.drupal.org/about",
        "https://updates.drupal.org/release-history/drupal/current",
    ]
    for u in neg:
        r = recognize(u)
        hit = r is not None and r.get("_recognized_platform") == "host_drupal-org"
        cases.append((f"negative[{u.split('drupal.org')[-1][:28]}]", not hit, f"got {hit!r}"))

    cases.append((
        "no_reject_conflict",
        recognize_reject("https://www.drupal.org/project/drupal/releases") is None,
        f"got {recognize_reject('https://www.drupal.org/project/drupal/releases')!r}",
    ))

    return cases


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
