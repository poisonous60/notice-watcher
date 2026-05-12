"""봇/notify 공용 설정 — .env(있으면) 로드 + 환경변수 접근.

systemd 에선 `EnvironmentFile=<repo>/.env` 가 진실의 원천이라 굳이 필요 없지만,
개발 박스/수동 실행 때를 위해 best-effort 로 `<repo>/.env` 를 파싱한다. (python-dotenv 의존 추가 안 함.)
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = ROOT / ".env"
_loaded = False


def load_env() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not _ENV_PATH.exists():
        return
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)  # 이미 있는 env(systemd 등)를 덮지 않음


def bot_token() -> str:
    load_env()
    return os.environ.get("BOT_TOKEN", "").strip()


def owner_user_id() -> str:
    load_env()
    return os.environ.get("OWNER_USER_ID", "").strip()


def safe_browsing_api_key() -> str:
    """Google Safe Browsing API 키 (URL 게이트 4단계). 없으면 게이트가 fail-closed 로 신규 등록을 전부 거부.
    발급: GCP 콘솔 → Safe Browsing API 사용 설정 → API 키 생성 → 그 키를 Safe Browsing API 로만 제한(권장).
    주의: .env 인라인 주석(KEY=val # ...)은 지원 안 함 — 값만 적을 것."""
    load_env()
    return os.environ.get("SAFE_BROWSING_API_KEY", "").strip()


def guild_id() -> int | None:
    load_env()
    v = os.environ.get("GUILD_ID", "").strip()
    return int(v) if v.isdigit() else None
