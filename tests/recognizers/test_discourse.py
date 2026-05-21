"""engine.recognizers.discourse — /latest query params are feed identity."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine import make_adapter
    from engine.config_schema import validate_config
    from engine.recognizers import recognize
    from engine.recognizers.discourse import build_config

    cases: list[tuple[str, bool, str]] = []

    cfg = build_config("https://discuss.python.org/")
    cases.append(("default_shape",
                  cfg is not None and cfg.get("kwargs") == {"base_url": "https://discuss.python.org"}
                  and cfg.get("_slug_board") == "discuss.python.org",
                  f"got {cfg!r}"))
    if cfg is not None:
        try:
            validate_config(cfg)
            adapter = make_adapter(cfg)
            cases.append(("default_make_adapter",
                          adapter.__class__.__name__ == "DiscourseAdapter" and adapter.board == "latest",
                          f"adapter={adapter!r}"))
        except Exception as e:  # noqa: BLE001
            cases.append(("default_make_adapter", False, f"{type(e).__name__}: {e}"))

    cfg_q = recognize("https://discuss.python.org/latest?order=created&ascending=true&utm_source=x")
    cases.append(("sort_params_preserved",
                  cfg_q is not None
                  and cfg_q.get("kwargs", {}).get("list_params") == {"order": "created", "ascending": "true"}
                  and cfg_q.get("_slug_board") == "discuss.python.org_ascending_true_order_created",
                  f"got {cfg_q!r}"))

    cfg_track = recognize("https://discuss.python.org/latest?utm_source=x&fbclid=y")
    cases.append(("tracking_params_dropped",
                  cfg_track is not None
                  and "list_params" not in (cfg_track.get("kwargs") or {})
                  and cfg_track.get("_slug_board") == "discuss.python.org",
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
