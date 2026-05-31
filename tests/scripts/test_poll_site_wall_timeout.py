"""poll.py per-site delay-aware wall timeout — deadlock 봉합 회귀 테스트 (2026-05-31).

검증:
1. _polite_sleep_max — config polite_sleep 에 엔진 floor 적용 (config_adapter 와 동일).
2. _polite_sleep_max — config_path 없으면 엔진 기본 상한.
3. _site_wall_timeout — fast 사이트(작은 polite_sleep) 는 base 그대로 (절대 안 줄어듦).
4. _site_wall_timeout — 느린 사이트(polite_sleep×max_new_articles > base) 는 base 초과 예산.
5. dcinside 30-35s × 10 글이 옛 180s cap 을 넘었음을 수치로 못박음 (회귀 가드).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write_cfg(d: Path, name: str, polite_sleep: dict | None) -> Path:
    cfg = {"version": 1, "site": "x", "board": "b", "strategy": "httpx_html",
           "list": {"url_template": "https://x/", "fields": {}}}
    if polite_sleep is not None:
        cfg["polite_sleep"] = polite_sleep
    p = d / name
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


def run() -> list[tuple[str, bool, str]]:
    import scripts.poll as poll
    from engine.config_adapter import _DEFAULT_SLEEP_MAX
    cases: list[tuple[str, bool, str]] = []

    tmp = Path(tempfile.mkdtemp(prefix="poll_wall_to_"))

    # 1. floor 적용 — config 1/2 는 엔진 floor(3/6) 아래라 무시 → 상한 = _DEFAULT_SLEEP_MAX
    cfg_fast = _write_cfg(tmp, "fast.json", {"min": 1.0, "max": 2.0})
    pmax_fast = poll._polite_sleep_max({"config_path": str(cfg_fast)})
    ok = pmax_fast == _DEFAULT_SLEEP_MAX
    cases.append(("polite_sleep_max floors below default to engine max", ok,
                  f"got {pmax_fast}, want {_DEFAULT_SLEEP_MAX}"))

    # 2. config_path 없음 → 엔진 기본 상한
    pmax_none = poll._polite_sleep_max({})
    cases.append(("polite_sleep_max defaults when no config_path",
                  pmax_none == _DEFAULT_SLEEP_MAX, f"got {pmax_none}"))

    # 3. config 35 → 35 (느린 사이트 그대로 상한)
    cfg_slow = _write_cfg(tmp, "slow.json", {"min": 30.0, "max": 35.0})
    pmax_slow = poll._polite_sleep_max({"config_path": str(cfg_slow)})
    cases.append(("polite_sleep_max keeps high config value", pmax_slow == 35.0, f"got {pmax_slow}"))

    # 4. fast 사이트 → base 그대로 (cap 은 max 라 절대 줄지 않음 = 기존 사이트 regression 0)
    base = poll.POLL_SITE_TIMEOUT_S
    to_fast = poll._site_wall_timeout({"config_path": str(cfg_fast)}, base=base, max_new_articles=10)
    cases.append(("fast site keeps base wall timeout", to_fast == float(base),
                  f"got {to_fast}, base {base}"))

    # 5. 느린 사이트 → base 초과 예산. (n-1)*pmax + n*8 + 30 = 9*35 + 80 + 30 = 425
    to_slow = poll._site_wall_timeout({"config_path": str(cfg_slow)}, base=base, max_new_articles=10)
    want_slow = 9 * 35.0 + 10 * poll._ARTICLE_FETCH_BUDGET_S + poll._WALL_OVERHEAD_S
    ok_slow = to_slow == want_slow and to_slow > base
    cases.append(("slow site extends wall timeout above base", ok_slow,
                  f"got {to_slow}, want {want_slow} (> base {base})"))

    # 6. 회귀 가드 — 옛 dcinside 30-35s config 를 _site_wall_timeout 에 통과시키면 base 초과
    #    예산이 나와야 함 (production fn 직접 호출 — 옛 고정 180s cap 이 deadlock 낸 조건).
    to_old = poll._site_wall_timeout({"config_path": str(cfg_slow)}, base=180.0, max_new_articles=10)
    cases.append(("old dcinside 30-35s config now gets budget above old fixed 180s cap",
                  to_old > 180.0, f"_site_wall_timeout -> {to_old}s (> old 180s)"))

    return cases
