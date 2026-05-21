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
    cfg_sort = recognize("https://lemmy.ml/api/v3/post/list?sort=Active&limit=20&type_=All&utm_source=x")
    cases.append(("api_sort_type_preserved",
                  cfg_sort is not None
                  and cfg_sort.get("kwargs") == {"base_url": "https://lemmy.ml", "sort": "Active", "type_": "All"}
                  and cfg_sort.get("_slug_board") == "lemmy.ml_sort_Active_type_All",
                  f"got {cfg_sort!r}"))
    cfg_community = recognize("https://lemmy.ml/api/v3/post/list?community_name=technology&sort=Hot&type_=Local")
    cases.append(("api_community_query_preserved",
                  cfg_community is not None
                  and cfg_community.get("kwargs", {}).get("community_name") == "technology"
                  and cfg_community.get("kwargs", {}).get("sort") == "Hot"
                  and cfg_community.get("_slug_board") == "lemmy.ml_c_technology_sort_Hot",
                  f"got {cfg_community!r}"))
    cfg_track = recognize("https://lemmy.ml/api/v3/post/list?utm_source=x&fbclid=y")
    cases.append(("tracking_params_dropped",
                  cfg_track is not None
                  and cfg_track.get("kwargs") == {"base_url": "https://lemmy.ml"}
                  and cfg_track.get("_slug_board") == "lemmy.ml",
                  f"got {cfg_track!r}"))

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
