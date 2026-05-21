"""probe.extract.detect_xenforo_platform — 렌더 HTML 의 `<html id=XF>`/`XF.config` 마커로 XenForo 판정.

XenForo public 페이지는 `<html id="XF" ... data-app="public">` + `XF.config = {...}` JS 박음.
register.py 가 is_xenforo=true 면 LLM 전 전역 RSS config 등록 시도. false-positive ~0 필수 —
Discourse/IPS/phpBB 는 이 마커 안 씀.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_xenforo_platform

    cases: list[tuple[str, bool, str]] = []

    # 1. <html id="XF"> 마커 (wordreference/hardforum 실제 폼) → 매칭, base 정규화.
    html_xf = ('<!DOCTYPE html><html id="XF" lang="en" dir="LTR" data-app="public" '
               'data-template="forum_list"><head><title>WordReference Forums</title></head></html>')
    out = detect_xenforo_platform(html=html_xf, base_url="https://forum.wordreference.com/")
    cases.append(("html_id_xf_matches",
                  out is not None and out["is_xenforo"] is True
                  and out["base_url"] == "https://forum.wordreference.com",
                  f"got {out!r}"))

    # 2. XF.config JS 마커만 있어도 매칭 (id=XF 없는 변형).
    html_cfg = '<html><head><script>window.XF = {}; XF.config = {"userId":0};</script></head></html>'
    out = detect_xenforo_platform(html=html_cfg, base_url="https://hardforum.com/")
    cases.append(("xf_config_js_matches",
                  out is not None and out["base_url"] == "https://hardforum.com",
                  f"got {out!r}"))

    # 3. Discourse generator meta → 미매칭 (false-positive 차단).
    html_disc = '<meta name="generator" content="Discourse 2026.5.0">'
    cases.append(("discourse_no_match",
                  detect_xenforo_platform(html=html_disc, base_url="https://forum.openwrt.org/") is None,
                  ""))

    # 4. 마커 없는 평범한 HTML → 미매칭.
    cases.append(("plain_no_match",
                  detect_xenforo_platform(html="<html><body>hi</body></html>", base_url="https://x.com/") is None,
                  ""))

    # 5. 빈 입력 → None.
    cases.append(("empty_html_none", detect_xenforo_platform(html="", base_url="https://x.com/") is None, ""))
    cases.append(("empty_base_none", detect_xenforo_platform(html=html_xf, base_url="") is None, ""))

    # 6. base_url path 붙어도 base 로 정규화.
    out = detect_xenforo_platform(html=html_xf, base_url="https://www.avsforum.com/whats-new/posts/?x=1")
    cases.append(("path_stripped_to_base",
                  out is not None and out["base_url"] == "https://www.avsforum.com",
                  f"got {out!r}"))

    # 7. 서브폴더 설치 — install path 보존 (route 세그먼트 앞 prefix 유지).
    out = detect_xenforo_platform(html=html_xf, base_url="https://xenforo.com/community/")
    cases.append(("subpath_install_preserved",
                  out is not None and out["base_url"] == "https://xenforo.com/community",
                  f"got {out!r}"))

    return cases
