"""봇 토큰으로 Discord REST 직접 호출 — 게이트웨이 봇 프로세스 없이도 DM/채널 메시지 발송.

notify.py(폴링 후 발송)가 이걸 쓴다. 봇 프로세스가 떠 있을 필요 없음(게이트웨이는 슬래시 명령 *수신* 용).
webhook 발송도 같이 노출 — BOT_TOKEN 없을 때 fallback.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

API = "https://discord.com/api/v10"
_MAX_CONTENT = 1900  # 2000 제한 - 여유


class DiscordRestError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Discord REST {status}: {body[:300]}")
        self.status = status
        self.body = body


class CannotDeliver(DiscordRestError):
    """403 등 — 그 대상에게는 못 보냄 (DM 닫힘 / 길드에 봇 없음). 호출부는 로그+skip."""


def _truncate(content: str) -> str:
    return content if len(content) <= _MAX_CONTENT else content[:_MAX_CONTENT] + "…(잘림)"


def _headers(bot_token: str) -> dict:
    return {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}


def _post(url: str, *, headers: dict, json_body: dict, timeout: float = 15.0) -> dict:
    for attempt in range(3):
        r = httpx.post(url, headers=headers, json=json_body, timeout=timeout)
        if r.status_code in (200, 201, 204):
            return r.json() if r.content else {}
        if r.status_code == 429:
            try:
                retry_after = float(r.json().get("retry_after", 1.0))
            except Exception:  # noqa: BLE001
                retry_after = 1.0
            time.sleep(min(retry_after + 0.2, 10.0))
            continue
        if r.status_code in (403, 404):
            raise CannotDeliver(r.status_code, r.text)
        raise DiscordRestError(r.status_code, r.text)
    raise DiscordRestError(429, "rate limited, gave up after retries")


# in-process 캐시: user_id -> dm channel_id (DM 채널은 안정적)
_DM_CACHE: dict[str, str] = {}


def open_dm_channel(bot_token: str, user_id: str) -> str:
    cid = _DM_CACHE.get(user_id)
    if cid:
        return cid
    data = _post(f"{API}/users/@me/channels", headers=_headers(bot_token),
                 json_body={"recipient_id": str(user_id)})
    cid = str(data["id"])
    _DM_CACHE[user_id] = cid
    return cid


def post_message(bot_token: str, channel_id: str, content: str) -> None:
    _post(f"{API}/channels/{channel_id}/messages", headers=_headers(bot_token),
          json_body={"content": _truncate(content)})


def send_dm(bot_token: str, user_id: str, content: str) -> None:
    post_message(bot_token, open_dm_channel(bot_token, user_id), content)


def post_webhook(webhook_url: str, content: str, *, timeout: float = 15.0) -> None:
    r = httpx.post(webhook_url, json={"content": _truncate(content)}, timeout=timeout)
    r.raise_for_status()


def deliver(bot_token: Optional[str], *, target_kind: str, target_id: str, content: str) -> None:
    """target_kind='dm' → DM, 'channel' → 그 채널. bot_token 없으면 에러."""
    if not bot_token:
        raise DiscordRestError(0, "BOT_TOKEN 없음 — DM/채널 발송 불가 (webhook fallback 을 쓰세요)")
    if target_kind == "dm":
        send_dm(bot_token, target_id, content)
    elif target_kind == "channel":
        post_message(bot_token, target_id, content)
    else:
        raise DiscordRestError(0, f"알 수 없는 target_kind: {target_kind}")
