"""engine.recognizers.mbin — Mbin entries API httpx_json config."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.config_schema import validate_config
    from engine.recognizers import recognize
    from engine.recognizers.mbin import build_config
    from engine import make_adapter

    cases: list[tuple[str, bool, str]] = []

    cfg = build_config("https://fedia.io/")
    cases.append(("root_build_shape",
                  cfg is not None and cfg.get("strategy") == "httpx_json"
                  and cfg.get("list", {}).get("url_template") == "https://fedia.io/api/entries?sort=newest&perPage={page_size}"
                  and cfg.get("_slug_board") == "fedia.io",
                  f"got {cfg!r}"))
    if cfg is not None:
        try:
            validate_config(cfg)
            adapter = make_adapter(cfg)
            cases.append(("root_config_valid_make_adapter",
                          adapter.__class__.__name__ == "ConfigAdapter" and adapter.board == "entries",
                          f"adapter={adapter!r}"))
        except Exception as e:  # noqa: BLE001
            cases.append(("root_config_valid_make_adapter", False, f"{type(e).__name__}: {e}"))

    cfg_api = recognize("https://fedia.io/api/entries?sort=newest&perPage=20")
    cases.append(("api_entries_url_recognized",
                  cfg_api is not None and cfg_api.get("_recognized_platform") == "mbin",
                  f"got {cfg_api!r}"))

    cfg_mag = recognize("https://fedia.io/m/news")
    cases.append(("magazine_url_recognized",
                  cfg_mag is not None and cfg_mag.get("_recognized_platform") == "mbin",
                  f"got {cfg_mag!r}"))

    cases.append(("root_not_recognized",
                  recognize("https://fedia.io/") is None,
                  "root URL must be probe-marker based, not URL-only"))

    return cases
