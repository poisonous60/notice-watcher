"""engine.recognizers.peertube — PeerTube API-backed handwritten config."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.config_schema import validate_config
    from engine.recognizers import recognize
    from engine.recognizers.peertube import build_config
    from engine import make_adapter

    cases: list[tuple[str, bool, str]] = []

    cfg = build_config("https://diode.zone/")
    cases.append(("root_build_shape",
                  cfg is not None and cfg.get("adapter") == "PeerTubeAdapter"
                  and cfg.get("strategy") == "handwritten"
                  and cfg.get("kwargs") == {"base_url": "https://diode.zone"}
                  and cfg.get("_slug_board") == "diode.zone",
                  f"got {cfg!r}"))
    if cfg is not None:
        try:
            validate_config(cfg)
            adapter = make_adapter(cfg)
            cases.append(("root_config_valid_make_adapter",
                          adapter.__class__.__name__ == "PeerTubeAdapter" and adapter.board == "videos",
                          f"adapter={adapter!r}"))
        except Exception as e:  # noqa: BLE001
            cases.append(("root_config_valid_make_adapter", False, f"{type(e).__name__}: {e}"))

    cfg_api = recognize("https://diode.zone/api/v1/videos?sort=-publishedAt&count=20")
    cases.append(("api_list_url_recognized",
                  cfg_api is not None and cfg_api.get("_recognized_platform") == "peertube"
                  and cfg_api.get("kwargs") == {"base_url": "https://diode.zone"},
                  f"got {cfg_api!r}"))
    cfg_sort = recognize("https://diode.zone/api/v1/videos?sort=-createdAt&count=20&utm_source=x")
    cases.append(("api_sort_preserved",
                  cfg_sort is not None
                  and cfg_sort.get("kwargs") == {"base_url": "https://diode.zone", "sort": "-createdAt"}
                  and cfg_sort.get("_slug_board") == "diode.zone_sort_-createdAt",
                  f"got {cfg_sort!r}"))
    cfg_track = recognize("https://diode.zone/api/v1/videos?utm_source=x&fbclid=y")
    cases.append(("tracking_params_dropped",
                  cfg_track is not None
                  and cfg_track.get("kwargs") == {"base_url": "https://diode.zone"}
                  and cfg_track.get("_slug_board") == "diode.zone",
                  f"got {cfg_track!r}"))

    cases.append(("root_not_recognized",
                  recognize("https://diode.zone/") is None,
                  "root URL must be probe-marker based, not URL-only"))
    cases.append(("videos_not_recognized_without_probe",
                  recognize("https://diode.zone/videos") is None,
                  "generic /videos needs PeerTube HTML marker"))
    cases.append(("single_watch_not_recognized",
                  recognize("https://diode.zone/w/21vs3SQqKnj1YjqyxUiJaJ") is None,
                  "single video URL is not a board"))
    cases.append(("other_host_negative",
                  recognize("https://example.com/videos") is None,
                  "generic /videos path should not be PeerTube without probe marker"))

    return cases
