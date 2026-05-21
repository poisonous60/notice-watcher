"""engine.recognizers.iacr_conf — IACR conference important-dates config."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.config_schema import validate_config
    from engine.recognizers import recognize
    from engine.recognizers.iacr_conf import _build, PATTERNS

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []

    cfg = _try("https://eurocrypt.iacr.org/2026/")
    cases.append((
        "board_and_site_extract",
        cfg is not None
        and cfg.get("site") == "eurocrypt.iacr.org"
        and cfg.get("board") == "2026"
        and cfg.get("_slug_board") == "2026",
        f"got site={cfg and cfg.get('site')!r} board={cfg and cfg.get('board')!r}",
    ))

    cases.append((
        "list_shape",
        cfg is not None
        and cfg["list"]["url_template"] == "https://eurocrypt.iacr.org/2026/"
        and cfg["list"]["row_selector"] == "article.customCard > div.customCardRow.row",
        f"got list={cfg and cfg.get('list')!r}",
    ))

    try:
        validate_config(cfg)
        valid = True
        detail = "validate_config OK"
    except Exception as ex:  # noqa: BLE001
        valid = False
        detail = f"{type(ex).__name__}: {ex}"
    cases.append(("config_valid", valid, detail))

    cfg = recognize("https://asiacrypt.iacr.org/2026/")
    cases.append((
        "recognize_integration",
        cfg is not None and cfg.get("_recognized_platform") == "iacr_conf",
        f"got {cfg and cfg.get('_recognized_platform')!r}",
    ))

    negatives = [
        "https://crypto.iacr.org/",
        "https://crypto.iacr.org/2026/callforpapers.php",
        "https://www.iacr.org/meetings/crypto/",
        "https://example.org/2026/",
    ]
    for url in negatives:
        cfg = recognize(url)
        hit = cfg is not None and cfg.get("_recognized_platform") == "iacr_conf"
        cases.append((f"negative[{url}]", not hit, f"got {cfg and cfg.get('_recognized_platform')!r}"))

    return cases


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(name, detail) for name, ok, detail in results if not ok]
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'} {name}: {detail}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
