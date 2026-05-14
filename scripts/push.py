"""dev박스 → N100 파일 push CLI. `inspect_subs.py pull` 의 대칭.

운영 컨피그/라우팅을 N100 에 반영할 때 사용. dashboard 가 subprocess 로도 호출.

사용:
    python scripts/push.py routing                     # output/llm_routing.json
    python scripts/push.py runtime                     # config.local.toml
    python scripts/push.py prices                      # model_prices.json
    python scripts/push.py config <slug>               # configs/<slug>.json (Claude code 가 작성한 것 push)
    python scripts/push.py env                         # .env (로컬 .env.push 가 있을 때만)
    python scripts/push.py timer                       # notice-poll.timer (~/.config/systemd/user/)

N100 호스트: `DEPLOY_HOST` (기본 `aaaa@<lan-ip>`), `DEPLOY_PATH` (기본 `~/notice-watcher`).

설계:
- target 종류는 allowlist (TARGETS dict). 임의 파일 path 인자 안 받음 → SSH/scp injection 차단.
- slug 인자는 정규식 검증 (engine 의 slug 규약과 동일).
- env push 는 `.env.push` 가 있을 때만 — 실수로 dev 박스 본인 `.env` 가 올라가지 않도록 차단.
- 결과 코드: 0=성공, 2=원격 실패, 3=로컬 파일 없음, 4=인자 오류.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "aaaa@<lan-ip>")
DEPLOY_PATH = os.environ.get("DEPLOY_PATH", "~/notice-watcher")


_SLUG_RE = re.compile(r"^[A-Za-z0-9._\-]{1,200}$")


def _safe_slug(s: str) -> bool:
    return bool(_SLUG_RE.match(s or ""))


@dataclass(frozen=True)
class _Target:
    """allowlisted push target.

    local_path : repo-relative 로컬 소스 path (slug 인 경우 fmt 후 채워짐).
    remote_path: N100 destination — shell expansion 됨 (`~/` 허용). DEPLOY_PATH/... 형식.
    """
    name: str
    local_path: str           # `{slug}` 치환 지원
    remote_path: str          # `{DEPLOY_PATH}` 치환 지원. `~/.config/...` 절대 path 도 가능
    needs_slug: bool = False
    requires_systemd_reload: bool = False
    description: str = ""


TARGETS: dict[str, _Target] = {
    "routing": _Target(
        name="routing",
        local_path="output/llm_routing.json",
        remote_path="{DEPLOY_PATH}/output/llm_routing.json",
        description="LLM call_site → model 매핑 (mtime 캐시 즉시 반영)",
    ),
    "runtime": _Target(
        name="runtime",
        local_path="config.local.toml",
        remote_path="{DEPLOY_PATH}/config.local.toml",
        description="머신별 runtime 튜닝 override — 봇/폴링 재시작 필요",
    ),
    "prices": _Target(
        name="prices",
        local_path="model_prices.json",
        remote_path="{DEPLOY_PATH}/model_prices.json",
        description="LLM 모델 단가표 — 다음 호출부터 적용",
    ),
    "config": _Target(
        name="config",
        local_path="configs/{slug}.json",
        remote_path="{DEPLOY_PATH}/configs/{slug}.json",
        needs_slug=True,
        description="사이트별 크롤링 config — 다음 polling 부터 적용",
    ),
    "env": _Target(
        name="env",
        local_path=".env.push",                # 안전장치: 별도 파일명만 push
        remote_path="{DEPLOY_PATH}/.env",
        description="환경변수/비밀. systemd 재시작 필요. dev박스 .env 가 아닌 .env.push 만 push",
    ),
    "timer": _Target(
        name="timer",
        local_path="output/notice-poll.timer",  # dashboard 가 여기에 작성해 두고 push
        remote_path="~/.config/systemd/user/notice-poll.timer",
        requires_systemd_reload=True,
        description="notice-poll.timer — daemon-reload + restart 필요",
    ),
}


def _resolve_remote(target: _Target, slug: Optional[str]) -> str:
    rp = target.remote_path.format(DEPLOY_PATH=DEPLOY_PATH, slug=slug or "")
    return rp


def _resolve_local(target: _Target, slug: Optional[str]) -> Path:
    return ROOT / target.local_path.format(slug=slug or "")


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode, out


def push(target_name: str, slug: Optional[str] = None) -> int:
    if target_name not in TARGETS:
        print(f"[push] 알 수 없는 target: {target_name!r}. 허용: {sorted(TARGETS)}", file=sys.stderr)
        return 4
    t = TARGETS[target_name]
    if t.needs_slug:
        if not slug or not _safe_slug(slug):
            print(f"[push] target={target_name} 은 안전한 slug 인자가 필요합니다.", file=sys.stderr)
            return 4
    local = _resolve_local(t, slug)
    if not local.exists():
        print(f"[push] 로컬 파일 없음: {local}", file=sys.stderr)
        return 3
    remote = _resolve_remote(t, slug)
    rc, out = _run(["scp", "-q", str(local), f"{DEPLOY_HOST}:{remote}"])
    if rc != 0:
        print(f"[push] scp 실패 (rc={rc}): {out}", file=sys.stderr)
        return 2
    print(f"[push] {local} → {DEPLOY_HOST}:{remote}  OK ({local.stat().st_size:,} bytes)")
    if t.requires_systemd_reload:
        rc2, out2 = _run(["ssh", DEPLOY_HOST, "systemctl --user daemon-reload"])
        if rc2 != 0:
            print(f"[push] daemon-reload 실패 (rc={rc2}): {out2}", file=sys.stderr)
            return 2
        print(f"[push] systemctl --user daemon-reload  OK")
    return 0


def list_targets() -> int:
    w = max(len(k) for k in TARGETS) + 2
    for name in sorted(TARGETS):
        t = TARGETS[name]
        slug_mark = " <slug>" if t.needs_slug else ""
        print(f"  {name:<{w}}{slug_mark}  {t.description}")
        print(f"  {'':<{w}}        local : {t.local_path}")
        print(f"  {'':<{w}}        remote: {t.remote_path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="dev박스 → N100 파일 push (allowlist)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in TARGETS:
        s = sub.add_parser(name, help=TARGETS[name].description)
        if TARGETS[name].needs_slug:
            s.add_argument("slug")
    sub.add_parser("list", help="허용 target 출력")
    args = p.parse_args(argv)
    if args.cmd == "list":
        return list_targets()
    slug = getattr(args, "slug", None)
    return push(args.cmd, slug=slug)


if __name__ == "__main__":
    sys.exit(main())
