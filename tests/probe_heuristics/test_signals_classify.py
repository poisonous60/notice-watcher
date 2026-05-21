"""probe.signals.classify — 응답 분류 회귀 테스트.

regression: 2026-05-16 — robots.txt 가 193 bytes (정상 크기) 인데
"<200 bytes 의심" 휴리스틱에 걸려 BLOCKED_BOT 으로 오분류되던 버그.
is_robots_txt=True 일 때 size 임계 안 적용해야 함.
"""
from __future__ import annotations


covers = ["signals_classify_robots_size", "signals_classify_js_challenge"]


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

    # 5. JS-챌린지 인터스티셜 (status 200 위장, 마커가 script/href 안 — _strip_scripts 로 지워짐).
    #    2026-05-21-forums: board_shape gate_reject 로 오분류되던 anti-bot 페이지를 BLOCKED_BOT 으로.
    challenges = {
        # Anubis PoW 풀 페이지 (lazarus/techpowerup)
        "anubis_full": '<html><head><title>Making sure you\'re not a bot!</title>'
                       '<link href="/.within.website/x/xess/xess.min.css">'
                       '<script id="anubis_challenge" type="application/json">{}</script></head>'
                       '<body>' + ("x" * 4000) + '</body></html>',
        # Anubis 경량 redirect 변형 (debian) — title "Loading...", 마커는 noscript+script
        "anubis_redirect": '<html><head><title>Loading...</title></head><body>Loading'
                           '<noscript><a href="/app.php/anubis/api/make_challenge">Click</a></noscript>'
                           '<script>setTimeout(goto,500)</script></body></html>',
        # Cloudflare 인터스티셜 (simplemachines) — 마커 cdn-cgi/challenge-platform·__cf_chl 가 script 안
        "cloudflare": '<html><head><title>잠시만 기다리십시오…</title></head><body>'
                      '<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/__cf_chl/v1"></script>'
                      + ("y" * 25000) + '</body></html>',
    }
    for nm, body in challenges.items():
        cls, notable = classify(status=200, body=body, headers={})
        cases.append((f"js_challenge_{nm}_blocked", cls == Classification.BLOCKED_BOT,
                      f"got {cls!r} notable={notable[:1]}"))

    # 6. 정상 포럼 (챌린지 마커 없음, 본문 충분) → OK (false-positive 회귀 차단).
    normal = ('<html><head><title>Debian User Forums</title></head><body>'
              + ('<div class="topic"><a href="/viewtopic.php?t=1">글</a></div>' * 60)
              + '</body></html>')
    cls_n, _ = classify(status=200, body=normal, headers={})
    cases.append(("normal_forum_not_blocked", cls_n == Classification.OK, f"got {cls_n!r}"))

    return cases
