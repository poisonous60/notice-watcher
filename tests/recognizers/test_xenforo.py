"""engine.recognizers.xenforo — XenForo 전역 RSS httpx_html config.

root 도메인은 URL 만으론 판정 불가(detect_xenforo_platform 가 probe 후 봉합) — recognizer 는
XenForo-distinctive URL(`/forums/-/index.rss`, `/whats-new/posts/`)만 매칭. build_config 는 양쪽 공유.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers.xenforo import build_config
    from engine.recognizers import recognize
    from engine.config_schema import validate_config

    cases: list[tuple[str, bool, str]] = []

    # 1. build_config → RSS url_template + RSS row selector + 스키마 통과.
    cfg = build_config("https://hardforum.com")
    ok = (cfg is not None
          and cfg["strategy"] == "httpx_html"
          and cfg["list"]["url_template"] == "https://hardforum.com/forums/-/index.rss"
          and cfg["list"]["row_selector"] == "channel > item")
    cases.append(("build_config_rss_shape", ok, f"got {cfg and cfg.get('list',{}).get('url_template')!r}"))

    if cfg is not None:
        try:
            validate_config(cfg)
            cases.append(("build_config_schema_valid", True, ""))
        except Exception as e:  # noqa: BLE001
            cases.append(("build_config_schema_valid", False, f"{type(e).__name__}: {e}"))

    # 2. RSS / whats-new URL → recognize 매칭.
    cases.append(("rss_url_recognized", recognize("https://hardforum.com/forums/-/index.rss") is not None, ""))
    cases.append(("whatsnew_url_recognized", recognize("https://www.avsforum.com/whats-new/posts/") is not None, ""))

    # 3. root 도메인 → 미매칭 (false-positive 폭발 차단 — detect_xenforo_platform 가 봉합).
    cases.append(("root_not_recognized", recognize("https://hardforum.com/") is None, ""))

    # 4. thread URL → 미매칭 (whats-new/rss 만; 임의 thread 를 RSS 로 바꾸지 않음).
    cases.append(("thread_not_recognized",
                  recognize("https://hardforum.com/threads/some-topic.123/") is None, ""))

    # 5. 빈 host → None.
    cases.append(("bad_base_none", build_config("https://") is None, ""))

    return cases
