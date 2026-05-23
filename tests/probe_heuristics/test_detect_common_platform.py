"""probe.extract.detect_common_platform -- Common SPA shell marker 판정."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_common_platform

    cases: list[tuple[str, bool, str]] = []

    sushi_shell = """
    <html>
      <head>
        <title>Common</title>
        <meta property="og:site_name" content="Common">
        <link rel="modulepreload" href="/assets/index-BmkLq.js">
        <link rel="icon" href="/brand_assets/common/favicon.ico">
      </head>
      <body><script>fetch('/api/internal/trpc/thread.getThreads')</script></body>
    </html>
    """
    out = detect_common_platform(sushi_shell, "https://forum.sushi.com/discussions")
    cases.append(("sushi_custom_domain_matches_without_hint",
                  out is not None
                  and out["is_common"] is True
                  and out["base_url"] == "https://forum.sushi.com"
                  and out["community_id_hint"] is None,
                  f"got {out!r}"))

    common_shell = """
    <html>
      <head>
        <title>Common</title>
        <script type="module" src="/assets/index-DEAD.js"></script>
      </head>
      <body><img src="/brand_assets/common/logo.svg"></body>
    </html>
    """
    out = detect_common_platform(common_shell, "https://common.xyz/osmosis/discussions")
    cases.append(("common_xyz_path_hint",
                  out is not None
                  and out["base_url"] == "https://common.xyz"
                  and out["community_id_hint"] == "osmosis",
                  f"got {out!r}"))

    out = detect_common_platform(common_shell, "https://commonwealth.im/dydx/discussions")
    cases.append(("commonwealth_im_path_hint",
                  out is not None
                  and out["base_url"] == "https://commonwealth.im"
                  and out["community_id_hint"] == "dydx",
                  f"got {out!r}"))

    plain = "<html><head><title>Commonwealth Bank</title></head><body></body></html>"
    out = detect_common_platform(plain, "https://example.com/discussions")
    cases.append(("plain_common_word_no_match", out is None, f"got {out!r}"))

    cases.append(("empty_html_none", detect_common_platform("", "https://common.xyz/osmosis/discussions") is None, ""))
    cases.append(("empty_base_none", detect_common_platform(common_shell, "") is None, ""))

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
