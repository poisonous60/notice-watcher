"""fediverse social detect-reject + Lemmy rc=5 API rescue."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

covers = ["detect_mastodon_platform", "detect_misskey_platform", "detect_pixelfed_platform"]


def _load_register():
    rp = Path(__file__).resolve().parent.parent.parent / "scripts" / "register.py"
    spec = importlib.util.spec_from_file_location("reg_social_under_test", rp)
    reg = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(reg)
    return reg


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize
    from probe.extract import (
        detect_mastodon_platform,
        detect_misskey_platform,
        detect_pixelfed_platform,
    )

    cases: list[tuple[str, bool, str]] = []

    mastodon_html = (
        '<script id="initial-state" type="application/json">'
        '{"meta":{"streaming_api":"wss://techhub.social/api/v1/streaming"}}</script>'
        '<div class="notranslate app-holder" id="mastodon"></div>'
        '<noscript>Mastodon requires JavaScript</noscript>'
    )
    out = detect_mastodon_platform(html=mastodon_html, base_url="https://techhub.social/about")
    cases.append(("mastodon_app_shell_matches",
                  out == {"is_mastodon": True, "base_url": "https://techhub.social"},
                  f"got {out!r}"))

    misskey_html = (
        '<html><head><meta property="og:site_name" content="Misskey">'
        '<title>misskey.io - Misskey</title></head>'
        '<body><script>window.__misskey = {}</script></body></html>'
    )
    out = detect_misskey_platform(html=misskey_html, base_url="https://misskey.io/")
    cases.append(("misskey_app_shell_matches",
                  out == {"is_misskey": True, "base_url": "https://misskey.io"},
                  f"got {out!r}"))

    pixelfed_html = (
        '<html><head><meta name="generator" content="Pixelfed">'
        '<meta property="og:site_name" content="Pixelfed"></head>'
        '<body><script>window.App.config = {"pixelfed":true}</script></body></html>'
    )
    out = detect_pixelfed_platform(html=pixelfed_html, base_url="https://pixelfed.social/")
    cases.append(("pixelfed_app_shell_matches",
                  out == {"is_pixelfed": True, "base_url": "https://pixelfed.social"},
                  f"got {out!r}"))

    pixey_html = '<html><head><title>Pixey</title></head><body><noscript><h1>Pixelfed</h1></noscript></body></html>'
    out = detect_pixelfed_platform(html=pixey_html, base_url="https://pixey.org/")
    cases.append(("pixelfed_noscript_matches",
                  out == {"is_pixelfed": True, "base_url": "https://pixey.org"},
                  f"got {out!r}"))

    board_html = (
        '<html><head><title>Notice Board</title></head><body>'
        '<main><article><a href="/notice/1">Mastodon maintenance notice</a></article>'
        '<article><a href="/notice/2">Misskey bridge notice</a></article></main></body></html>'
    )
    cases.append(("plain_board_no_social_match",
                  detect_mastodon_platform(board_html, "https://example.edu/notices") is None
                  and detect_misskey_platform(board_html, "https://example.edu/notices") is None
                  and detect_pixelfed_platform(board_html, "https://example.edu/notices") is None,
                  ""))

    cases.append(("social_roots_not_url_recognized",
                  recognize("https://techhub.social/about") is None
                  and recognize("https://misskey.io/") is None
                  and recognize("https://pixelfed.social/") is None,
                  ""))

    reg = _load_register()
    saved: list = []
    orig_save = reg._save_rejected
    reg._save_rejected = lambda *a, **k: saved.append((a, k))
    try:
        dispatch_cases = [
            ("mastodon_platform", "is_mastodon", "https://techhub.social", "https://techhub.social/about"),
            ("misskey_platform", "is_misskey", "https://misskey.io", "https://misskey.io/"),
            ("pixelfed_platform", "is_pixelfed", "https://pixelfed.social", "https://pixelfed.social/"),
        ]
        for key, flag, base, url in dispatch_cases:
            saved.clear()
            digest = {"list_candidates": {key: {flag: True, "base_url": base}}}
            rc = reg._social_platform_reject(digest, url, "host_social_test")
            ok = rc == 3 and len(saved) == 1 and saved[0][1].get("learn") is False
            cases.append((f"{key}_reject_dispatch", ok, f"rc={rc} saved={saved!r}"))
    finally:
        reg._save_rejected = orig_save

    orig_httpx = sys.modules.get("httpx")
    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"site_view": {"site": {"name": "Example Lemmy"}}, "version": "0.19.18"}

    def _fake_register(cfg, slug, url, *, out, force):
        captured.update({"cfg": cfg, "slug": slug, "url": url, "out": out, "force": force})
        return 0

    sys.modules["httpx"] = SimpleNamespace(get=lambda *a, **k: _Resp())
    orig_reg = reg._register_built_config
    reg._register_built_config = _fake_register
    try:
        rc = reg._try_lemmy_api_rescue("https://lemmy.world/", "host_lemmy-world_root_x", out=None, force=False)
        ok = rc == 0 and captured.get("cfg", {}).get("adapter") == "LemmyAdapter"
        cases.append(("lemmy_api_rescue_registers", ok, f"rc={rc} captured={captured!r}"))
    finally:
        reg._register_built_config = orig_reg
        if orig_httpx is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = orig_httpx

    return cases


if __name__ == "__main__":
    results = run()
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    failed = [r for r in results if not r[1]]
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
