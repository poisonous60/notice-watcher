"""호출 간 sleep 헬퍼. 크롤링 지침: 같은 호스트 사이 2~5초 + jitter ±30%."""
from __future__ import annotations

import random
import time


def polite_sleep(min_sec: float = 5.0, max_sec: float = 7.0) -> None:
    base = random.uniform(min_sec, max_sec)
    jitter = base * random.uniform(-0.3, 0.3)
    time.sleep(max(0.5, base + jitter))
