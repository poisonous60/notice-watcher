"""호출 간 sleep 헬퍼.

probe 는 *대화형 1회 정찰* — 한 호스트에 요청 몇 번 보내고 끝난다(폴링이 아님). 그래서 운영 폴링
(어댑터/엔진: 2~5초, dcinside 30s 등 — `docs/크롤링 지침.md` §2-2)보다 짧게 잡는다: 기본 1~2초 + jitter ±30%.
(과거엔 5~7초였는데 정찰 한 번이 수 분 걸려서 줄임. 그래도 jitter 는 유지 — 고정 간격이 봇 탐지에 더 잘 걸린다.)
운영 폴링 쪽 sleep 은 `adapters/base.BaseAdapter.polite_sleep` / config 의 `polite_sleep` 가 따로 관리하며 여기 영향 안 받는다.
"""
from __future__ import annotations

import random
import time


def polite_sleep(min_sec: float = 1.0, max_sec: float = 2.0) -> None:
    base = random.uniform(min_sec, max_sec)
    jitter = base * random.uniform(-0.3, 0.3)
    time.sleep(max(0.3, base + jitter))
