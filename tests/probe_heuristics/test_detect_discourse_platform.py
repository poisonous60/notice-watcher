"""probe.extract.detect_discourse_platform — 정적 HTML generator meta 로 Discourse 판정.

Discourse 는 root/`/latest`/`/c`/`/t` 모든 페이지에 `<meta name=generator content=Discourse ...>` 박음.
Ember.js shell 이라 topic rows 는 정적에 없어 LLM 이 posts_nonempty:0 으로 실패하지만 이 meta 는 항상 있음.

scripts/register.py 가 is_discourse=true 면 LLM 호출 전 DiscourseAdapter config 만들어 등록 시도.
false-positive ~0 필수 — Discourse 외 사이트(XenForo/IPS/phpBB)는 generator=Discourse 안 박음.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_discourse_platform

    cases: list[tuple[str, bool, str]] = []

    # 1. root-form Discourse (forum.openwrt.org 실제 generator meta reproduce) → 매칭.
    html_ow = ('<html><head><meta name="generator" content="Discourse 2026.5.0-latest.1 - '
               'https://github.com/discourse/discourse"><title>OpenWrt Forum</title></head></html>')
    out = detect_discourse_platform(html=html_ow, base_url="https://forum.openwrt.org/")
    cases.append(("openwrt_root_matches",
                  out is not None and out["is_discourse"] is True
                  and out["base_url"] == "https://forum.openwrt.org"
                  and out["version"] == "2026.5.0-latest.1",
                  f"got {out!r}"))

    # 2. attr 순서 뒤바뀜(content 먼저)이라도 name=generator + Discourse 면 매칭 — 단, 정규식은
    #    name=generator 가 content 앞이라 가정. Discourse 는 항상 name 먼저 박음 → 이 케이스는 미매칭 허용.
    html_swift = ('<meta charset="utf-8">'
                  '<meta name="generator" content="Discourse 2026.5.0-latest - https://github.com/discourse/discourse">')
    out = detect_discourse_platform(html=html_swift, base_url="https://forums.swift.org/")
    cases.append(("swift_no_version_suffix_matches",
                  out is not None and out["is_discourse"] is True
                  and out["base_url"] == "https://forums.swift.org",
                  f"got {out!r}"))

    # 3. XenForo (generator 다름) → 미매칭 (false-positive 차단).
    html_xf = '<meta name="generator" content="XenForo">'
    out = detect_discourse_platform(html=html_xf, base_url="https://forums.macrumors.com/")
    cases.append(("xenforo_no_match", out is None, f"got {out!r}"))

    # 4. generator meta 없음 → 미매칭.
    html_plain = "<html><head><title>Some Forum</title></head><body></body></html>"
    out = detect_discourse_platform(html=html_plain, base_url="https://example.com/")
    cases.append(("no_generator_no_match", out is None, f"got {out!r}"))

    # 5. 빈 입력 → None.
    cases.append(("empty_html_none", detect_discourse_platform(html="", base_url="https://x.com/") is None, ""))
    cases.append(("empty_base_none",
                  detect_discourse_platform(html=html_ow, base_url="") is None, ""))

    # 6. base_url 호스트만 추출 — path 붙어도 base 로 정규화.
    out = detect_discourse_platform(html=html_ow, base_url="https://community.fly.io/latest?foo=1")
    cases.append(("path_stripped_to_base",
                  out is not None and out["base_url"] == "https://community.fly.io",
                  f"got {out!r}"))

    return cases
