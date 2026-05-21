"""jobs.status='failed' 안의 fail_kind/fail_subkind 분류 — `result_rc` + `result_tail` 에서 파생.

이 모듈이 fail 분류의 **single source of truth**. 새 fail 패턴 발견 시 절차:

  1. 해당 FailKind 의 `subkinds` 튜플에 Subkind 한 줄 추가 (또는 dynamic family 의 hint 갱신)
  2. `tests/fail_taxonomy/test_classify_fail.py` 에 fixture 케이스 한 줄 추가
  3. `python scripts/gen_fail_taxonomy_doc.py` 실행 → `docs/fail 분류.md` 자동 재생성
  4. pre-push hook 통과 — `tests/fail_taxonomy/` 의 completeness/drift 테스트가 누락 차단

DB 컬럼 추가 X — read time 파생 (ADR `docs/adr/0002-fail-classification-derived-at-read.md`).

분류 룰 요약:
- 1차 (rc + status 기반): pending(status) / running(status) / done(rc=0) / gen_fail(rc=1) /
  policy_reject(rc=2) / gate_reject(rc=3) / bug(rc=-1/-2/-3/-5/-99 또는 status='failed' AND rc=0)
- 2차 (tail regex/토큰): 각 FailKind 의 subkinds 순서대로 시도. dynamic Subkind (recognizer:* /
  [FAIL] passthrough) 는 catalog 미등록 이름도 surface — "새 패턴 감지" 시그널.

tail 은 `bot/site_ops.py` 가 last ~4000 chars 만 보존 — 잘려도 마지막 print 라인은 살아남는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional


# ============================================================================
# 자료구조
# ============================================================================

# Matcher protocol: (tail, rc) -> Optional[str].
# - None = 매치 안 됨.
# - str = 실제 subkind name (fixed Subkind 는 자기 name 반환, dynamic 은 capture 결과).
Matcher = Callable[[str, Optional[int]], Optional[str]]


@dataclass(frozen=True)
class Subkind:
    name: str       # canonical name 또는 pattern ("posts_nonempty", "recognizer:*").
    label_ko: str
    hint: str
    match: Matcher
    dynamic: bool = False  # True = name 이 pattern (catalog 외 실제 값 등장 가능).


def _always_false(_s: str, _rc: Optional[int], _t: str) -> bool:  # 기본 rc_extra
    return False


@dataclass(frozen=True)
class FailKind:
    name: str
    label_ko: str
    severity: str  # 'ok' | 'warn' | 'error' | ''
    rc: Optional[int]  # rc==이 값 → 매칭. None = rc_extra 로만 분기 (예: bug).
    # rc_extra: (status, rc, tail) -> bool. tail 인자 추가 (2026-05-20) — `url_dead` 가
    # 옛 rc=2 entries 의 tail (TARGET_NOT_FOUND / CERT_OR_DNS_BROKEN) 도 매칭하기 위해.
    rc_extra: Callable[[str, Optional[int], str], bool] = field(default=_always_false)
    rc_doc: str = ""  # doc gen 용 — 비어있으면 `rc={fk.rc}` 자동. 복합 조건은 명시.
    subkinds: tuple[Subkind, ...] = ()


# ============================================================================
# Matcher builders / dynamic matchers
# ============================================================================
_FAIL_CHECK_RE = re.compile(r"\[FAIL\]\s+([A-Za-z_][A-Za-z0-9_]*)")
_RECOGNIZER_RE = re.compile(r"recognize_reject\s+\(([^)]+)\)")


def _fail_check(name: str) -> Matcher:
    """`[FAIL] <name>` 라인이 tail 의 *마지막* [FAIL] match 와 일치하면 name 반환."""
    def m(tail: str, _rc: Optional[int]) -> Optional[str]:
        ms = _FAIL_CHECK_RE.findall(tail)
        return name if ms and ms[-1] == name else None
    return m


def _has_any(*tokens: str, name: str) -> Matcher:
    """tail 에 토큰 중 하나라도 있으면 name 반환."""
    def m(tail: str, _rc: Optional[int]) -> Optional[str]:
        return name if any(t in tail for t in tokens) else None
    return m


def _rc_eq(rc_val: int, name: str) -> Matcher:
    """rc == rc_val 이면 name 반환 (bug 의 rc→subkind 매핑)."""
    def m(_tail: str, rc: Optional[int]) -> Optional[str]:
        return name if rc == rc_val else None
    return m


def _fail_check_dynamic(tail: str, _rc: Optional[int]) -> Optional[str]:
    """gen_fail 의 fixed Subkind 가 다 미스했을 때 호출 — tail 의 마지막 [FAIL] capture 반환.

    catalog 미등록 fail_check 이름이 그대로 surface → "새 check 추가됨" 시그널.
    """
    ms = _FAIL_CHECK_RE.findall(tail)
    return ms[-1] if ms else None


def _recognizer_capture(tail: str, _rc: Optional[int]) -> Optional[str]:
    """`recognize_reject (<name>)` 가 있으면 `recognizer:<name>` 반환."""
    m = _RECOGNIZER_RE.search(tail)
    return f"recognizer:{m.group(1).strip()}" if m else None


def _race_subkind(_tail: str, rc: Optional[int]) -> Optional[str]:
    """status='failed' AND rc=0 race (`bot/worker.py` 의 `ok = (rc==0) and is_registered(slug)`)."""
    return "registered_but_no_state" if rc == 0 else None


def _bug_rc_extra(_s: str, rc: Optional[int], _t: str) -> bool:
    """bug FailKind 의 status/rc 매칭 — 음수 rc 또는 race."""
    return rc in (-1, -2, -3, -5, -99) or (_s == "failed" and rc == 0)


# `_policy_check` 가 verdict TARGET_NOT_FOUND / CERT_OR_DNS_BROKEN 일 때 박는 tail 토큰들.
# register.py 가 새로 emit 하는 rc=4 entries 도 위 토큰을 tail 에 박지만, rc=4 자체만으로도 매칭됨.
_URL_DEAD_TOKENS_TARGET = (
    "TARGET_NOT_FOUND",
    "URL 이 잘못됐거나 글이 삭제된",
)
_URL_DEAD_TOKENS_CERT = (
    "CERT_OR_DNS_BROKEN",
    "SSL 인증서/DNS 가 깨짐",
)
_URL_DEAD_TOKENS_SOFT_404 = (
    "SOFT_404",
    "not-found shell",
)


def _url_dead_rc_extra(_s: str, rc: Optional[int], tail: str) -> bool:
    """url_dead FailKind 매칭 — rc=4 또는 rc=2 + tail 에 url-dead verdict 토큰.

    rc=2 매칭은 *옛* policy_reject 데이터를 url_dead 로 re-classify (2026-05-20 split 이전 데이터).
    새 runs 는 register.py 가 직접 rc=4 박음. classify_fail 의 FAIL_CATALOG 순회 순서가
    url_dead → policy_reject 라 rc=2 + url-dead-tail 이 정확히 잡힘.
    """
    if rc == 4:
        return True
    if rc == 2 and tail:
        return any(t in tail for t in _URL_DEAD_TOKENS_TARGET + _URL_DEAD_TOKENS_CERT + _URL_DEAD_TOKENS_SOFT_404)
    return False


def _url_dead_target(_tail: str, _rc: Optional[int]) -> Optional[str]:
    return "target_not_found" if any(t in _tail for t in _URL_DEAD_TOKENS_TARGET) else None


def _url_dead_cert(_tail: str, _rc: Optional[int]) -> Optional[str]:
    return "cert_or_dns_broken" if any(t in _tail for t in _URL_DEAD_TOKENS_CERT) else None


def _url_dead_soft_404(_tail: str, _rc: Optional[int]) -> Optional[str]:
    return "soft_404" if any(t in _tail for t in _URL_DEAD_TOKENS_SOFT_404) else None


# ============================================================================
# Catalog — single source of truth
# ============================================================================
FAIL_CATALOG: tuple[FailKind, ...] = (
    FailKind(
        name="done",
        label_ko="성공",
        severity="ok",
        rc=0,
        subkinds=(),
    ),
    FailKind(
        name="gen_fail",
        label_ko="LLM 생성·검증 실패",
        severity="error",
        rc=1,
        subkinds=(
            Subkind("posts_nonempty", "추출 게시물 0건",
                    "validator 가 게시물 추출 결과를 0건으로 판정.",
                    _fail_check("posts_nonempty")),
            Subkind("article_body_len", "본문 너무 짧음",
                    "본문 selector 가 <100자 추출 — content selector 의심.",
                    _fail_check("article_body_len")),
            Subkind("published_at_iso", "날짜 파싱 실패",
                    "ISO8601 변환 실패 — date selector / format 의심.",
                    _fail_check("published_at_iso")),
            Subkind("post_id_stable_shape", "post_id 형태 불안정",
                    "post_id 가 매번 바뀌는 형태 — 새 게시물 감지 X.",
                    _fail_check("post_id_stable_shape")),
            Subkind("title_nonempty", "제목 비어 있음",
                    "title selector 가 빈 문자열 반환.",
                    _fail_check("title_nonempty")),
            # ▼ `[FAIL]` 라인 dynamic passthrough — fixed [FAIL] Subkind 다 미스했고 어쨌든 [FAIL] 라인이
            #   하나라도 있으면 그 마지막 이름 surface (catalog 미등록 check name 도). 토큰-기반 매처
            #   (`gemini_api`) 보다 *앞* 에 와야 구 동작 보존: 구 `classify_fail` 은 `[FAIL]` 가 있으면
            #   gemini 토큰 무시하고 그 이름 그대로 반환했음.
            Subkind("[FAIL]:<check>", "신규 fail_check 감지",
                    "catalog 미등록 [FAIL] check_name — Subkind 추가 권장.",
                    _fail_check_dynamic, dynamic=True),
            # ▼ 토큰-기반 fallback. `[FAIL]` 라인이 *없을* 때만 도달 (위 dynamic 이 잡지 못함).
            Subkind("gemini_api", "Gemini API 호출 실패",
                    "429 RESOURCE_EXHAUSTED / UNAVAILABLE / 호출·파싱 실패.",
                    _has_any("RESOURCE_EXHAUSTED", "UNAVAILABLE", "gemini 호출",
                             name="gemini_api")),
        ),
    ),
    # url_dead: 입력 URL 자체가 잘못 — 사이트 정책과 무관. 카탈로그 yaml URL 편집이 답 (코드 X).
    # 정책 거부와 분리 (2026-05-20) — 옛 rc=2 entries 중 tail 에 url-dead verdict 토큰 있는 것도
    # 자동 re-classify (rc=2 + token = url_dead, FAIL_CATALOG 순회 순서로 policy_reject 보다 먼저).
    FailKind(
        name="url_dead",
        label_ko="URL 잘못/죽음",
        severity="warn",
        rc=None,
        rc_extra=_url_dead_rc_extra,
        rc_doc="rc=4 (새 runs) 또는 rc=2 + tail 에 TARGET_NOT_FOUND / CERT_OR_DNS_BROKEN / SOFT_404 (옛 entries)",
        subkinds=(
            Subkind("target_not_found", "404 (URL 없음)",
                    "도메인 정상이지만 입력 URL 의 글/페이지가 없음 — 카탈로그 URL 편집 필요.",
                    _url_dead_target),
            Subkind("cert_or_dns_broken", "SSL/DNS 깨짐",
                    "도메인 자체 접근 단계 이전에 cert/DNS fail — 사이트가 사라졌거나 운영 오설정.",
                    _url_dead_cert),
            Subkind("soft_404", "soft-404 (200 not-found)",
                    "HTTP 200 이지만 not-found shell — URL 이 잘못됐거나 삭제됨.",
                    _url_dead_soft_404),
        ),
    ),
    FailKind(
        name="policy_reject",
        label_ko="사이트 정책 거부",
        severity="error",
        rc=2,
        subkinds=(
            Subkind("login_required", "로그인 필요",
                    "사이트가 로그인 요구 (네이버카페 비공개 등).",
                    _has_any("LOGIN_REQUIRED", name="login_required")),
            Subkind("blocked_bot", "봇 차단",
                    "User-Agent 또는 행동 기반 봇 감지.",
                    _has_any("BLOCKED_BOT", name="blocked_bot")),
            Subkind("blocked_ip", "IP 차단",
                    "IP/네트워크 단위 차단.",
                    _has_any("BLOCKED_IP", name="blocked_ip")),
            Subkind("blocked_geo", "지역 차단",
                    "지역(GEO) 단위 차단.",
                    _has_any("BLOCKED_GEO", name="blocked_geo")),
        ),
    ),
    # capability_blocked: anti-bot/captcha/cloudflare 차단 — 사이트를 *못 들어감* (능력 부족).
    # 2026-05-21 사용자 결정: policy_reject 에서 split. "captcha 못 들어가는 건 능력 부족이지 정책 아님".
    # register.py 가 rc=5 + FAILED.json (재시도 가능, learned_blacklist X) 박음. batch --failed 재집음 +
    # hand-config 가 stealth/storage_state 어댑터로 재도전 대상 (docs/크롤링 지침.md: captcha stealth 허용).
    FailKind(
        name="capability_blocked",
        label_ko="차단(능력 부족)",
        severity="warn",
        rc=5,
        subkinds=(
            Subkind("cloudflare", "Cloudflare 챌린지",
                    "Cloudflare anti-bot 챌린지 — stealth 어댑터로 재도전.",
                    _has_any("CLOUDFLARE", name="cloudflare")),
            Subkind("baseline_blocked", "정적·headless 진입 차단",
                    "static·headless 둘 다 차단 — anti-bot 의심. stealth 재도전.",
                    _has_any("BASELINE_BLOCKED", name="baseline_blocked")),
            # generic fallback — rc=5 인데 위 토큰 다 미스 (분류 보류 / BLOCKED_BOT/IP/GEO 등). 마지막.
            # blocked_bot/ip/geo 세분화는 policy_reject(legacy rc=2)에만 — rc=5 는 entry_blocked 로 흡수.
            Subkind("entry_blocked", "진입 차단(미분류)",
                    "anti-bot/captcha 추정 — verdict 미분류. stealth 재도전 후보.",
                    _has_any("능력 부족", "접근 실패", "BLOCKED", name="entry_blocked")),
        ),
    ),
    FailKind(
        name="gate_reject",
        label_ko="휴리스틱 게이트 거부",
        severity="warn",
        rc=3,
        subkinds=(
            # Dynamic — recognizer 이름은 인식기 추가마다 늘어남.
            Subkind("recognizer:*", "recognizer fast-path 거부",
                    "특정 사이트 인식기가 fast-path 로 거부 (예: wikipedia_article).",
                    _recognizer_capture, dynamic=True),
            Subkind("nav_only", "nav-only same-host",
                    "단일 article 인데 nav 만 같은 host 로 발산.",
                    _has_any("nav-only same-host", name="nav_only")),
            Subkind("meta_diverging", "meta 선언 + 발산",
                    "단일 article + meta 선언이지만 first_article 발산.",
                    _has_any("meta 선언 + 발산", name="meta_diverging")),
            Subkind("multi_host_hub", "multi-host hub root",
                    "외부 host 여러 곳으로 발산하는 hub root.",
                    _has_any("multi-host hub root", name="multi_host_hub")),
            Subkind("root_marketing_homepage", "root 마케팅 랜딩",
                    "메이저 미디어/플랫폼 root 도메인 — board 아님. 카테고리 URL 권장.",
                    _has_any("root 도메인 마케팅 랜딩", name="root_marketing_homepage")),
            Subkind("board_shape", "게시판 형식 아님",
                    "post 리스트 구조 인식 실패.",
                    _has_any("게시판 형식 아님", name="board_shape")),
        ),
    ),
    FailKind(
        name="bug",
        label_ko="시스템 결함",
        severity="error",
        rc=None,
        rc_extra=_bug_rc_extra,
        rc_doc="rc=-1/-2/-3/-5/-99 또는 status='failed' AND rc=0",
        subkinds=(
            Subkind("chromium_lock_timeout", "Chromium 락 대기 초과",
                    "동시 register 가 락 대기로 timeout — concurrency 제한 확인.",
                    _rc_eq(-1, "chromium_lock_timeout")),
            Subkind("subprocess_timeout", "register.py 600s timeout",
                    "subprocess 실행 시간 초과.",
                    _rc_eq(-2, "subprocess_timeout")),
            Subkind("subprocess_exception", "subprocess 예외",
                    "register.py 안 예외 (외부 runner 가 catch).",
                    _rc_eq(-3, "subprocess_exception")),
            Subkind("attempts_limit", "재시도 한도 초과",
                    "BUG 마커로 재시작 한도 도달.",
                    _rc_eq(-5, "attempts_limit")),
            Subkind("worker_exception", "worker 예외",
                    "worker.py 본체 예외 (KeyError 등).",
                    _rc_eq(-99, "worker_exception")),
            Subkind("registered_but_no_state", "subprocess 성공 / state.json 미작성",
                    "rc=0 인데 status='failed' — state 작성 race.",
                    _race_subkind),
        ),
    ),
)


# ============================================================================
# Pseudo-kinds (FAIL_CATALOG 외 — pending/running/unknown) severity
# ============================================================================
_PSEUDO_SEVERITY: dict[str, str] = {
    "pending": "",
    "running": "warn",
    "unknown": "error",
}


# ============================================================================
# Public helpers
# ============================================================================
# `bot/db.py` 의 jobs.status CHECK 값 — `/jobs` filter 가 SQL pushdown 가능한 base status 분기에 씀.
BASE_STATUS_VALUES: frozenset[str] = frozenset({"pending", "running", "done", "failed"})


def severity_for_kind(kind: Optional[str]) -> str:
    """fail_kind 또는 pseudo (pending/running/unknown) 의 css class severity 반환.

    catalog 미등록 값은 빈 문자열 — template 이 fallback 처리.
    """
    if not kind:
        return ""
    for fk in FAIL_CATALOG:
        if fk.name == kind:
            return fk.severity
    return _PSEUDO_SEVERITY.get(kind, "")


def fail_filter_options() -> list[str]:
    """dashboard filter dropdown 의 옵션 value 리스트 (전체 빈 옵션 제외).

    catalog 에서 derive: pending → running → (FAIL_CATALOG 순서대로). 새 FailKind 추가하면
    자동 dropdown 포함. `_PSEUDO_SEVERITY` 의 unknown 은 매처 미스 결과라 사용자가 직접 필터 X.
    """
    return ["pending", "running"] + [fk.name for fk in FAIL_CATALOG]


def label_for_kind(kind: Optional[str]) -> str:
    """fail_kind 의 한국어 라벨. catalog 미등록 값은 kind 자체 그대로."""
    if not kind:
        return ""
    for fk in FAIL_CATALOG:
        if fk.name == kind:
            return fk.label_ko
    return kind


def known_subkinds(fail_kind: str) -> list[str]:
    """주어진 fail_kind 의 *fixed* subkind name 리스트 (dynamic 제외) — completeness test 용."""
    for fk in FAIL_CATALOG:
        if fk.name == fail_kind:
            return [sk.name for sk in fk.subkinds if not sk.dynamic]
    return []


def all_known_subkinds() -> dict[str, list[str]]:
    """fail_kind → fixed subkind name 리스트 (dynamic 제외)."""
    return {fk.name: known_subkinds(fk.name) for fk in FAIL_CATALOG}


def pseudo_kinds() -> dict[str, str]:
    """catalog 외 표시 kind → severity (pending/running/unknown). doc gen 용."""
    return dict(_PSEUDO_SEVERITY)


def classify_fail(status: Optional[str], rc: Optional[int], tail: Optional[str]
                  ) -> tuple[str, Optional[str], Optional[str]]:
    """jobs row 의 (fail_kind, fail_subkind, reason_short) 계산.

    Returns:
        fail_kind: pending / running / done / gen_fail / policy_reject / gate_reject / bug /
            unknown 중 하나.
        fail_subkind: catalog 의 Subkind.name 또는 dynamic capture (e.g. "recognizer:foo").
            None = 매처 다 미스.
        reason_short: tail 의 마지막 의미있는 줄 (≤200 chars). 셀 hover/title 용. None 가능.
    """
    s = (status or "").lower()
    if s in ("pending", "running"):
        return (s, None, None)
    if s == "done":
        return ("done", None, None)
    # status != 'failed' AND rc == 0 = subprocess 성공 (대시보드에 done 처럼 보여줘도 안전).
    if s != "failed" and rc == 0:
        return ("done", None, None)

    reason = _last_meaningful_line(tail)
    t = tail or ""

    for fk in FAIL_CATALOG:
        if fk.name == "done":
            continue
        if fk.rc is not None:
            if rc != fk.rc:
                continue
        else:
            if not fk.rc_extra(s, rc, t):
                continue
        for sk in fk.subkinds:
            matched = sk.match(t, rc)
            if matched is not None:
                return (fk.name, matched, reason)
        return (fk.name, None, reason)

    return ("unknown", None, reason)


def _last_meaningful_line(tail: Optional[str]) -> Optional[str]:
    if not tail:
        return None
    for line in reversed(tail.splitlines()):
        s = line.strip()
        if s:
            return s[:200]
    return None
