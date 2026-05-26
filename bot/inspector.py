"""구독·등록 잡·config·state 통합 조회 + 자동 진단 (`bot/admin.py` 와 `scripts/inspect_subs.py` 가 공유).

목적: 다른 사용자의 /watch 가 이상하게 등록됐다는 신고(`/report`)를 받으면 그 사용자의 입력 URL,
파생된 slug, 실제 작성된 config, 폴링 state, 휴리스틱 진단을 한 번에 dump 한다. owner 가
Discord 에서(`/admin inspect`) 혹은 dev 박스에서(`scripts/inspect_subs.py`) 같은 데이터를 본다.

설계:
  - 순수 lib — discord 의존 없음(formatting 도 markdown 텍스트만). DB conn 은 호출자가 주입.
  - 두 경로(라이브 N100 vs dev 박스 snapshot)에서 다 돌도록 `InspectorPaths` 로 디렉토리 분리.
  - `fetch_sim` 만 async (adapter 가 playwright/httpx 등 비동기). 나머진 동기.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from bot import db

ROOT = Path(__file__).resolve().parent.parent
SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


@dataclass
class InspectorPaths:
    """라이브(N100) 와 snapshot(dev 박스) 양쪽에서 같은 함수를 돌리기 위한 경로 묶음."""
    db_path: Path
    configs_dir: Path
    state_dir: Path

    @classmethod
    def live(cls) -> "InspectorPaths":
        return cls(
            db_path=ROOT / "output" / "bot.sqlite3",
            configs_dir=ROOT / "configs",
            state_dir=ROOT / "output" / "poll_state",
        )

    @classmethod
    def snapshot(cls, base: Path) -> "InspectorPaths":
        """`scripts/inspect_subs.py pull` 가 떨군 dev 박스 snapshot 디렉토리. base/{bot.sqlite3, configs/, poll_state/}."""
        base = Path(base)
        return cls(
            db_path=base / "bot.sqlite3",
            configs_dir=base / "configs",
            state_dir=base / "poll_state",
        )


# --------------------------------------------------------------------------- #
# 데이터 수집
# --------------------------------------------------------------------------- #
def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None


def recent_jobs(conn: sqlite3.Connection, limit: int = 20, offset: int = 0,
                status: Optional[str] = None,
                kind: Optional[str] = "register") -> list[dict]:
    """최근 잡. 각 항목: id/slug/url/status/finished_at/via/requested_by(parsed) /sub_payload(parsed) +
    `fail_kind`/`fail_subkind`/`fail_reason_short` (`bot.fail_taxonomy.classify_fail` 파생).

    `kind` (ADR 0019 Phase 2): None = 모든 kind, 기본 'register' (옛 동작), 또는 'reprobe'/'poll_site'/
    'deliver_target' 지정. poll_site/deliver_target 은 register-orient classify_fail 이 적용 안 됨
    (fail_kind = base status).

    `status` 인자는 SQL pushdown — base status (pending/running/done/failed/rejected) 한정. fail_kind sub 필터링은
    호출자(`dashboard/app.py:jobs_list`)가 결과 dict 의 `fail_kind` 로 추가 필터.
    """
    from bot.fail_taxonomy import classify_fail
    out: list[dict] = []
    for r in db.recent_register_jobs(conn, limit=limit, offset=offset, status=status, kind=kind):
        d = dict(r)
        rb = d.get("requested_by")
        if rb:
            try:
                d["requested_by"] = json.loads(rb)
            except json.JSONDecodeError:
                pass
        sp = d.get("sub_payload")
        if sp:
            try:
                d["sub_payload"] = json.loads(sp)
            except json.JSONDecodeError:
                pass
        kind, sub, reason = classify_fail(d.get("status"), d.get("result_rc"), d.get("result_tail"))
        d["fail_kind"] = kind
        d["fail_subkind"] = sub
        d["fail_reason_short"] = reason
        out.append(d)
    return out


def _read_json(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _config_for(slug: str, paths: InspectorPaths) -> Optional[dict]:
    """state 의 config_path 우선, 없으면 configs/<slug>.json. snapshot 경로일 때 state 가 가리키는
    절대경로(N100)는 dev 박스에 없으니 stem 으로 다시 찾는다."""
    st = _read_json(paths.state_dir / f"{slug}.json")
    if st and st.get("config_path"):
        cp = Path(st["config_path"])
        if cp.exists():
            cfg = _read_json(cp)
            if cfg is not None:
                return cfg
        # snapshot: N100 절대경로는 못 찾으니 stem 으로 fallback
        local = paths.configs_dir / cp.name
        if local.exists():
            return _read_json(local)
    direct = paths.configs_dir / f"{slug}.json"
    return _read_json(direct) if direct.exists() else None


def _state_for(slug: str, paths: InspectorPaths) -> Optional[dict]:
    """라이브 state. .FAILED.json 도 함께 본다."""
    out = _read_json(paths.state_dir / f"{slug}.json")
    failed = _read_json(paths.state_dir / f"{slug}.FAILED.json")
    if out is None and failed is None:
        return None
    return {"ok": out, "failed": failed}


def _subscriptions_for(conn: sqlite3.Connection, *, user_id: Optional[str], slug: str) -> list[dict]:
    if user_id is None:
        rows = conn.execute("SELECT * FROM subscriptions WHERE slug=?", (slug,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM subscriptions WHERE slug=? AND user_id=?", (slug, user_id),
        ).fetchall()
    return [dict(r) for r in rows]


def _latest_register_job_for(conn: sqlite3.Connection, *, user_id: Optional[str], slug: str) -> Optional[dict]:
    """이 (user, slug) 의 가장 최근 register 잡. subscriptions.url 은 UPSERT 로 마지막 /watch URL 만 남으므로
    *원래 등록 시* URL 을 보려면 jobs 를 봐야 한다."""
    if user_id is None:
        row = conn.execute(
            "SELECT * FROM jobs WHERE kind='register' AND slug=? ORDER BY id DESC LIMIT 1", (slug,)
        ).fetchone()
    else:
        # json_extract 로 명확히 match — JSON1 (SQLite 3.38+, N100 Arch 의 3.45+ 에서 사용 가능).
        # 옛 LIKE 패턴은 username 등 다른 필드에 같은 숫자가 섞이면 잘못 매칭 가능.
        row = conn.execute(
            "SELECT * FROM jobs WHERE kind='register' AND slug=? "
            "AND json_extract(requested_by, '$.id')=? "
            "ORDER BY id DESC LIMIT 1",
            (slug, user_id),
        ).fetchone()
    d = _row_to_dict(row)
    if d and d.get("requested_by"):
        try:
            d["requested_by"] = json.loads(d["requested_by"])
        except json.JSONDecodeError:
            pass
    return d


# --------------------------------------------------------------------------- #
# 진단
# --------------------------------------------------------------------------- #
@dataclass
class DiagnoseFinding:
    severity: str   # 'error' | 'warn' | 'info'
    tag: str
    msg: str


@dataclass
class InspectResult:
    slug: str
    subscriptions: list[dict] = field(default_factory=list)
    latest_job: Optional[dict] = None
    report: Optional[dict] = None
    config: Optional[dict] = None
    state: Optional[dict] = None
    findings: list[DiagnoseFinding] = field(default_factory=list)
    fetch_sample: Optional[list[dict]] = None  # fetch_sim 호출했을 때만


def diagnose(conn: sqlite3.Connection, paths: InspectorPaths, *,
             slug: str, subscriptions: list[dict], latest_job: Optional[dict],
             config: Optional[dict], state: Optional[dict],
             fetch_sample: Optional[list[dict]] = None) -> list[DiagnoseFinding]:
    """slug 단위 휴리스틱 진단. arca-tab 같은 특정 버그 외에도 generic 한 깨짐 신호를 잡는다."""
    findings: list[DiagnoseFinding] = []

    # 1) FAILED 마커 — 자동 등록 자체가 실패
    if state and state.get("failed"):
        reason = (state["failed"] or {}).get("reason") or "(없음)"
        findings.append(DiagnoseFinding("error", "auto_register_failed",
                                        f"자동 등록 실패 마커가 있음 — reason: {reason!r}. configs/ 가 없거나 stale."))

    # config 못 찾음
    if config is None:
        findings.append(DiagnoseFinding("error", "config_missing",
                                        f"configs/{slug}.json 또는 state.config_path 가 가리키는 파일이 없음."))

    # 2) query_kwargs_mismatch — 등록 URL 에 query 가 있는데 config.kwargs 가 비어있거나 query 키와 무관해 보임
    job_url = (latest_job or {}).get("url") or ""
    sub_urls = list(dict.fromkeys((s.get("url") or "") for s in subscriptions))
    candidate_urls = [u for u in (sub_urls + [job_url]) if u]
    for u in candidate_urls:
        q = parse_qs(urlsplit(u).query, keep_blank_values=False)
        if not q:
            continue
        kwargs = ((config or {}).get("kwargs") or {})
        # 키가 정확히 일치하지 않더라도(예: query 'category' vs kwargs 'category') 키 이름 그대로 비교.
        # 둘 다 비어있지 않은데 교집합 0 이면 의심.
        if not kwargs:
            findings.append(DiagnoseFinding(
                "warn", "query_kwargs_mismatch",
                f"등록 URL 에 query={list(q)} 있는데 config.kwargs 가 비어있음 — 등록 시 query 가 무시됐을 수 있음. "
                f"(URL={u})"))
            break
        if not (set(q) & set(kwargs)):
            findings.append(DiagnoseFinding(
                "info", "query_kwargs_keys_disjoint",
                f"등록 URL query 키={list(q)} 와 config.kwargs 키={list(kwargs)} 가 한 개도 안 겹침 — "
                f"등록 시 query 가 다른 형태로 변환됐거나 무시됐을 수 있음. (URL={u})"))
            break

    # 3) breakage_signal — state 가 연속 깨짐 누적
    cb = ((state or {}).get("ok") or {}).get("consecutive_breakage")
    if isinstance(cb, int) and cb > 0:
        findings.append(DiagnoseFinding("error", "breakage_signal",
                                        f"consecutive_breakage={cb} — 폴링이 연속해서 깨짐 신호 감지."))

    # 3b) body_empty_drift — poll.py 가 K회 연속 모든 새 글 본문 0자 감지 시 state 에 박는 streak.
    ok_state = (state or {}).get("ok") or {}
    streak = ok_state.get("body_empty_streak")
    if isinstance(streak, int) and streak >= 3:
        first_at = ok_state.get("body_empty_drift_first_at") or "?"
        findings.append(DiagnoseFinding(
            "error", "body_empty_drift",
            f"최근 {streak}회 연속 폴링에서 새 글 본문이 전부 0자 (first_at={first_at}) — "
            f"등록 후 사이트가 등급제한/로그인월 추가됐을 가능성. 알림은 제목·URL 만 발송 중."))

    # 4) stale_poll — 마지막 폴링 24h 초과
    lp = ok_state.get("last_poll_at")
    if lp:
        try:
            t = datetime.fromisoformat(lp.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - t > timedelta(hours=24):
                findings.append(DiagnoseFinding(
                    "warn", "stale_poll", f"last_poll_at={lp} — 24h 넘게 폴링 안 됨(시간 스케줄 또는 N100 down)."))
        except (ValueError, AttributeError):
            pass

    # 5) empty_baseline — baseline 자체가 0
    nb = ((state or {}).get("ok") or {}).get("n_baseline")
    if isinstance(nb, int) and nb == 0:
        findings.append(DiagnoseFinding(
            "info", "empty_baseline",
            "baseline=0 — 등록 당시 글이 0건이었음. 새 글 감지엔 무관하지만 어댑터 selector 가 잘못 잡혔을 수도."))

    # 6) never_delivered — 구독 ≥7일이고 deliveries 0건
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for sub in subscriptions:
        try:
            created = datetime.fromisoformat((sub.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if created > cutoff:
            continue
        n = conn.execute(
            "SELECT COUNT(*) FROM deliveries WHERE slug=? AND target_id=?",
            (slug, sub.get("target_id")),
        ).fetchone()[0]
        if int(n) == 0:
            findings.append(DiagnoseFinding(
                "warn", "never_delivered",
                f"user={sub.get('user_id')} target={sub.get('target_id')} 구독 {sub.get('created_at')[:10]} 부터 "
                f"deliveries 0건 — 필터가 너무 빡세거나 폴링이 깨졌을 가능성."))

    # 7) fetch_sim — 호출자가 미리 돌려 결과를 주입한 경우만
    if fetch_sample is not None:
        if not fetch_sample:
            findings.append(DiagnoseFinding(
                "error", "fetch_sim_empty", "현재 config 로 fetch_list 돌렸더니 0건 — 어댑터/selector drift."))
        else:
            ids = [str(p.get("post_id")) for p in fetch_sample]
            if len(set(ids)) == 1 and len(ids) > 1:
                findings.append(DiagnoseFinding(
                    "error", "fetch_sim_same_id",
                    f"fetch_list 결과 {len(ids)}건이 모두 같은 post_id={ids[0]!r} — post_id 추출이 깨짐."))
            # 본문도 시도한 경우(body_chars 키 있음) — 시도 N건 *모두* 0자면 본문 추출 깨짐 신호.
            bcs = [p.get("body_chars") for p in fetch_sample if isinstance(p.get("body_chars"), int)]
            if bcs and all(b == 0 for b in bcs):
                findings.append(DiagnoseFinding(
                    "warn", "article_body_empty",
                    f"fetch_article {len(bcs)}건 모두 본문 0자 — 비공개·등급제한·로그인 필요 게시판일 수 있음 "
                    f"(어댑터가 401/403 시 본문 비워 반환)."))

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.tag))
    return findings


# --------------------------------------------------------------------------- #
# 통합 inspect (lookup → 모든 데이터 모음 → diagnose)
# --------------------------------------------------------------------------- #
def inspect(conn: sqlite3.Connection, paths: InspectorPaths, *,
            job_id: Optional[int] = None,
            user_id: Optional[str] = None,
            slug: Optional[str] = None,
            report_id: Optional[int] = None) -> Optional[InspectResult]:
    """네 가지 lookup 키 중 하나로 시작. 가장 풍부한 것부터: report_id → job_id → (user_id, slug) → slug.
    못 찾으면 None. fetch_sim 결과는 호출자가 별도로 돌려서 `update_with_fetch_sample` 로 넣는다."""
    report: Optional[dict] = None
    resolved_slug: Optional[str] = slug
    resolved_user: Optional[str] = user_id

    if report_id is not None:
        r = db.get_report(conn, report_id)
        if r is None:
            return None
        report = dict(r)
        resolved_slug = report["slug"]
        resolved_user = report["user_id"]

    if job_id is not None:
        j = db.get_job(conn, job_id)
        if j is None and resolved_slug is None:
            return None
        if j is not None:
            jd = dict(j)
            try:
                rb = json.loads(jd.get("requested_by") or "{}")
                if not resolved_user:
                    resolved_user = rb.get("id")
            except json.JSONDecodeError:
                pass
            if not resolved_slug:
                resolved_slug = jd["slug"]

    if not resolved_slug:
        return None

    subscriptions = _subscriptions_for(conn, user_id=resolved_user, slug=resolved_slug)
    latest_job = _latest_register_job_for(conn, user_id=resolved_user, slug=resolved_slug)
    cfg = _config_for(resolved_slug, paths)
    st = _state_for(resolved_slug, paths)
    findings = diagnose(conn, paths, slug=resolved_slug, subscriptions=subscriptions,
                        latest_job=latest_job, config=cfg, state=st)
    return InspectResult(slug=resolved_slug, subscriptions=subscriptions, latest_job=latest_job,
                         report=report, config=cfg, state=st, findings=findings)


def update_with_fetch_sample(result: InspectResult, conn: sqlite3.Connection,
                             paths: InspectorPaths, sample: list[dict]) -> None:
    """fetch_sim 결과를 반영해 진단을 다시 돌린다. sample 은 [{post_id, title, url}, ...]."""
    result.fetch_sample = sample
    result.findings = diagnose(conn, paths, slug=result.slug, subscriptions=result.subscriptions,
                               latest_job=result.latest_job, config=result.config,
                               state=result.state, fetch_sample=sample)


# --------------------------------------------------------------------------- #
# fetch_sim — 현 config 로 어댑터 돌려 top N 끌어옴
# --------------------------------------------------------------------------- #
async def verify_recognize(url: str, n: int = 10) -> dict:
    """원본 URL → engine.recognizers.recognize() → in-memory cfg 로 fetch_list 돌려 결과 반환.

    *dev 박스 검증용*. 디스크에 configs/ · poll_state/ 안 만든다 — register.py 호출과 달리 부수 효과 0.
    recognizer 수정 후 "지금 그 URL 이 어떤 config 로 매칭되고 어떤 글이 잡히나" 를 한 번에 본다.

    반환 dict:
      - `url`            : 입력 URL
      - `slug`           : url_to_slug 결과
      - `recognized`     : recognize() 의 cfg dict (None 이면 fast-path 거부)
      - `posts`          : fetch_list 결과 [{post_id,title,url,category,published_at}, …] (recognized 가 None 이면 [])
      - `error`          : 어댑터 예외 메시지 (정상이면 None)
    """
    from engine.recognizers import recognize
    from probe.paths import url_to_slug
    out: dict = {"url": url, "slug": url_to_slug(url), "recognized": None, "posts": [], "error": None}
    cfg = recognize(url)
    out["recognized"] = cfg
    if cfg is None:
        return out
    # n<=0 면 fetch_list 호출 자체를 스킵 — playwright/chromium spin-up 비용 회피
    # (recognizer-only 검증 / 테스트 fixture 용도).
    if n <= 0:
        return out
    try:
        from engine import make_adapter
        async with make_adapter(cfg) as a:
            posts = await a.fetch_list(page=1, page_size=n)
        for p in posts[:n]:
            try:
                d = p.to_dict()
            except Exception:  # noqa: BLE001
                d = {"post_id": getattr(p, "post_id", None), "title": getattr(p, "title", None),
                     "url": getattr(p, "url", None), "category": getattr(p, "category", None),
                     "published_at": getattr(p, "published_at", None)}
            out["posts"].append({k: d.get(k) for k in
                                 ("post_id", "title", "url", "category", "published_at")})
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def format_verify_result(d: dict) -> str:
    """`verify_recognize` 결과를 사람이 보는 텍스트로. recognizer 가 잡은 kwargs·strategy 와 글 목록 동시 노출."""
    parts: list[str] = []
    parts.append(f"## verify: `{d['url']}`")
    parts.append(f"- 파생 slug: `{d['slug']}`")
    cfg = d.get("recognized")
    if cfg is None:
        parts.append("- recognizer: **매칭 안 됨** (fast-path 거부 — probe/gemini 경로로 폴백됨)\n"
                     "  recognizer 가 None 반환했을 때 의도된 동작인지 직접 검증 필요.")
        return "\n".join(parts)
    parts.append(f"- recognizer: `{cfg.get('_recognized_platform') or '?'}`")
    parts.append(f"- strategy: `{cfg.get('strategy')}` · adapter: `{cfg.get('adapter') or '-'}` · "
                 f"site: `{cfg.get('site')}` · board: `{cfg.get('board')}`")
    kw = cfg.get("kwargs") or {}
    if kw:
        parts.append(f"- kwargs: `{json.dumps(kw, ensure_ascii=False)}`")
    if d.get("error"):
        parts.append(f"- ⚠️ fetch_list 예외: `{d['error']}`")
    posts = d.get("posts") or []
    if not posts:
        parts.append("- fetch_list 결과: **0 건** (어댑터 실패 또는 selector drift / 빈 게시판)")
    else:
        parts.append(f"- fetch_list 결과: **{len(posts)} 건**")
        lines = []
        for p in posts:
            cat = p.get("category") or "-"
            t = (p.get("title") or "")[:70]
            lines.append(f"  - `{p.get('post_id')}` · [{cat}] · {t}")
        parts.append("\n".join(lines))
        # 카테고리 분포 — 탭 fix 검증에 핵심
        cats = [p.get("category") for p in posts]
        from collections import Counter
        dist = Counter(cats)
        parts.append(f"- 카테고리 분포: " + ", ".join(f"`{k or '-'}`={v}" for k, v in dist.most_common()))
    return "\n".join(parts)


async def fetch_sim(paths: InspectorPaths, slug: str, n: int = 5,
                    body_sample: int = 3) -> Optional[list[dict]]:
    """현재 config 로 adapter.fetch_list 를 돌려 상위 N 개 post 의 {post_id, title, url, category, published_at} 반환.
    config 없으면 None. 어댑터 예외 시 [] 반환(빈 결과).

    `body_sample` > 0 이면 첫 `body_sample` 건은 fetch_article 도 시도해서 `body_chars` 키 추가
    (네트워크 1건당 1회 추가 — 본문 추출 깨짐 신호 진단용). 본문 fetch 예외는 body_chars=None 으로."""
    cfg = _config_for(slug, paths)
    if cfg is None:
        return None
    from engine import make_adapter  # 무거우니 lazy
    out: list[dict] = []
    try:
        async with make_adapter(cfg) as a:
            posts = await a.fetch_list(page=1, page_size=n)
            for i, p in enumerate(posts[:n]):
                try:
                    d = p.to_dict()
                except Exception:  # noqa: BLE001
                    d = {"post_id": getattr(p, "post_id", None), "title": getattr(p, "title", None),
                         "url": getattr(p, "url", None)}
                row = {k: d.get(k) for k in ("post_id", "title", "url", "category", "published_at")}
                if i < body_sample:
                    try:
                        f = await a.fetch_article(p)
                        row["body_chars"] = len(f.content_html or "")
                    except Exception:  # noqa: BLE001
                        row["body_chars"] = None
                out.append(row)
    except Exception:  # noqa: BLE001  진단용이라 빈 결과로
        return [] if not out else out
    return out


# --------------------------------------------------------------------------- #
# Markdown formatting (Discord 메시지 / CLI stdout 공용)
# --------------------------------------------------------------------------- #
_SEVERITY_BADGE = {"error": "🔴", "warn": "🟡", "info": "ℹ️"}


def format_findings(findings: list[DiagnoseFinding]) -> str:
    if not findings:
        return "_(진단 결과 깨짐 신호 없음)_"
    lines = []
    for f in findings:
        lines.append(f"{_SEVERITY_BADGE.get(f.severity, '•')} **{f.tag}** ({f.severity}): {f.msg}")
    return "\n".join(lines)


def _short_json(d: Any, *, limit: int = 600) -> str:
    if d is None:
        return "_(없음)_"
    s = json.dumps(d, ensure_ascii=False, indent=2)
    if len(s) > limit:
        s = s[:limit] + f"\n… (truncated, 전체 {len(s)} chars)"
    return f"```json\n{s}\n```"


def format_inspect_result(r: InspectResult) -> str:
    parts: list[str] = []
    parts.append(f"## inspect: `{r.slug}`")

    if r.report:
        rp = r.report
        # issue 는 사용자 입력이라 markdown/멘션 무력화: code-fence 로 감쌈.
        # 본인이 ``` 를 박아 fence 깰 수는 있지만 owner DM 한정이라 안전 영향 미미.
        issue_text = (rp.get("issue") or "").replace("```", "ʼʼʼ")
        parts.append(f"### 신고 #{rp['id']} ({rp['status']})\n"
                     f"- user: `{rp['user_id']}` ({rp.get('username') or '?'})\n"
                     f"- 시각: {rp['created_at']}\n"
                     f"- issue:\n```\n{issue_text}\n```")
        if rp.get("resolved_note"):
            parts.append(f"  - resolved_note: {rp['resolved_note']}")

    parts.append("### 진단\n" + format_findings(r.findings))

    if r.latest_job:
        j = r.latest_job
        rb = j.get("requested_by") or {}
        rb_str = f"{rb.get('name', '?')} (id={rb.get('id', '?')})" if isinstance(rb, dict) else str(rb)
        parts.append(f"### 최근 register 잡 #{j['id']}\n"
                     f"- via: `{j.get('via')}` · status: `{j.get('status')}` (rc={j.get('result_rc')})\n"
                     f"- 요청자: {rb_str}\n"
                     f"- 제출 URL: `{j.get('url')}`\n"
                     f"- article_url: `{j.get('article_url') or '없음'}`\n"
                     f"- 시작/종료: {j.get('started_at')} → {j.get('finished_at')}")
        tail = j.get("result_tail")
        if tail:
            t = (tail or "").strip()[-1200:]
            parts.append(f"- register.py tail:\n```\n{t}\n```")
    else:
        parts.append("### 최근 register 잡\n_(없음 — 잡 큐 거치지 않은 경로이거나 너무 오래됨)_")

    if r.subscriptions:
        sub_lines = ["### 구독 행 (DB)"]
        for s in r.subscriptions:
            sub_lines.append(f"- user=`{s.get('user_id')}` target=`{s.get('target_kind')}/{s.get('target_id')}` "
                             f"filter={s.get('filter_prompt') or '없음'} notify_empty={s.get('notify_empty')} "
                             f"created={s.get('created_at')[:10]}\n  url=`{s.get('url')}`")
        parts.append("\n".join(sub_lines))
    else:
        parts.append("### 구독 행\n_(없음)_")

    parts.append("### config\n" + _short_json(r.config))
    parts.append("### state\n" + _short_json(r.state))

    if r.fetch_sample is not None:
        if not r.fetch_sample:
            parts.append("### fetch_sim\n_(0건 — 어댑터 실패 또는 selector drift)_")
        else:
            lines = ["### fetch_sim (현 config 로 지금 받아본 결과)"]
            for p in r.fetch_sample:
                t = (p.get("title") or "")[:80]
                bc = p.get("body_chars")
                tail = ""
                if bc is not None:
                    tail = f"  body={bc}자" if bc > 0 else "  body=**0자** ⚠️"
                lines.append(f"- `{p.get('post_id')}` · {t}\n  {p.get('url')}{tail}")
            parts.append("\n".join(lines))

    return "\n\n".join(parts)


def triage_summary(conn: sqlite3.Connection, paths: "InspectorPaths") -> dict:
    """admin 처리-대기 backlog 카운트. state dir 스캔 + DB 카운트."""
    from datetime import datetime, timedelta, timezone

    open_reports = db.list_reports(conn, status="open", limit=500)
    all_feedback = db.list_feedback(conn, limit=1000)
    pending_jobs = db.queue_pending_count(conn)
    jobs_summary = db.jobs_summary(conn)

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    def _is_recent(iso: str) -> bool:
        try:
            return datetime.fromisoformat(iso) >= cutoff
        except (ValueError, TypeError):
            return False
    recent_fb_count = sum(1 for f in all_feedback if _is_recent(f["created_at"]))
    recent_report_count = sum(1 for r in open_reports if _is_recent(r["created_at"]))

    broken: list[str] = []
    failed: list[str] = []
    if paths.state_dir.exists():
        for f in paths.state_dir.glob("*.json"):
            if f.name.endswith(".FAILED.json"):
                failed.append(f.name[: -len(".FAILED.json")])
                continue
            d = _read_json(f)
            if d and int(d.get("consecutive_breakage", 0) or 0) > 0:
                broken.append(d.get("slug", f.stem))

    return {
        "open_reports": len(open_reports),
        "open_reports_recent_7d": recent_report_count,
        "feedback_total": len(all_feedback),
        "feedback_recent_7d": recent_fb_count,
        "broken_slugs": sorted(broken),
        "failed_slugs": sorted(failed),
        "pending_jobs": pending_jobs,
        "running_jobs": int(jobs_summary.get("running", 0)),
    }


def format_triage(summary: dict) -> str:
    lines = ["**🚦 Triage 백로그**"]
    lines.append(f"• 미해결 신고(open): **{summary['open_reports']}건** "
                 f"(최근 7d: {summary['open_reports_recent_7d']}건)")
    bs = summary["broken_slugs"]
    lines.append(f"• 깨짐 신호 slug: **{len(bs)}건**"
                 + (f" — {', '.join(bs)}" if bs else ""))
    fs = summary["failed_slugs"]
    lines.append(f"• 자동등록 실패 slug: **{len(fs)}건**"
                 + (f" — {', '.join(fs)}" if fs else ""))
    lines.append(f"• 잡 큐: pending {summary['pending_jobs']}건 / running {summary['running_jobs']}건")
    lines.append(f"• 의견(feedback) 누적: **{summary['feedback_total']}건** "
                 f"(최근 7d: {summary['feedback_recent_7d']}건)")
    return "\n".join(lines)


def format_recent_jobs(rows: list[dict]) -> str:
    if not rows:
        return "_(최근 register 잡 없음)_"
    lines = ["**최근 register 잡:**"]
    for r in rows:
        rb = r.get("requested_by") or {}
        if isinstance(rb, dict):
            name = rb.get("name", "?")
            uid = rb.get("id")
            rb_str = f"{name} (<@{uid}>)" if uid else name
        else:
            rb_str = "?"
        # preview 잡은 sub_payload 없음. watch 잡은 filter_prompt(None/문자열) 가 안에 있음.
        sp = r.get("sub_payload")
        filt_line = ""
        if isinstance(sp, dict):
            fp = sp.get("filter_prompt")
            target_kind = sp.get("target_kind") or "?"
            ne = " · notify_empty" if sp.get("notify_empty") else ""
            filt_line = f"\n   filter: {fp if fp else '없음(새 글 전부)'} · target={target_kind}{ne}"
        lines.append(
            f"- #{r['id']} `{r.get('slug')}` · {r.get('status')} · via={r.get('via')} · {rb_str}\n"
            f"   URL: {r.get('url')}{filt_line}\n"
            f"   {r.get('finished_at') or r.get('created_at')}")
    return "\n".join(lines)


def format_reports(rows: list[dict]) -> str:
    if not rows:
        return "_(신고 없음)_"
    lines = ["**신고:**"]
    for r in rows:
        # issue 는 사용자 입력 — 한 줄 요약에선 markdown 무력화: 줄바꿈 제거 + 한 줄 backtick 코드.
        # ` 자체가 들어있으면 비슷한 zero-width 로 치환해 깨지지 않게.
        raw = (r.get("issue") or "").replace("\n", " ").replace("\r", " ").replace("`", "ʼ")
        snippet = raw[:140] + ("…" if len(raw) > 140 else "")
        lines.append(f"- #{r['id']} `{r['slug']}` · {r['status']} · {r.get('username') or r['user_id']} · {r['created_at'][:16]}\n"
                     f"   `{snippet}`")
    return "\n".join(lines)


def chunk_for_discord(text: str, *, limit: int = 1900) -> list[str]:
    """Discord 메시지 2000 자 제한 회피. 줄 경계로 split."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and buf:
            chunks.append("".join(buf))
            buf = [line]
            size = len(line)
        else:
            buf.append(line)
            size += len(line)
    if buf:
        chunks.append("".join(buf))
    return chunks
