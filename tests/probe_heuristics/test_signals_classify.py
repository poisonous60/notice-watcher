"""probe.signals.classify — 응답 분류 회귀 테스트.

regression: 2026-05-16 — robots.txt 가 193 bytes (정상 크기) 인데
"<200 bytes 의심" 휴리스틱에 걸려 BLOCKED_BOT 으로 오분류되던 버그.
is_robots_txt=True 일 때 size 임계 안 적용해야 함.
"""
from __future__ import annotations


covers = ["signals_classify_robots_size"]


def run() -> list[tuple[str, bool, str]]:
    from probe.signals import classify
    from probe.types import Classification

    cases: list[tuple[str, bool, str]] = []

    # 1. robots.txt 200 + 193 bytes → OK (이전엔 BLOCKED_BOT 으로 오분류)
    short_robots = (
        "User-agent: *\n"
        "Disallow: /wp-admin/\n"
        "Allow: /wp-admin/admin-ajax.php\n"
        "Sitemap: https://example.com/sitemap.xml\n"
    )  # ~140 bytes
    cls, _ = classify(
        status=200,
        body=short_robots,
        headers={"content-type": "text/plain"},
        is_robots_txt=True,
    )
    cases.append(("robots_short_body_is_ok", cls == Classification.OK,
                  f"got {cls!r} for {len(short_robots)} byte robots.txt"))

    # 2. 일반 페이지 200 + 50 bytes → 여전히 BLOCKED_BOT (UA 필터 의심) — 회귀 차단
    cls2, _ = classify(
        status=200,
        body="<html><body>blocked</body></html>",
        headers={},
        is_robots_txt=False,
    )
    cases.append(("html_short_body_still_blocked", cls2 == Classification.BLOCKED_BOT,
                  f"got {cls2!r}"))

    # 3. robots.txt 비어 있어도 (0 bytes) OK — 일부 사이트가 빈 robots 응답
    cls3, _ = classify(
        status=200, body="", headers={}, is_robots_txt=True,
    )
    cases.append(("robots_empty_is_ok", cls3 == Classification.OK, f"got {cls3!r}"))

    # 4. is_robots_txt 미지정 (default False) → 기존 동작 보존
    cls4, _ = classify(status=200, body=short_robots, headers={})
    cases.append(("default_no_robots_flag_keeps_old_behavior",
                  cls4 == Classification.BLOCKED_BOT,
                  f"got {cls4!r}"))

    return cases
