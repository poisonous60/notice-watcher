"""deliver_due owner-broken-alert — silent poll breakage 봉합 회귀 테스트 (2026-05-31).

검증:
1. unalerted_broken — BROKEN sidecar 1건 → episode 미알림이면 반환.
2. mark_broken_alerted → 같은 episode 는 dedup (재호출 시 안 나옴).
3. 새 episode (first_at 변경) → 재알림 대상.
4. mark_broken_alerted 가 복구(unlink)된 slug 를 state 에서 prune.
5. _alert_owner_broken dry=True → send_dm 미호출 + 마킹 X (다음 실발송 때 재알림).
6. _alert_owner_broken dry=False → send_dm 1회 호출 + 마킹 → 이후 unalerted 비움.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write_broken(sd: Path, slug: str, first_at: str, *, cb: int = 3,
                  last_status: str = "poll_timeout", last_note: str = "wait_for cap=180s") -> None:
    p = sd / f"{slug}.BROKEN.json"
    p.write_text(json.dumps({
        "slug": slug, "url": f"https://{slug}/", "first_at": first_at, "last_at": first_at,
        "count": 1, "consecutive_breakage": cb, "last_status": last_status, "last_note": last_note,
    }, ensure_ascii=False), encoding="utf-8")


def run() -> list[tuple[str, bool, str]]:
    from bot import site_ops
    import scripts.deliver_due as dd
    cases: list[tuple[str, bool, str]] = []

    tmp = Path(tempfile.mkdtemp(prefix="owner_alert_"))
    sd = tmp / "poll_state"
    sd.mkdir()

    orig_sd = site_ops.STATE_DIR
    orig_alert_state = site_ops._OWNER_ALERT_STATE
    orig_send = dd.send_dm
    orig_owner = dd.owner_user_id
    site_ops.STATE_DIR = sd
    site_ops._OWNER_ALERT_STATE = sd / "_owner_broken_alerts.json"

    sent: list[tuple[str, str]] = []
    dd.send_dm = lambda tok, uid, content: sent.append((uid, content))
    dd.owner_user_id = lambda: "999"

    try:
        # 1. 미알림 broken → unalerted 에 나옴
        _write_broken(sd, "siteA", "2026-05-31T00:00:00+00:00")
        u1 = site_ops.unalerted_broken()
        cases.append(("unalerted_broken returns new broken episode",
                      len(u1) == 1 and u1[0]["slug"] == "siteA", f"got {[i.get('slug') for i in u1]}"))

        # 2. 마킹 후 같은 episode dedup
        site_ops.mark_broken_alerted(u1)
        u2 = site_ops.unalerted_broken()
        cases.append(("same episode deduped after mark", u2 == [], f"got {[i.get('slug') for i in u2]}"))

        # 3. 새 episode (first_at 변경) → 재알림
        _write_broken(sd, "siteA", "2026-06-05T00:00:00+00:00")
        u3 = site_ops.unalerted_broken()
        cases.append(("new episode (changed first_at) re-alerts",
                      len(u3) == 1 and u3[0]["slug"] == "siteA", f"got {[i.get('first_at') for i in u3]}"))
        site_ops.mark_broken_alerted(u3)

        # 4. 복구(unlink)된 slug prune — siteB 알림 후 siteA sidecar 제거하고 siteB 만 마킹하면 state 에 siteA 없음
        (sd / "siteA.BROKEN.json").unlink()
        _write_broken(sd, "siteB", "2026-06-06T00:00:00+00:00")
        site_ops.mark_broken_alerted(site_ops.unalerted_broken())
        state = json.loads(site_ops._OWNER_ALERT_STATE.read_text(encoding="utf-8"))
        cases.append(("recovered slug pruned from alert state",
                      "siteA" not in state and "siteB" in state, f"state keys {list(state)}"))

        # 5. dry=True → 발송/마킹 X. 새 broken 만들고 dry 호출 후에도 unalerted 에 남아야.
        (sd / "siteB.BROKEN.json").unlink()
        _write_broken(sd, "siteC", "2026-06-07T00:00:00+00:00")
        sent.clear()
        dd._alert_owner_broken("tok", "999", dry=True)
        u5 = site_ops.unalerted_broken()
        cases.append(("dry alert does not send nor mark",
                      sent == [] and any(i["slug"] == "siteC" for i in u5),
                      f"sent={len(sent)}, unalerted={[i.get('slug') for i in u5]}"))

        # 6. dry=False → send 1회 + 마킹 → 이후 unalerted 비움
        dd._alert_owner_broken("tok", "999", dry=False)
        u6 = site_ops.unalerted_broken()
        ok6 = len(sent) == 1 and sent[0][0] == "999" and u6 == []
        cases.append(("real alert sends once to owner and marks", ok6,
                      f"sent={sent[:1]}, unalerted_after={[i.get('slug') for i in u6]}"))

        return cases
    finally:
        site_ops.STATE_DIR = orig_sd
        site_ops._OWNER_ALERT_STATE = orig_alert_state
        dd.send_dm = orig_send
        dd.owner_user_id = orig_owner
