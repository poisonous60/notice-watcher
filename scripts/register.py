"""사이트 등록: URL → lite probe → preflight(글페이지 HAR re-probe + probe 신호 hint) → digest → gemini(≤max_attempts) → config 저장 + baseline state.

preflight (gemini 부르기 *전에* 1회, --no-escalate 면 생략):
  (a) probe 가 잡은 첫 글 페이지를 Playwright+HAR 로 re-probe → 본문 JSON API 후보(article_candidates.json) + 렌더된 DOM(article.html) 확보
      → 프롬프트가 이걸 '⚡ 글 본문 JSON API 후보' 블록으로 자동 첨부 (httpx 본문 대신 본문 API 를 쓰는 config / strategy=playwright_html 로 유도).
  (b) probe 신호(목록 페이지가 정적 GET 으론 안 열림 + JSON API 후보 유무)로 목록 전략 hint 를 digest.escalation_hint 에 넣어 1회차부터 제공.
  → 옛날엔 "lite gen 4번 실패 → full probe + gen 4번 → 본문 hint + gen 4번 …" 식으로 escalate 했지만(최대 16회 호출), 이제 그 정보를
     처음부터 다 주고 gen 은 max_attempts(기본 4)회만. 한 라운드 안에서 검증 피드백 재시도는 그대로(generate_config_validated).

사용:
    python scripts/register.py "https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582&srSearchKey=&srSearchVal="
    python scripts/register.py "<목록URL>" --out configs/my_board.json --max-attempts 4
    python scripts/register.py "<목록URL>" --reuse-probe       # probe 산출물 있으면 재사용
    python scripts/register.py "<목록URL>" --full-probe        # lite 대신 처음부터 full probe (외부/유료 서비스까지 — 보통 불필요)
    python scripts/register.py "<목록URL>" --no-escalate       # preflight(글페이지 re-probe + hint 주입) 생략, raw lite digest 로만 생성
    python scripts/register.py "<목록URL>" --article-url "<글페이지URL>"
        # probe 가 '첫 글'을 잘못 잡는 사이트용: 실제 글 본문 페이지 URL 을 직접 지정.
        # 그 글페이지를 render+HAR 로 미리 re-probe(본문 JSON API 후보·렌더 DOM 확보)하고 digest 의 article_sample 을 그걸로 맞춘 뒤 생성한다.

성공: configs/<slug>.json 저장 + output/poll_state/<slug>.json (baseline = 현재 글 post_id 집합).
실패: output/poll_state/<slug>.FAILED.json + "자동 처리 불가 — 손으로 config/어댑터 작성 필요" 안내.
정책: LOGIN_REQUIRED / 접근 차단 사이트는 등록 거부. robots Disallow 면 경고만 띄우고 진행.
필요: Gemini API 키 (GEMINI_API_KEYS / GEMINI_API_KEY env 또는 GEMINI_API_KEY.md 파일). 글페이지 re-probe 엔 playwright 필요.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probe.paths import output_dir, url_to_slug  # noqa: E402
from engine.digest import build_digest  # noqa: E402
from engine.recognizers import recognize as recognize_platform  # noqa: E402
from engine.tracing import start_trace, current_trace, env_for_child  # noqa: E402
from generate import generate_config_validated, GenerationError  # noqa: E402
from generate.routing import resolve as _resolve_route  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = ROOT / "configs"
STATE_DIR = ROOT / "output" / "poll_state"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_probe(url: str, *, lite: bool) -> None:
    import os
    print("[PHASE] probe", flush=True)
    print(f"[register] {'lite' if lite else 'full'} probe: {url}")
    cmd = [sys.executable, str(ROOT / "scripts" / "probe.py"), url, "--no-paid", "--no-crawl4ai"]
    if lite:
        cmd.append("--lite")
    tr = current_trace()
    with tr.span("probe_subprocess", attrs={"url": url, "lite": lite}):
        # env_for_child 는 span enter *후* 호출 — _current_span_id 가 probe_subprocess 인 상태로 잡혀야
        # probe.py 의 phase spans 가 probe_subprocess 자식으로 nested. 밖에서 잡으면 parent_span=""
        # → phase 들이 형제로 떠 dashboard 에서 collapse 불가.
        child_env = {**os.environ, **env_for_child()}
        rc = subprocess.call(cmd, env=child_env)
    if rc != 0:
        raise SystemExit(f"probe 실패 (rc={rc})")


def _entry_matrix_has_ok_list(digest: dict) -> bool:
    for r in (digest.get("entry_matrix") or []):
        if r.get("target") == "list" and r.get("classification") == "OK":
            return True
    return False


def _robots_path_matches(path: str, pattern: str) -> bool:
    """robots.txt 식 경로 매칭: 접두어 매칭 + `*` 와일드카드 + 끝의 `$` 앵커."""
    import re as _re
    p = pattern
    anchored = p.endswith("$")
    if anchored:
        p = p[:-1]
    rx = _re.escape(p).replace(r"\*", ".*")
    try:
        return _re.match("^" + rx + ("$" if anchored else ""), path) is not None
    except _re.error:
        return path.startswith(pattern.split("*", 1)[0])


def _policy_check(digest: dict, url: str) -> tuple[bool, list[str]]:
    """(등록 가능?, 메시지들). 차단/로그인이면 False. robots Disallow 면 경고만(True 유지)."""
    msgs: list[str] = []
    verdict = (digest.get("verdict") or "").lower()
    if "login" in verdict:
        return False, [f"로그인 필요 사이트 (verdict={digest.get('verdict')!r}) — 자동 등록 미지원. "
                       "로그인은 사용자가 한 번 수동으로(Playwright headful) 해야 하며 이번 단계 범위 밖."]
    if not _entry_matrix_has_ok_list(digest):
        return False, [f"목록 페이지에 정적으로도 headless 로도 접근 실패 (verdict={digest.get('verdict')!r}). "
                       "차단(BLOCKED) 사이트로 보임 — 차단 우회는 하지 않음. 등록 거부."]
    # robots Disallow — 경고만 (와일드카드 * / 끝앵커 $ 도 처리)
    path = urlsplit(url).path or "/"
    for dis in (digest.get("robots") or {}).get("disallow") or []:
        d = (dis or "").strip()
        if not d:
            continue
        if d == "/":
            msgs.append("⚠ robots.txt 가 'Disallow: /' (사이트 전체 크롤링 금지) 라고 명시. 그래도 진행은 하지만 권장하지 않음.")
            continue
        if _robots_path_matches(path, d):
            msgs.append(f"⚠ robots.txt 가 'Disallow: {d}' 라고 명시 — 이 경로({path})를 자동 접근 금지로 표시. 그래도 진행함(경고).")
    cd = (digest.get("robots") or {}).get("crawl_delay")
    if cd:
        msgs.append(f"ℹ robots.txt Crawl-Delay={cd}s — config 의 polite_sleep 에 반영(이 값 이상). 폴링/전체 스캔이 느릴 수 있음.")
    return True, msgs


# anti-bot/captcha 챌린지로 리다이렉트된 URL — board 신호로 잡으면 안 됨.
# 같은 호스트라도 사실상 "차단됐다" 는 negative 증거. 예: google.com/sorry/index 는
# Google 검색 클릭 시 abuse-detection 챌린지로 가는 자리 — clicked_same=True 로 위장됨.
_ANTIBOT_REDIRECT_PATH_PREFIXES = (
    "/sorry/",           # Google abuse-detection
    "/captcha",          # generic
    "/recaptcha",        # generic
    "/challenges/",      # Cloudflare 등
    "/challenge/",       # Cloudflare 등
    "/cdn-cgi/challenge", # Cloudflare
)


def _is_antibot_redirect(u: Optional[str]) -> bool:
    if not u:
        return False
    try:
        path = (urlsplit(u).path or "").lower()
    except ValueError:
        return False
    return any(path.startswith(pfx) for pfx in _ANTIBOT_REDIRECT_PATH_PREFIXES)


def _board_shape_check(digest: dict, url: str) -> tuple[bool, str]:
    """probe digest 만으로 '게시판 형식 같은가' 판정 — gemini 부르기 전에.
    어떤 board 신호도 같은 호스트로 안 잡히면 '게시판 아님' 단정 (rc=3 로 거부).
    신호 (어느 하나라도 있으면 통과):
      - list_candidates.traffic_json_api_candidates (목록 JSON API 후보)
      - list_candidates.inline_js_data_candidates (SPA 인라인 데이터)
      - list_candidates.hydration_list_candidates (Next/Nuxt 하이드레이션)
      - list_candidates.html_repeating_patterns 중 같은 호스트 글 링크 가진 것 (href_pattern_guess / sample_url)
      - list_candidates.first_article_url 가 같은 호스트
      - article_sample.clicked_resolved_url 가 같은 호스트 (클릭 진입 성공) — 단,
        anti-bot/captcha 챌린지 경로(`/sorry/`, `/captcha`, `/challenges/` 등)는 제외.
        같은 호스트로 보이지만 사실상 차단된 거라 board 증거가 아님 (예: google.com/sorry/index).
      - feed_candidates 비어있지 않음 (RSS/Atom)
    """
    host = (urlsplit(url).netloc or "").lower()
    if not host:
        return True, ""
    lc = digest.get("list_candidates") or {}
    ah = digest.get("article_sample") or {}

    def _same_host(u: Optional[str]) -> bool:
        if not u:
            return False
        try:
            return (urlsplit(u).netloc or "").lower() == host
        except ValueError:
            return False

    n_json = len(lc.get("traffic_json_api_candidates") or [])
    n_inline = len(lc.get("inline_js_data_candidates") or [])
    n_hyd = len(lc.get("hydration_list_candidates") or [])
    n_feed = len(digest.get("feed_candidates") or [])
    n_html_same = sum(
        1 for p in (lc.get("html_repeating_patterns") or [])
        if _same_host(p.get("href_pattern_guess")) or _same_host(p.get("sample_url"))
    )
    fau_same = _same_host(lc.get("first_article_url"))
    clicked_url = ah.get("clicked_resolved_url")
    clicked_blocked = _is_antibot_redirect(clicked_url)
    clicked_same = _same_host(clicked_url) and not clicked_blocked

    if (n_json + n_inline + n_hyd + n_feed + n_html_same) >= 1 or fau_same or clicked_same:
        return True, ""

    detail = (f"traffic_json={n_json} inline_js={n_inline} hydration={n_hyd} feed={n_feed} "
              f"html_same_host={n_html_same} first_article_same_host={fau_same} clicked_same_host={clicked_same}"
              + (f" clicked_blocked_by_antibot={clicked_url}" if clicked_blocked else ""))
    return False, ("게시판 형식이 아닌 것 같다 — probe 가 같은 호스트로 가는 반복되는 글 링크/목록 API/피드를 하나도 못 찾았다. "
                   "게시판/공지 목록 페이지(글 행이 반복되는 페이지)의 URL 을 주세요. "
                   f"[신호: {detail}]")


def _save_state(slug: str, url: str, config_path: Path, post_ids: list[str],
                body_empty_at_baseline: Optional[bool] = None) -> Path:
    """state.json 작성. `body_empty_at_baseline`: 등록 직후 첫 글 1~3건 본문 fetch 결과 —
    None=확인 안 됨, True=모두 0자(비공개/등급제한 의심), False=하나라도 본문 있음. 봇이 이 플래그로
    `/preview`·`/watch` 응답에 "본문 추출 안 됨" 경고 표시 (`bot/site_ops.body_empty_at_baseline`)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{slug}.json"
    state: dict = {
        "slug": slug,
        "url": url,
        "config_path": str(config_path),
        "registered_at": _now_iso(),
        "last_poll_at": None,
        "last_status": "registered",
        "consecutive_breakage": 0,
        "n_baseline": len(post_ids),
        "seen_post_ids": post_ids,
    }
    if body_empty_at_baseline is not None:
        state["body_empty_at_baseline"] = bool(body_empty_at_baseline)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    # 등록과 동시에 FAILED·REJECTED 마커 / triage 큐 항목이 남아있으면 제거.
    # REJECTED 제거는 의도된 등록 (예: admin 이 풀고 register.py --config --force 로 재등록) 만 해당 —
    # 자동 경로는 어차피 봇 _is_registered 가 False 라서 워커가 register.py 를 안 부른다.
    for marker_suffix in (".FAILED.json", ".REJECTED.json"):
        mp = STATE_DIR / f"{slug}{marker_suffix}"
        if mp.exists():
            mp.unlink()
    _prune_triage_queue(slug)
    # 등록 성공 = "이 URL 의 host+path_prefix 패턴은 작동함" 증거. 같은 패턴 학습된 거부 룰이 있으면 자동 회수.
    # path_prefix 정확 매치만 — 다른 path 의 학습은 영향 X (예: google.com/search 룰이 있고 google.com/forms 등록해도 /search 룰 안 풀림).
    # 실패해도 등록 자체는 성공이니 swallow.
    try:
        removed = _unlearn_pattern_if_match(url)
        if removed:
            print(f"[register] learned_blacklist: 매칭 패턴 자동 회수 — id={removed} (등록 성공 = 패턴 작동 증거)")
    except Exception as e:  # noqa: BLE001
        print(f"[register] ⚠ learned_blacklist 자동 회수 실패 — 등록은 성공: {e}", file=sys.stderr)
    return p


# --------------------------------------------------------------------------- #
# learned_blacklist — 자동 학습 거부 패턴 (host + path_prefix 단위, 영구).
# 한 사용자의 거부 → 모두에게 적용. dev 박스에서 손-config 으로 작동시키면 자동 회수.
# 저장 자리: output/learned_blacklist.json (output/ 룰 — N100 작성 가능, git 추적 X).
# 봇 url_gate 가 mtime cache 로 자동 reload → 큐 처리 중 앞 작업 거부가 뒤 작업에 즉시 반영.
# --------------------------------------------------------------------------- #
LEARNED_PATH = ROOT / "output" / "learned_blacklist.json"


def _pattern_id(host: str, path_prefix: str) -> str:
    """host + path_prefix 의 안정적 12자 hash. 같은 (host, path_prefix) 는 같은 id."""
    h = hashlib.sha1(f"{host}|{path_prefix}".encode("utf-8")).hexdigest()
    return h[:12]


def _extract_url_pattern(url: str) -> Optional[tuple[str, str]]:
    """URL → (host_suffix, path_prefix). path_prefix 는 path 의 첫 segment (보수적 — host 의 다른 서비스 안 막음).
    path 가 '/' 또는 빈 문자열이면 path_prefix=''. host 없으면 None.

    예:
      https://www.google.com/search?q=대나무   → ('www.google.com', '/search')
      https://search.naver.com/search.naver  → ('search.naver.com', '/search.naver')
      https://example.com/                   → ('example.com', '')
      https://example.com                    → ('example.com', '')
    """
    try:
        p = urlsplit(url)
    except (ValueError, AttributeError):
        return None
    host = (p.hostname or "").strip().lower().rstrip(".")
    if not host:
        return None
    path = (p.path or "").strip()
    # path 의 첫 segment 만 — 보수적.
    seg = ""
    if path and path != "/":
        parts = [s for s in path.split("/") if s]
        if parts:
            seg = "/" + parts[0]
    return (host, seg)


def _read_learned() -> dict:
    """learned_blacklist.json 읽기. 없거나 깨지면 빈 구조 반환."""
    try:
        data = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("patterns"), list):
            return data
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return {"version": 1, "patterns": []}


def _write_learned_atomic(data: dict) -> None:
    """temp file + os.replace 로 atomic write. 부분 쓰기로 인한 reader 깨짐 방지.
    같은 디렉토리 안에서 tmp 생성 (cross-device rename 회피)."""
    LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".learned_blacklist.", suffix=".json", dir=str(LEARNED_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, LEARNED_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _learn_pattern(url: str, reason: str, slug: Optional[str] = None) -> Optional[dict]:
    """URL 의 host + path_prefix 를 learned_blacklist 에 박음. 이미 있는 entry 면 count 증가 + last_* 갱신.
    돌려준 dict 은 박힌/갱신된 pattern entry. URL 이 invalid 면 None.

    부르는 자리:
      - `_save_rejected` 마지막에 자동 호출 (모든 REJECTED 마커는 패턴도 박음)
      - `bot/worker.py` 의 rc=3 처리 분기에서 `_save_rejected` 거치며 호출됨
    """
    extracted = _extract_url_pattern(url)
    if extracted is None:
        return None
    host, path_prefix = extracted
    pat_id = _pattern_id(host, path_prefix)
    now = _now_iso()
    data = _read_learned()
    patterns = data.setdefault("patterns", [])
    existing = None
    for p in patterns:
        if isinstance(p, dict) and p.get("id") == pat_id:
            existing = p
            break
    if existing is not None:
        existing["last_rejected_at"] = now
        existing["reject_count"] = int(existing.get("reject_count") or 0) + 1
        existing["last_reason"] = reason
        existing["last_url"] = url
        if slug:
            existing["last_slug"] = slug
        entry = existing
    else:
        entry = {
            "id": pat_id,
            "host_suffix": host,
            "path_prefix": path_prefix,
            "first_rejected_at": now,
            "last_rejected_at": now,
            "reject_count": 1,
            "last_reason": reason,
            "last_url": url,
            "last_slug": slug,
        }
        patterns.append(entry)
    data["version"] = 1
    _write_learned_atomic(data)
    return entry


def _unlearn_pattern_if_match(url: str) -> list[str]:
    """URL 의 host + path_prefix 매칭하는 learned entry 를 모두 제거.
    `_save_state` (등록 성공) 가 호출 — "이 URL 이 작동한다 = 같은 패턴은 거부 룰 풀어줌".
    돌려준 list 는 제거된 pattern id 들. 매칭 X 면 빈 list.
    """
    extracted = _extract_url_pattern(url)
    if extracted is None:
        return []
    host, path_prefix = extracted
    pat_id = _pattern_id(host, path_prefix)
    data = _read_learned()
    patterns = data.get("patterns") or []
    removed = [p["id"] for p in patterns if isinstance(p, dict) and p.get("id") == pat_id]
    if not removed:
        return []
    data["patterns"] = [p for p in patterns if not (isinstance(p, dict) and p.get("id") == pat_id)]
    data["version"] = 1
    _write_learned_atomic(data)
    return removed


def _list_learned() -> list[dict]:
    """learned_blacklist 의 patterns 리스트. 디버깅/admin 용."""
    return _read_learned().get("patterns") or []


def _clear_learned_by_id(pat_id: str) -> bool:
    """pattern id 로 learned entry 제거 (운영자 손-회수). 없었으면 False."""
    data = _read_learned()
    patterns = data.get("patterns") or []
    new = [p for p in patterns if not (isinstance(p, dict) and p.get("id") == pat_id)]
    if len(new) == len(patterns):
        return False
    data["patterns"] = new
    data["version"] = 1
    _write_learned_atomic(data)
    return True


def _save_rejected(slug: str, url: str, reason: str, note: Optional[str] = None) -> Path:
    """`.REJECTED.json` 마커. 봇 `is_rejected(slug)`=True 가 되어 `/preview`·`/watch` 가 자동경로
    안 타고 "이전에 거부됨" 메시지로 응답. `is_registered` 와 분리 — REJECTED 는 polling 대상도 아님.
    같은 slug 의 `.FAILED.json` 마커가 있었으면 함께 제거 (REJECTED 가 우선).

    + 같은 URL 의 host+path_prefix 패턴을 `output/learned_blacklist.json` 에 자동 학습 (한 명의 거부 → 모두에게 적용).
    이 자동 학습은 atomic write — `output/` 가 없으면 만들어줌.

    `slug` 는 `[A-Za-z0-9._%-]+` 만 (path traversal 방어) — admin/스크립트 외 호출 없지만 보수적으로.
    """
    if not re.fullmatch(r"[A-Za-z0-9._%-]+", slug):
        raise ValueError(f"잘못된 slug 형식: {slug!r}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{slug}.REJECTED.json"
    p.write_text(json.dumps({
        "slug": slug,
        "url": url,
        "reason": reason,
        "note": note,
        "rejected_at": _now_iso(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    fp = STATE_DIR / f"{slug}.FAILED.json"
    if fp.exists():
        fp.unlink()
    _prune_triage_queue(slug)
    # 자동 패턴 학습 — host+path_prefix 단위. 실패해도 REJECTED 마커는 이미 박혔으니 swallow.
    try:
        _learn_pattern(url, reason, slug=slug)
    except Exception as e:  # noqa: BLE001
        print(f"[register] ⚠ learned_blacklist 학습 실패 — REJECTED 마커는 박힘: {e}", file=sys.stderr)
    return p


def _clear_rejected(slug: str) -> bool:
    """REJECTED 마커 제거 (실수 거부 복구용). 없었으면 False."""
    if not re.fullmatch(r"[A-Za-z0-9._%-]+", slug):
        raise ValueError(f"잘못된 slug 형식: {slug!r}")
    p = STATE_DIR / f"{slug}.REJECTED.json"
    if p.exists():
        p.unlink()
        return True
    return False


def _check_body_at_baseline(cfg: dict, posts: list, sample: int = 3) -> Optional[bool]:
    """등록 직후 첫 `sample` 건 본문 fetch. 결과:
      - True : 모두 0자 (비공개·등급제한·로그인 필요 게시판일 가능성 — 어댑터가 401/403 시 본문 비워 반환)
      - False: 하나라도 본문 있음 (정상)
      - None : 모두 예외 또는 posts 비어 — 판정 불가
    상위 호출에서 state.json `body_empty_at_baseline` 키로 저장 → 봇 응답에 경고 표시."""
    if not posts:
        return None
    from engine import make_adapter

    async def _run() -> list[int]:
        chars: list[int] = []
        async with make_adapter(cfg) as a:
            for p in posts[:sample]:
                try:
                    f = await a.fetch_article(p)
                    chars.append(len(f.content_html or ""))
                except Exception:  # noqa: BLE001  진단용 — 예외는 unknown 으로 버림
                    pass
        return chars

    try:
        chars = asyncio.run(_run())
    except Exception:  # noqa: BLE001
        return None
    if not chars:
        return None
    return all(c == 0 for c in chars)


def _prune_triage_queue(slug: str) -> None:
    """봇이 쌓는 output/triage_queue.jsonl 에서 이 slug 항목 제거 (등록되면 더 이상 triage 대상 아님)."""
    q = ROOT / "output" / "triage_queue.jsonl"
    if not q.exists():
        return
    try:
        kept: list[str] = []
        for line in q.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if rec.get("slug") != slug:
                kept.append(line)
        if kept:
            q.write_text("\n".join(kept) + "\n", encoding="utf-8")
        else:
            q.unlink()
    except OSError:
        pass


def _save_failed(slug: str, url: str, reason: str, last_config, last_feedback: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{slug}.FAILED.json"
    p.write_text(json.dumps({
        "slug": slug, "url": url, "failed_at": _now_iso(),
        "reason": reason, "last_config": last_config, "last_feedback": last_feedback,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _attempt_logger(i, cfg, rep, ok, msg):
    print(f"  시도 {i}: {'PASS' if ok else 'FAIL'} — {msg}")


def _list_sites(csv_path: Optional[str]) -> int:
    """등록 사이트 현황 = output/poll_state/<slug>.json (사이트당 1파일) + 구독 수(bot.sqlite3).
    레지스트리는 여기지 문서가 아님. --csv 면 그 경로(기본 output/registered_sites.csv)에도 씀."""
    sub_count: dict[str, int] = {}
    try:
        from bot import db as _db  # noqa: PLC0415
        conn = _db.connect()
        for r in conn.execute("SELECT slug, COUNT(*) FROM subscriptions GROUP BY slug").fetchall():
            sub_count[r[0]] = r[1]
        conn.close()
    except Exception:  # noqa: BLE001  bot.sqlite3 없으면 그냥 구독 0
        pass
    rows: list[dict] = []
    if STATE_DIR.exists():
        for p in sorted(STATE_DIR.glob("*.json")):
            failed = p.name.endswith(".FAILED.json")
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            slug = st.get("slug") or (p.name[:-len(".FAILED.json")] if failed else p.stem)
            cfgp = st.get("config_path") or ""
            strategy = ""
            if cfgp and Path(cfgp).exists():
                try:
                    strategy = json.loads(Path(cfgp).read_text(encoding="utf-8")).get("strategy", "")
                except Exception:  # noqa: BLE001
                    pass
            rows.append({
                "slug": slug, "url": st.get("url", ""), "strategy": strategy,
                "baseline": st.get("n_baseline", ""), "last_poll": st.get("last_poll_at") or "",
                "status": ("FAILED" if failed else (st.get("last_status") or "")),
                "breakage": st.get("consecutive_breakage", 0),
                "subscribers": sub_count.get(slug, 0), "config": cfgp,
            })
    if not rows:
        print("(등록된 사이트 없음 — output/poll_state/ 비어있음)")
        return 0
    rows.sort(key=lambda r: (r["status"] == "FAILED", r["slug"]))
    w_slug = max(len("slug"), max(len(r["slug"]) for r in rows))
    w_strat = max(len("strategy"), max(len(str(r["strategy"])) for r in rows))
    print(f"{'slug':<{w_slug}}  {'strategy':<{w_strat}}  {'base':>5}  {'subs':>4}  {'status':<10}  url")
    for r in rows:
        print(f"{r['slug']:<{w_slug}}  {str(r['strategy']):<{w_strat}}  {str(r['baseline']):>5}  "
              f"{str(r['subscribers']):>4}  {str(r['status']):<10}  {r['url']}")
    print(f"\n총 {len(rows)}건 (FAILED 포함). 레지스트리: {STATE_DIR}/  ·  구독: output/bot.sqlite3")
    if csv_path:
        import csv as _csv  # noqa: PLC0415
        cp = Path(csv_path)
        cp.parent.mkdir(parents=True, exist_ok=True)
        with cp.open("w", newline="", encoding="utf-8") as f:
            wr = _csv.DictWriter(f, fieldnames=["slug", "url", "strategy", "baseline", "last_poll",
                                                "status", "breakage", "subscribers", "config"])
            wr.writeheader()
            for r in rows:
                wr.writerow(r)
        print(f"→ CSV: {cp}")
    return 0


async def _generate(digest: dict, *, max_attempts: int, model):
    return await generate_config_validated(
        digest, model=model, max_attempts=max_attempts, fetch_articles=1, on_attempt=_attempt_logger,
    )


def _gen(digest: dict, *, max_attempts: int, model):
    """동기 래퍼 (asyncio.run)."""
    return asyncio.run(_generate(digest, max_attempts=max_attempts, model=model))


def _article_url_score(u: Optional[str], host: str) -> int:
    if not u or not u.startswith("http"):
        return -1
    sp = urlsplit(u)
    s = 0
    if host and sp.netloc == host:
        s += 4
    if re.search(r"\d{3,}", (sp.path or "") + "?" + (sp.query or "")):
        s += 2
    if re.search(r"(view|detail|article|notice|read|thread|post|bbs|board)", (sp.path or "").lower()):
        s += 1
    return s


def _best_article_url(digest: dict, last_fb: str) -> Optional[str]:
    """글페이지 re-probe 에 쓸 *진짜 글* URL 을 고른다. 후보:
    (1) 직전 attempt 가 실제로 추출한 글 URL (검증 피드백 텍스트의 url='...'), (2) digest 의 article_sample.url /
    list_candidates.first_article_url / html_repeating_patterns[].sample_url. — 목록과 같은 호스트 + 글ID 같은 숫자 있는 걸 우선
    (probe 가 헤더의 myinfo/login 링크를 first_article_url 로 잘못 집는 경우를 회피)."""
    host = urlsplit(digest.get("url") or "").netloc
    cands: list[str] = list(re.findall(r"url=['\"](https?://[^'\"]+)['\"]", last_fb or ""))
    lc = digest.get("list_candidates") or {}
    a = (digest.get("article_sample") or {}).get("url")
    if a:
        cands.append(a)
    if lc.get("first_article_url"):
        cands.append(lc["first_article_url"])
    for c in (lc.get("html_repeating_patterns") or []):
        if c.get("sample_url"):
            cands.append(c["sample_url"])
    cands = [u for u in cands if u and u.startswith("http")]
    if not cands:
        return None
    return max(cands, key=lambda u: _article_url_score(u, host))


def _set_first_article_url(slug: str, article_url: str) -> None:
    """list_candidates.json 의 first_article_url 을 덮어쓴다 (digest 의 article_sample.url 이 여기서 옴).
    probe 가 사이드바 메뉴 링크 등을 '첫 글'로 잘못 집은 걸 사용자가 준 진짜 글 URL 로 교정할 때."""
    p = output_dir(slug) / "list_candidates.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["first_article_url"] = article_url
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_ARTICLE_HINT_PREFIX = "사용자가 실제 글(본문) 페이지 URL 을 직접 지정했다"


def _article_hint_text(article_url: str, n_api: int) -> str:
    """--article-url 로 글페이지를 미리 re-probe 한 뒤 생성기에 주는 지침(첫 시도부터). 사용자가 *직접 지정한* URL 이라
    "이게 글 페이지다" 는 신뢰하되, 본문 API 후보가 진짜 본문인지는 확인하라고 한다(광고 SDK 가 후보로 새는 수 있음)."""
    api_line = (f"이 글페이지는 이미 render+HAR 로 re-probe 됐다 — article_sample.api_candidates 에 본문 JSON API 후보 {n_api}건이 있다. "
                "그중 *진짜 본문을 주는* 후보(url_id_match=true·body_looks_html=true)를 골라 article.url_template=그 후보 url(글 ID 숫자를 {post_id} 로 치환), "
                "article.fetch_kind=\"json\", article.content=[{from:\"json\", path:<그 후보의 body_field_path 그대로>}], 필요하면 그 후보 request_headers 의 X-Requested-With/Referer 를 config 최상위 headers 에 추가하라. "
                "(body_field_path 가 ['ads',...] 류이거나 url 이 ad/banner/sdk/collect/gtm 류면 광고 — 무시하고, 그러면 아래 article_sample.html 의 본문 컨테이너 selector 로.) "
                if n_api else
                "본문 JSON API 후보는 못 찾았다 — article.url_template 은 이 글 URL 의 패턴(글 ID 숫자→{post_id})으로 잡고, article.content 는 article_sample.html(이미 렌더된 DOM)에서 본문 컨테이너 selector 를 찾아 잡아라(필요하면 strategy=\"playwright_html\" + article.wait_selector). ")
    return (f"{_ARTICLE_HINT_PREFIX}: {article_url} — probe 가 자동으로 집은 '첫 글'은 무시하라(메뉴/사이드바 링크였을 수 있음). 이 URL 이 글 본문 페이지다(article_sample.html 이 그 페이지). "
            f"{api_line}"
            "또한 list 쪽: 이 글 URL 에 박힌 글 ID 가 목록 행의 어디(href/data-* 속성/JSON 필드)에 나오는지 list_html 에서 보고 list.fields.post_id 와 list.fields.url 을 그에 맞춰 잡아라.")


def _reprobe_article(slug: str, article_url: str) -> int:
    """글 본문 페이지를 Playwright(+HAR)로 다시 받아 → article.html(렌더 DOM, digest 가 자동으로 더 큰 걸 씀) +
    article_candidates.json(본문 JSON API 후보) 갱신. 발견한 본문 API 후보 개수 반환."""
    out_dir = output_dir(slug)
    try:
        from probe.fetch_headless import fetch_with_capture, is_available
        from probe.extract import traffic_article_body_candidates
    except Exception as e:  # noqa: BLE001
        print(f"[register]   글페이지 re-probe 모듈 import 실패: {e!r}")
        (out_dir / "article_candidates.json").write_text("[]", encoding="utf-8")
        return 0
    if not is_available():
        print("[register]   playwright 미설치 — 글페이지 render+HAR re-probe 불가 (FAILED 로 떨어질 수 있음)")
        (out_dir / "article_candidates.json").write_text("[]", encoding="utf-8")
        return 0
    r = fetch_with_capture(url=article_url, out_dir=out_dir, target="article", headless=True)
    print(f"[register]   article re-probe: status={r.status} {r.classification.value}  body={r.body_path}")
    har = out_dir / "traffic.article.har"
    if not har.exists():
        har = out_dir / "traffic.har"
    cands = traffic_article_body_candidates(har, article_url) if har.exists() else []

    # probe Phase 9b 가 만든 클릭 진입 HAR(traffic.article_click.har)이 있으면 거기서도 본문 API 후보를 캐서 합친다 —
    # 직접 GET 으론 다른 데로 튕기는 클라이언트 라우트나, 본문 API 가 *클릭 후에야* 호출되는 SPA 는 traffic.article.har 엔 안 잡힌다.
    # 이미 디스크에 있는 파일을 한 번 더 읽는 것뿐 — 새 브라우저/네트워크 비용 없음.
    click_har = out_dir / "traffic.article_click.har"
    if click_har.exists():
        click_article_url = article_url
        try:
            cm = json.loads((out_dir / "article_click.json").read_text(encoding="utf-8"))
            if isinstance(cm, dict) and cm.get("resolved_url"):
                click_article_url = cm["resolved_url"]      # 클릭 후 최종 URL — url_id_match 점수가 정확해짐
        except (json.JSONDecodeError, OSError):
            pass
        click_cands = traffic_article_body_candidates(click_har, click_article_url)
        seen = {c.get("url") for c in cands}
        added = [c for c in click_cands if c.get("url") not in seen]
        if added:
            print(f"[register]   + traffic.article_click.har 에서 본문 API 후보 {len(added)}건 추가")
            cands = (cands + added)[:8]

    # contract 검증 — 실패해도 _reprobe_article 흐름 중단 X (WARN 후 계속)
    try:
        from probe._contract import validate_payload as _vp, ContractError as _CE
        _vp("article_candidates.json", cands, allow_extra=False)
    except _CE as e:
        print(f"[register]   ⚠ article_candidates.json contract 위반: {e}")
    except Exception:  # noqa: BLE001
        pass
    (out_dir / "article_candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in cands[:3]:
        print(f"[register]     본문 API 후보: {c.get('method')} {c.get('url')}  body_field_path={c.get('body_field_path')} "
              f"len={c.get('body_len')} html={c.get('body_looks_html')} url_id_match={c.get('url_id_match')}")
    print(f"[register]   본문 JSON API 후보 {len(cands)}건")
    return len(cands)


def _has_json_api_candidates(digest: dict) -> bool:
    return bool(((digest.get("list_candidates") or {}).get("traffic_json_api_candidates")))


def _list_strategy_hint(digest: dict) -> Optional[str]:
    """probe 신호로 목록 전략 hint 를 만든다 (1회차부터 digest.escalation_hint 에 들어감).

    목록 페이지가 정적 GET(httpx) 으론 200 OK 가 안 나왔으면(static_ok_preset 없음 = headless 로만 됨 — JS 렌더거나 일시 차단)
    → JSON API 후보가 있으면 "httpx_json 검토하되 그 후보가 진짜 글 목록인지 확인" hint, 없으면 "playwright_html 검토" hint.
    정적 GET 이 되면 None — gemini 가 list_html / 후보들 보고 판단하게 둔다. *어느 경우든 "후보는 휴리스틱이라 광고/위젯이 섞일 수 있으니 list_html·HAR 와 대조해 확인" 을 강조한다.*"""
    if digest.get("static_ok_preset"):
        return None
    if _has_json_api_candidates(digest):
        return (
            "목록 페이지가 정적 GET(httpx)으론 200 OK 가 안 나왔다(headless 로만 됨 — JS 렌더 가능성). list_candidates.traffic_json_api_candidates 에 목록 JSON API 후보가 있으니: "
            "**먼저 그 후보(들)가 *진짜 글 목록*을 주는지 list_html·HAR 와 대조해 확인하라** — relevance 점수 순일 뿐이라 광고 SDK·트래커·다른 위젯이 섞이는 수 있다(응답이 {ads:[...]} 류거나 url 이 ad/banner/sdk/collect/gtm 류면 무시). "
            "진짜 글 목록 API 면 strategy=\"httpx_json\" 으로 (list.url_template / list_path / success_when / fields / pagination 은 그 후보 기준 — 시스템 프롬프트 'list 키' 설명 참고). "
            "후보가 다 광고/위젯이면 → list_candidates.html_repeating_patterns 중 진짜 글 목록인 걸 list_html 에서 확인해 strategy=\"playwright_html\" + list.row_selector / list.wait_selector. 마땅한 게 없으면 억지로 만들지 말고 그렇게 적어라."
        )
    if (digest.get("list_candidates") or {}).get("html_repeating_patterns"):
        return (
            "목록 페이지가 정적 GET(httpx)으론 200 OK 가 안 나왔고(JS 렌더 가능성) 목록 JSON API 후보도 없다. "
            "list_candidates.html_repeating_patterns 중 *진짜 글 목록처럼 보이는 것*(child_count 가 크고 href_pattern_guess 가 글 상세 URL 패턴 — 네비 메뉴·푸터 링크·댓글·'관련글' 위젯 말고)을 **list_html 에서 직접 확인해** 고르고: strategy=\"playwright_html\" + list.row_selector / list.wait_selector 로 그 목록이 그려질 때까지 대기, fields 는 그 렌더된 행 기준. article.content 는 글 상세 HTML 의 본문 컨테이너 selector. "
            "마땅한 글 목록 후보가 없으면(반복 패턴이 다 메뉴/위젯) 억지로 selector 만들지 말고 그렇게 적어라(handwritten 어댑터 영역)."
        )
    return None


def _preflight(slug: str, url: Optional[str], digest: dict, *, no_escalate: bool) -> dict:
    """gemini 부르기 *전에* 한 번: 옛 escalation 의 정보 수집을 "N회 실패 후 escalate" 대신 "사전 준비"로.

      (a) probe 가 잡은 첫 글 페이지(_best_article_url)를 Playwright+HAR 로 re-probe → article_candidates.json(본문 JSON API 후보)
          + article.html(렌더 DOM) 갱신. build_user_prompt 가 이걸 '⚡ 글 본문 JSON API 후보' 블록으로 자동 첨부 → 본문 API config /
          strategy=playwright_html 로 유도. (글 본문이 정적 HTML 에 멀쩡히 있는 사이트면 후보 0건이지만, 렌더된 DOM 샘플은 더 깨끗함.)
      (b) probe 신호로 목록 전략 hint(_list_strategy_hint)를 digest.escalation_hint 에. + probe 가 잡은 첫 글 URL 의 글 ID 가
          목록 행 어디 있는지 보라는 list 필드 hint.

    --no-escalate / playwright 미설치 면 해당 단계 건너뜀. probe 가 잡은 '첫 글' URL 이 *없거나 신뢰도 낮으면*(같은 호스트도
    아님 — probe 가 외부 링크를 첫 글로 오인) re-probe 를 건너뛰고 "gemini 가 list_html 에서 직접 찾아라" hint 만 준다. 반환: (보강된) digest.
    """
    if no_escalate:
        return digest
    url = url or digest.get("url") or ""
    art = _best_article_url(digest, "")
    host = urlsplit(url).netloc or urlsplit(art or "").netloc  # 목록 URL 호스트를 모르면(--slug + diagnosis 에 url 없음 등) art 호스트를 그 기준으로
    # 같은 호스트 이상이어야 re-probe (점수: 같은 호스트 +4, 글ID 숫자 +2, view/detail 류 경로 +1).
    # 그것보다 낮으면 probe 가 외부/엉뚱한 링크를 첫 글로 집은 것 — re-probe 해봤자 잘못된 article.html 샘플로 gemini 만 오도함.
    art_ok = bool(art) and _article_url_score(art, host) >= 4
    if art_ok:
        print(f"[register] preflight: 첫 글 페이지를 render+HAR 로 re-probe → {art}")
        _set_first_article_url(slug, art)          # digest 의 article_sample.url 이 우리가 re-probe 한 URL 과 일치하도록(_best_article_url 이 first_article_url 과 다른 후보를 골랐을 수 있음)
        n_api = _reprobe_article(slug, art)        # playwright 없으면 article_candidates.json=[] 쓰고 0 반환(조용)
        # _reprobe_article 이 article.html(렌더 DOM) / article_candidates.json 을 갱신했을 수 있으니 digest 재구성.
        # (playwright 미설치라 아무것도 못 바꿨어도 결과는 동일 — 무해.)
        digest = build_digest(slug=slug, url=url)
        if n_api:
            print(f"[register]   → 본문 JSON API 후보 {n_api}건, 프롬프트에 ⚡ 블록으로 첨부됨 (단, gemini 가 진짜 본문인지 확인하게 함)")
    elif art:
        print(f"[register] preflight: probe 가 첫 글로 집은 게 다른 호스트({art}) — re-probe 건너뜀(probe 오인 가능성). gemini 가 list_html 에서 직접 찾게 둠.")
    else:
        print("[register] preflight: probe 가 첫 글 URL 을 못 찾음 — re-probe 건너뜀.")

    hints: list[str] = []
    lh = _list_strategy_hint(digest)
    if lh:
        hints.append(lh)
    if art_ok:
        hints.append(
            f"probe 가 '{art}' 를 '첫 글' 로 추정하고 그 페이지를 render+HAR 로 re-probe 했다 — article_sample.html / api_candidates / article_sample.url 이 그것. "
            "**이게 진짜 글 본문 페이지가 맞는지 article_sample.html 을 보고 먼저 판단하라** — 메뉴/카테고리/서브게시판 페이지였을 수 있다. "
            "맞으면: 이 글 URL 에 박힌 글 ID 숫자가 목록 행의 어디(href / data-* 속성 / JSON 필드)에 나오는지 list_html 에서 보고 list.fields.post_id·url 을 그에 맞춰라. "
            "아니면: list_html 의 글 목록 행에서 글 상세로 가는 href 패턴을 직접 보고 article.url_template / list.fields.url 을 잡아라(article_sample 은 부정확하니 본문 selector 는 fallback chain 2~3개로, 또는 register.py --article-url \"<진짜 글 URL>\" 로 재등록)."
        )
    elif art:
        hints.append(
            f"⚠ probe 가 '첫 글' 로 집은 게 이 사이트와 *다른 호스트*({art}) — 외부 링크를 글로 오인한 것이다. article_sample.html / article_sample.url / first_article_url 을 *글 페이지로 쓰지 마라*. "
            "list_html 의 글 목록 행에서 글 상세로 가는 href(또는 data-* / 인라인 JS) 패턴을 직접 보고 list.fields.url 과 (필요하면) article.url_template·list.fields.post_id 를 잡아라. 본문 selector 는 그렇게 잡은 글 URL 기준으로(확신 없으면 fallback chain 2~3개). "
            "확신 안 서면 멈추고 그렇게 적어라 — register.py --article-url \"<진짜 글 하나 URL>\" 로 글 URL 을 직접 주면 정확해진다."
        )
    else:
        hints.append(
            "probe 가 '첫 글' URL 을 못 찾았다(목록 행에 글 상세 링크가 안 보임 — href 가 javascript: 거나 인라인 JS 데이터거나) — article_sample 은 비어있거나 부정확하다. "
            "list_html / list_candidates.html_repeating_patterns / inline_js_data_candidates 를 보고 글 ID·글 URL 이 어디 있는지 찾아 list.fields.post_id·url 을 잡아라(샘플 article 이 없으니 article.content selector 는 글 상세를 직접 받아 정해야 할 수도). "
            "정적 CSS 만으론 안 될 것 같으면(javascript: 링크 + data-* 도 없음) 억지로 만들지 말고 handwritten 어댑터가 필요하다고 적어라."
        )
    if hints:
        digest["escalation_hint"] = "\n\n".join(hints)
    return digest


def _try_known_platform(url: str, slug: str, *, out: Optional[str], force: bool) -> Optional[int]:
    """url 이 알려진 플랫폼(engine.recognizers)이면 probe/Gemini 없이 바로 config 작성·등록.
    반환: 0=등록 성공 / None=인식 안 됨 · 잘못 인식(fetch_list 0건/예외) · 기존 config 존재(--force 없이) → 호출 측이 일반 파이프라인으로 폴백.
    (정책 검사 -- 로그인/차단 -- 는 안 함: 알려진 플랫폼은 공개 게시판이고, 비공개·등급제한이면 어댑터가 본문만 비워 반환하니 목록 등록은 그대로 됨.)
    slug 는 register.py 가 호출된 URL 기준(봇 _is_registered 가 그 slug 로 찾으므로) — config 의 _source_url 도 그 url 로 맞춤."""
    cfg = recognize_platform(url)
    if cfg is None:
        return None
    name = cfg.get("_recognized_platform", "?")
    out_path = Path(out) if out else (CONFIGS_DIR / f"{slug}.json")
    if out_path.exists() and not force:
        print(f"[register] 알려진 플랫폼({name})으로 보이지만 {out_path} 이미 존재 — 인식 경로 건너뜀(덮어쓰려면 --force, 또는 일반 파이프라인으로 진행).")
        return None
    cfg["_source_url"] = url  # 호출된 URL 로 통일 (slug 와 일치)
    from engine import validate_config, make_adapter
    try:
        validate_config(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"[register] 알려진 플랫폼({name}) config 스키마 검증 실패 — 일반 파이프라인으로 폴백: {e}")
        return None
    print(f"[register] 🔎 알려진 플랫폼 인식: {name} — probe/gemini 생략, 바로 등록 시도 "
          f"(strategy={cfg.get('strategy')}{', adapter=' + cfg['adapter'] if cfg.get('adapter') else ''})")

    async def _baseline():
        async with make_adapter(cfg) as a:
            return await a.fetch_list(page=1, page_size=30)
    try:
        posts = asyncio.run(_baseline())
    except Exception as e:  # noqa: BLE001
        print(f"[register] 알려진 플랫폼({name}) fetch_list 실패 — 잘못 인식한 듯, 일반 파이프라인으로 폴백: {e!r}")
        return None
    if not posts:
        print(f"[register] 알려진 플랫폼({name})으로 인식했지만 글 0건 — 잘못 인식한 듯, 일반 파이프라인으로 폴백.")
        return None

    # 목록 일관성 검증 — recognizer 가 사이드바/광고/추천 영역을 우연히 N건 잡았을 때 silent 통과 방지.
    # post_id 안정성/유니크/title 비어있지 않음/published_at ISO 만 검사 (본문은 _check_body_at_baseline 별도).
    # digest=None → probe 교차검증(층위2) skip, fetch_articles=0 → 본문 fetch skip.
    # existing_posts=posts → fetch_list 재호출 안 함 (rate-limit·중복 트래픽 회피).
    from generate.validate import validate_built_config
    try:
        rep = asyncio.run(validate_built_config(cfg, digest=None, fetch_articles=0,
                                                  existing_posts=posts))
    except Exception as e:  # noqa: BLE001
        print(f"[register] known({name}) 검증 중 예외 — 폴백: {type(e).__name__}: {e}")
        return None
    if not rep.ok:
        fails = "; ".join(f"{c.name}({c.detail})" for c in rep.hard_failures())
        print(f"[register] known({name}) 인식했지만 목록 검증 실패 — 폴백: {fails}")
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    post_ids = [str(pp.post_id) for pp in posts]
    body_empty = _check_body_at_baseline(cfg, posts)
    print("[PHASE] baseline", flush=True)
    sp = _save_state(slug, url, out_path, post_ids, body_empty_at_baseline=body_empty)
    print(f"[register] ✅ 등록 완료 (알려진 플랫폼: {name}) — baseline {len(post_ids)}건  config={out_path}  state={sp}")
    if body_empty is True:
        print(f"[register] ⚠️ 본문 추출 안 됨 (등급/로그인 필요 가능) — 알림은 제목·URL 만 옵니다.")
    for pp in posts[:3]:
        print(f"    {pp.post_id}  {pp.published_at}  {(pp.title or '')[:60]}")
    return 0


def main(argv) -> int:
    # parent process (bot worker) 가 env 로 trace_id 전달 → start_trace 가 같은 trace 안에서
    # inner spans 추가. CLI 단독 호출이면 새 root trace 생성 (kind="probe").
    with start_trace("probe", attrs={"cli_argv": " ".join(argv[:6])}):
        return _main_inner(argv)


def _main_inner(argv) -> int:
    p = argparse.ArgumentParser(description="사이트 등록 (URL → config + baseline). --list 로 등록 현황 조회.")
    p.add_argument("url", nargs="?", help="목록 URL")
    p.add_argument("--slug", help="이미 probe 한 slug (url 대신; 그땐 probe 안 돌림)")
    p.add_argument("--config", help="이미 작성된 config 파일을 그대로 등록(probe/gemini 생략 — 손으로 짠 config / handwritten strategy 용). fetch_list 로 baseline 만 잡음.")
    p.add_argument("--list", action="store_true", help="등록된 사이트 현황을 표로 출력하고 종료 (output/poll_state/ + bot.sqlite3 기준)")
    p.add_argument("--csv", nargs="?", const=str(ROOT / "output" / "registered_sites.csv"),
                   help="--list 와 함께: 사이트 목록을 CSV 로도 저장 (값 생략 시 output/registered_sites.csv)")
    p.add_argument("--out", help="config 저장 경로 (기본: configs/<slug>.json)")
    from bot.runtime_config import settings as _rt_settings
    p.add_argument("--max-attempts", type=int, default=_rt_settings.register.max_attempts,
                   help=f"gemini 생성+검증 시도 횟수 (한 라운드 안에서 검증 피드백 재시도). "
                        f"기본값은 config.toml [register].max_attempts (현재 {_rt_settings.register.max_attempts}).")
    p.add_argument("--reuse-probe", action="store_true", help="probe 산출물 있으면 재사용")
    p.add_argument("--full-probe", action="store_true", help="lite 대신 처음부터 full probe (외부 Jina/Crawl4AI·유료 서비스까지 — 보통 불필요, 느림)")
    p.add_argument("--no-escalate", action="store_true",
                   help="preflight(첫 글 페이지 render+HAR re-probe + probe 신호 기반 목록 전략 hint 주입) 생략 — raw lite digest 로만 생성 (디버깅용)")
    p.add_argument("--no-recognize", action="store_true",
                   help="알려진 플랫폼(engine.recognizers) 자동 인식을 끄고 probe→gemini 일반 파이프라인을 강제 (디버깅/검증용)")
    p.add_argument("--article-url", metavar="URL",
                   help="실제 글 본문 페이지 URL 힌트 (probe 의 '첫 글' 자동 탐지가 메뉴/사이드바 링크를 잘못 집는 사이트용). "
                        "이 URL 을 render+HAR 로 미리 re-probe 해서 본문 JSON API 후보·렌더 DOM 을 확보하고 digest 의 article_sample 을 그걸로 맞춘 뒤 생성한다.")
    p.add_argument("--model", help="Gemini 모델 (기본 GEMINI_MODEL env 또는 gemini-2.5-flash)")
    p.add_argument("--force", action="store_true", help="기존 config 가 있어도 덮어씀")
    p.add_argument("--unlearn", metavar="PATTERN_ID",
                   help="learned_blacklist 의 pattern entry 제거 ([a-f0-9]{1,12}). 다른 인자 무시. "
                        "REMOVED / NOT_FOUND 한 줄 print.")
    args = p.parse_args(argv)

    if args.unlearn:
        pid = args.unlearn.strip().lower()
        if not re.fullmatch(r"[a-f0-9]{1,12}", pid):
            print(f"[register --unlearn] invalid pattern_id: {args.unlearn!r}", file=sys.stderr)
            return 4
        ok = _clear_learned_by_id(pid)
        print("REMOVED" if ok else "NOT_FOUND")
        return 0 if ok else 1

    if args.list:
        return _list_sites(args.csv)

    if not args.url and not args.slug and not args.config:
        p.error("url / --slug / --config / --list 중 하나 필요")

    # --- --config 모드: 이미 작성된 config 를 그대로 등록 (probe/gemini 생략) ---
    if args.config:
        from engine import load_config, validate_config, make_adapter
        cfg_path = Path(args.config)
        cfg = load_config(cfg_path)
        validate_config(cfg)
        stem = cfg_path.stem
        print(f"[register --config] {cfg_path}  strategy={cfg.get('strategy')}  site={cfg.get('site')}  board={cfg.get('board')}")

        async def _baseline():
            async with make_adapter(cfg) as a:
                return await a.fetch_list(page=1, page_size=30)
        posts = asyncio.run(_baseline())
        post_ids = [str(p.post_id) for p in posts]
        url0 = cfg.get("_source_url") or ((cfg.get("list") or {}).get("url_template") or "").format(board=cfg.get("board", ""))
        body_empty = _check_body_at_baseline(cfg, posts)
        # _save_state 가 같은 slug 의 .FAILED.json 마커도 치워 줌 (안 그러면 봇 _is_registered 가 계속 False).
        sp = _save_state(stem, url0, cfg_path, post_ids, body_empty_at_baseline=body_empty)
        print(f"[register --config] ✅ 등록 완료 — baseline {len(post_ids)}건, state={sp}")
        if body_empty is True:
            print(f"[register --config] ⚠️ 본문 추출 안 됨 (등급/로그인 필요 가능) — 알림은 제목·URL 만 옵니다.")
        for p in posts[:3]:
            print(f"    {p.post_id}  {p.published_at}  {(p.title or '')[:60]}")
        return 0

    if args.slug:
        slug = args.slug
        url = None
    else:
        url = args.url
        slug = url_to_slug(url)
        # 알려진 플랫폼이면 probe/gemini 건너뛰고 바로 등록 (실패하면 일반 파이프라인으로 폴백)
        if not args.no_recognize:
            if (args.article_url or "").strip():
                print("[register] 알림: --article-url 은 알려진 플랫폼으로 인식되면 무시됩니다(probe 를 건너뛰므로). 인식 안 되면 아래 probe 경로에서 그대로 적용됨.")
            tr = current_trace()
            print("[PHASE] recognize", flush=True)
            with tr.span("known_platform_try", attrs={"slug": slug, "url": url}) as sp:
                rc = _try_known_platform(url, slug, out=args.out, force=args.force)
                sp.set_attr("matched", rc is not None)
            if rc is not None:
                return rc
        out_dir = output_dir(slug)
        if not (args.reuse_probe and out_dir.exists() and (out_dir / "diagnosis.json").exists()):
            _run_probe(url, lite=not args.full_probe)

    print("[PHASE] digest", flush=True)
    print(f"[register] digest 구성: slug={slug}")
    tr = current_trace()
    with tr.span("build_digest", attrs={"slug": slug}):
        digest = build_digest(slug=slug, url=url)
    url = url or digest.get("url") or ""

    ok_policy, msgs = _policy_check(digest, url)
    for m in msgs:
        print(f"[register] {m}")
    if not ok_policy:
        print("[register] ❌ 등록 거부 (위 사유).")
        return 2

    # board-shape 게이트 — gemini 부르기 전에 한 번 더. probe 가 같은 호스트로 가는 반복 글 링크/목록 API/피드를
    # 하나도 못 찾았으면 그냥 일반 페이지(랜딩/문서/단일 글) — gemini 4회 돌릴 가치 없음 + triage 큐 오염 방지.
    ok_board, board_msg = _board_shape_check(digest, url)
    if not ok_board:
        print(f"[register] {board_msg}")
        print("[register] ❌ 등록 거부 — 게시판 형식 아님.")
        return 3

    # preflight: gemini 부르기 전에 정보 수집을 끝낸다 (옛 escalation 의 "N회 실패 후" 대신 "처음부터").
    #   --article-url 가 있으면 그 글 URL 로 first_article_url 교정 + re-probe + 강한 hint (probe 의 '첫 글' 휴리스틱이
    #   메뉴/사이드바 링크를 잘못 집는 사이트용); 없으면 _preflight 가 probe 가 잡은 첫 글로 re-probe + probe 신호 hint.
    article_url_hint = (args.article_url or "").strip() or None
    if article_url_hint and not article_url_hint.startswith(("http://", "https://")):
        print(f"[register] ⚠ --article-url 은 http(s):// URL 이어야 함 — 무시: {article_url_hint!r}")
        article_url_hint = None
    print("[PHASE] preflight", flush=True)
    with current_trace().span("preflight",
                              attrs={"slug": slug,
                                     "article_url_hint": bool(article_url_hint),
                                     "no_escalate": bool(args.no_escalate)}):
        if article_url_hint:
            print(f"[register] --article-url 힌트: {article_url_hint} — first_article_url 교정 + 그 글페이지 render+HAR re-probe")
            _set_first_article_url(slug, article_url_hint)
            n_api = _reprobe_article(slug, article_url_hint)
            digest = build_digest(slug=slug, url=url)
            hint = _article_hint_text(article_url_hint, n_api)
            lh = _list_strategy_hint(digest)        # 목록이 JS-gated 면 httpx_json/playwright_html 전환 hint 도 함께
            digest["escalation_hint"] = (hint + "\n\n" + lh) if lh else hint
        else:
            digest = _preflight(slug, url, digest, no_escalate=args.no_escalate)

    out_path = Path(args.out) if args.out else (CONFIGS_DIR / f"{slug}.json")
    if out_path.exists() and not args.force:
        print(f"[register] 주의: {out_path} 이미 존재 — 덮어쓰려면 --force. 새 결과는 {out_path}.new 로 저장.")
        out_path = out_path.with_suffix(out_path.suffix + ".new")

    # 실제 호출은 client_for("config_generate"/"config_retry") → routing.json 거침.
    # default_model() 은 routing 무시하고 GEMINI_MODEL env / hard-coded fallback 만 봐서 라벨 거짓말 — routing 거친 effective model 표시.
    _eff_model_init = args.model or _resolve_route("config_generate").model
    _eff_model_retry = args.model or _resolve_route("config_retry").model
    if _eff_model_init == _eff_model_retry:
        _model_label = _eff_model_init
    else:
        _model_label = f"{_eff_model_init} → {_eff_model_retry}"
    print(f"[PHASE] generate max={args.max_attempts}", flush=True)
    print(f"[register] gemini 생성+검증 (모델={_model_label}, 최대 {args.max_attempts}회):")
    gem_span_cm = current_trace().span("gemini_gen_validate",
                                        attrs={"slug": slug,
                                               "model_attempt1": _eff_model_init,
                                               "model_retry": _eff_model_retry,
                                               "max_attempts": args.max_attempts})
    gem_span_cm.__enter__()
    _gem_closed = False
    try:
        cfg, rep = _gen(digest, max_attempts=args.max_attempts, model=args.model)
    except GenerationError as e:
        if args.no_escalate:
            _ctx = "--no-escalate: preflight(글페이지 re-probe + probe 신호 hint) 생략, raw lite digest 로 생성한 상태"
        elif digest.get("escalation_hint") or article_url_hint:
            _ctx = "preflight: 글페이지 HAR re-probe + probe 신호 hint 적용 상태"
        else:
            _ctx = "preflight 돌렸으나 글 페이지 후보 없음/추가 hint 없음 — 사실상 raw lite digest"
        fp = _save_failed(slug, url, f"gemini 생성+검증 {args.max_attempts}회 실패 ({_ctx})",
                          getattr(e, "last_config", None), getattr(e, "last_feedback", str(e)))
        print(f"\n[register] ❌ 자동 처리 불가. → {fp}")
        print("  → docs/config 자동생성 실패 케이스.md 에서 .FAILED.json 의 last_feedback([FAIL] <체크명>) 로 케이스 판별 → 보통 손작성 config(register.py --config)로 해결, 안 되면 손어댑터(docs/사이트 어댑터 추가 가이드.md).")
        print("  (probe 가 '첫 글'을 잘못 집은 게 의심되면: register.py \"<목록URL>\" --article-url \"<실제 글 하나 URL>\" 로 재시도.)")
        print(f"  마지막 실패 사유:\n{getattr(e, 'last_feedback', e)}")
        try:
            gem_span_cm.__exit__(type(e), e, e.__traceback__)
            _gem_closed = True
        except Exception:  # noqa: BLE001
            _gem_closed = True
        return 1
    finally:
        # 아직 안 닫혔으면 — 정상 종료(exc=None) 또는 GenerationError 외의 예외 — 항상 닫는다.
        if not _gem_closed:
            exc_t, exc_v, exc_tb = sys.exc_info()
            try:
                gem_span_cm.__exit__(exc_t, exc_v, exc_tb)
            except Exception:  # noqa: BLE001
                pass

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 일반 파이프라인은 validate 단계에서 이미 fetch_article 시도 — rep.article_bodies 가 결과.
    # 모두 0 자면 body_empty True (validate 가 "전부 접근제한" soft-OK 로 통과시킨 케이스).
    if rep.article_bodies:
        bvals = list(rep.article_bodies.values())
        body_empty = all(v == 0 for v in bvals) if bvals else None
    else:
        body_empty = None
    print("[PHASE] baseline", flush=True)
    state_path = _save_state(slug, url, out_path, rep.all_post_ids, body_empty_at_baseline=body_empty)

    print(f"\n[register] ✅ 등록 완료")
    print(f"  config: {out_path}  (strategy={cfg.get('strategy')}, site={cfg.get('site')}, board={cfg.get('board')})")
    print(f"  state : {state_path}  (baseline {len(rep.all_post_ids)}건 — 이 글들은 '새 글' 아님)")
    if body_empty is True:
        print(f"  ⚠️ 본문 추출 안 됨 (등급/로그인 필요 가능) — 알림은 제목·URL 만 옵니다.")
    if rep.soft_failures():
        print(f"  경고: " + "; ".join(f"{c.name}({c.detail})" for c in rep.soft_failures()))
    for sp in rep.sample_posts[:3]:
        print(f"    {sp.get('post_id')}  {sp.get('published_at')}  {(sp.get('title') or '')[:60]}")
    print(f"  → 폴링: python scripts/poll.py   (M6 에서 구현)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
