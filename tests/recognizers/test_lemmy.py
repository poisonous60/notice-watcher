"""engine.recognizers.lemmy — Lemmy API-backed handwritten config."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.config_schema import validate_config
    from engine.recognizers import recognize
    from engine.recognizers.lemmy import build_config
    from engine import make_adapter

    cases: list[tuple[str, bool, str]] = []

    cfg = build_config("https://lemmy.ml/")
    cases.append(("root_build_shape",
                  cfg is not None and cfg.get("adapter") == "LemmyAdapter"
                  and cfg.get("strategy") == "handwritten"
                  and cfg.get("kwargs") == {"base_url": "https://lemmy.ml"}
                  and cfg.get("_slug_board") == "lemmy.ml",
                  f"got {cfg!r}"))
    if cfg is not None:
        try:
            validate_config(cfg)
            adapter = make_adapter(cfg)
            ok = adapter.__class__.__name__ == "LemmyAdapter" and adapter.board == "local"
            cases.append(("root_config_valid_make_adapter", ok, f"adapter={adapter!r}"))
        except Exception as e:  # noqa: BLE001
            cases.append(("root_config_valid_make_adapter", False, f"{type(e).__name__}: {e}"))

    cfg_c = build_config("https://lemmy.ml/c/technology", community_name="technology")
    cases.append(("community_build_shape",
                  cfg_c is not None and cfg_c.get("kwargs", {}).get("community_name") == "technology"
                  and cfg_c.get("_slug_board") == "lemmy.ml_c_technology",
                  f"got {cfg_c!r}"))

    cfg_api = recognize("https://lemmy.ml/api/v3/post/list?sort=New&limit=20&type_=Local")
    cases.append(("api_list_url_recognized",
                  cfg_api is not None and cfg_api.get("_recognized_platform") == "lemmy"
                  and cfg_api.get("kwargs") == {"base_url": "https://lemmy.ml"},
                  f"got {cfg_api!r}"))

    cases.append(("root_not_recognized",
                  recognize("https://lemmy.ml/") is None,
                  "root URL must be probe-marker based, not URL-only"))
    cases.append(("community_not_recognized_without_probe",
                  recognize("https://lemmy.ml/c/technology") is None,
                  "generic /c path needs probe marker"))
    cases.append(("post_not_recognized",
                  recognize("https://lemmy.ml/post/47636483") is None,
                  "single post URL is not a board"))
    cases.append(("other_host_negative",
                  recognize("https://example.com/c/technology") is None,
                  "generic /c path should not be Lemmy without probe marker"))

    return cases
