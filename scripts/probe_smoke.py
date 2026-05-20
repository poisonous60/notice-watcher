"""probe smoke test — 산출물·digest·config·휴리스틱 회귀를 단일 명령으로 잡는다.

`probe/` 휴리스틱·산출물 키·`engine/digest.py`·`engine/config_schema.py` 등을 수정한 뒤
다운스트림 silent fail(`or {}` 방어로 통과되는 누락)을 잡으려고 만든 게이트.

stage 4 종 (모두 네트워크 0, offline):
  1. artifacts schema      — output/probe/<slug>/ 의 파일·키 존재 + mtime 신선도
                             (1b: contract self-check, 1c: prompt-sync WARN)
  2. digest integrity      — engine.digest.build_digest 의 결과 9가지 단언 + slug-specific 값 의미
  3. configs validate      — configs/*.json 전수 validate_config + make_adapter 인스턴스화
  5. heuristic units       — tests/probe_heuristics/test_*.py 의 휴리스틱 unit 테스트 자동 발견·실행
                             (새 휴리스틱 추가 시 fixture 파일 하나 추가하면 자동 picked up)

사용:
    python scripts/probe_smoke.py                    # 전체 (offline, ~1s)
    python scripts/probe_smoke.py --verbose          # FAIL detail 길게
    python scripts/probe_smoke.py --slug skku        # 한 slug 만 (stage 1·2 만 영향)
    python scripts/probe_smoke.py --stage 5          # 한 stage 만 (반복 가능)
    python scripts/probe_smoke.py --json             # 머신 리더블 출력

회귀 주입 메타-테스트 예시는 docs 또는 plan 파일 참고.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import load_config, validate_config, make_adapter, ConfigError  # noqa: E402
from engine.digest import build_digest, DEFAULT_MAX_HTML_BYTES  # noqa: E402
from probe.paths import output_dir, url_to_slug, OUTPUT_ROOT  # noqa: E402
from probe._contract import (  # noqa: E402
    OUTPUT_SCHEMA,
    ContractError,
    validate_payload,
    required_keys,
    prompt_required_keys,
    LIST_CANDIDATES_KEYS as LIST_CAND_KEYS,
    DIAGNOSIS_TOP_KEYS,
    DIAGNOSIS_RESULT_KEYS,
    ROBOTS_KEYS,
    ARTICLE_CLICK_KEYS,
)

CONFIGS_DIR = ROOT / "configs"
PROBE_DIR = ROOT / "probe"


# ----------------------------------------------------------------------------
# Spec / Result
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Spec:
    name: str
    url: str
    has_article_click: bool = False

    @property
    def slug(self) -> str:
        return url_to_slug(self.url)


REPS: list[Spec] = [
    Spec(name="skku",
         url="https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582&srSearchKey=&srSearchVal="),
    # httpx_json fixture: SPA 페이지 로드 시 클라이언트가 JSON feed API 를 XHR 로 호출 →
    # probe HAR 가 그 호출을 캡처 → traffic_json_api_candidates 점수화 휴리스틱이 광고/SDK 와
    # 구분하여 진짜 feed API 를 1위로 골라야 함. (이전 endfield 는 Next.js prerender 라
    # XHR 안 함 → fixture 부적절했음, commit 99f4f0b 의 잘못된 가정. 2026-05-15 trickcal 로 교체.)
    Spec(name="trickcal",
         url="https://game.naver.com/lounge/Trickcal/board/3"),
    Spec(name="arca",
         url="https://arca.live/b/akendfield"),
    Spec(name="mabinogi",
         url="https://mabinogimobile.nexon.com/News/notice",
         has_article_click=True),
]


@dataclass
class Result:
    stage: int
    target: str               # slug name 또는 'configs' (stage 3)
    status: str               # 'PASS' | 'FAIL' | 'WARN' | 'SKIP'
    detail: str = ""
    extras: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------
# Stage 1 — artifacts schema (probe/_contract.OUTPUT_SCHEMA 가 single source of truth)
# ----------------------------------------------------------------------------
_PROBE_HEURISTIC_FILES = ("extract.py", "fetch_headless.py", "fetch_static.py", "hydration.py")


def _max_heuristic_mtime() -> float:
    mtimes = []
    for name in _PROBE_HEURISTIC_FILES:
        p = PROBE_DIR / name
        if p.exists():
            mtimes.append(p.stat().st_mtime)
    return max(mtimes) if mtimes else 0.0


def _validate_artifact(file_name: str, payload: Any, *, slug: str) -> Optional[str]:
    """contract validate → 위반 메시지 (없으면 None)."""
    try:
        validate_payload(file_name, payload, strict=True, allow_extra=True)
    except ContractError as e:
        return f"{slug}/{file_name}: {e}"
    return None


def stage1_artifacts_schema(rep: Spec, *, heuristic_mtime: float) -> Result:
    od = output_dir(rep.slug)
    if not od.exists():
        return Result(1, rep.name, "WARN", f"산출물 디렉토리 없음 — `python scripts/probe.py \"{rep.url}\"` 먼저")

    # slug sanity
    if url_to_slug(rep.url) != rep.slug:
        return Result(1, rep.name, "FAIL", f"url_to_slug 회귀: {url_to_slug(rep.url)!r} != REPS slug {rep.slug!r}")

    diag_p = od / "diagnosis.json"
    if not diag_p.exists():
        return Result(1, rep.name, "FAIL", "diagnosis.json 없음")

    # contract 기반 검증 — OUTPUT_SCHEMA 의 모든 산출물 순회
    warn_msgs: list[str] = []
    for fname, contract in OUTPUT_SCHEMA.items():
        p = od / fname
        if not p.exists():
            if contract.optional_on_disk:
                continue
            return Result(1, rep.name, "FAIL", f"필수 산출물 없음: {fname}")
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return Result(1, rep.name, "FAIL", f"{fname} 파싱 실패: {e}")
        # diagnosis.json: 옛 산출물(11키 contract 도입 이전) 호환 — 필수 6 키 + results 만 hard, 나머지는 WARN (audit [E])
        if fname == "diagnosis.json":
            hard_keys = ("slug", "url", "verdict", "recommended_strategy", "article_entry_ok", "results")
            missing_hard = [k for k in hard_keys if k not in payload]
            if missing_hard:
                return Result(1, rep.name, "FAIL",
                              f"diagnosis.json: missing hard keys {missing_hard}")
            missing_soft = [k for k in DIAGNOSIS_TOP_KEYS if k not in payload and k not in hard_keys]
            if missing_soft:
                warn_msgs.append(f"diagnosis.json: 옛 산출물 — 신규 키 누락 {missing_soft} (재 probe 권유)")
            results = payload.get("results") or []
            for i, r in enumerate(results):
                missing_r = [k for k in DIAGNOSIS_RESULT_KEYS if k not in r]
                if missing_r:
                    return Result(1, rep.name, "FAIL",
                                  f"diagnosis.json: results[{i}] missing keys {missing_r}")
            continue
        # 그 외 = contract 가 strict 검증
        msg = _validate_artifact(fname, payload, slug=rep.slug)
        if msg:
            return Result(1, rep.name, "FAIL", msg)

    # article_click.json (has_article_click=True slug 만 추가 보장)
    if rep.has_article_click and not (od / "article_click.json").exists():
        return Result(1, rep.name, "FAIL", "article_click.json 없음 (has_article_click=True spec)")

    # mtime 신선도 — heuristic 변경 후 산출물 재생성 안 했으면 WARN (FAIL X)
    if heuristic_mtime > 0 and diag_p.stat().st_mtime < heuristic_mtime:
        warn_msgs.append(
            f"diagnosis.json 이 probe/ 휴리스틱보다 옛것 — `python scripts/probe.py \"{rep.url}\"` 재생성 권유"
        )

    if warn_msgs:
        return Result(1, rep.name, "WARN", " | ".join(warn_msgs))

    n_files = sum(1 for _ in od.iterdir() if _.is_file())
    return Result(1, rep.name, "PASS", f"{n_files} files, contract OK")


# ----------------------------------------------------------------------------
# Stage 1b — contract self-check (audit [A]):
#   write 함수가 실제 산출에 쓰는 키 set vs contract 가 선언한 set 일치 여부.
#   write 가 contract 보다 새 키 늘렸는데 contract 안 갱신 = contract 회귀 detect.
# ----------------------------------------------------------------------------
def stage1b_contract_self_check() -> list[Result]:
    """디스크의 한 산출물 샘플을 골라, contract 선언 키 ⊆ payload 키 + payload extra 키 = 보고."""
    out: list[Result] = []
    sample_slugs = [r.slug for r in REPS if output_dir(r.slug).exists()]
    if not sample_slugs:
        return [Result(1, "_contract_xcheck", "SKIP", "REPS slug 산출물 없음")]
    for fname, contract in OUTPUT_SCHEMA.items():
        # 첫 발견 산출물에서 키 union 추출 (object payload 만)
        if contract.payload_kind != "object":
            continue
        for slug in sample_slugs:
            p = output_dir(slug) / fname
            if not p.exists():
                continue
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            contract_names = {f.name for f in contract.fields}
            payload_keys = set(payload)
            unknown = payload_keys - contract_names
            if unknown:
                out.append(Result(
                    1, f"_xcheck:{fname}", "WARN",
                    f"산출물에 contract 미선언 키: {sorted(unknown)} (slug={slug})",
                ))
            break
        else:
            continue
    if not any(r.status == "FAIL" for r in out):
        out.append(Result(1, "_contract_xcheck", "PASS",
                          f"OUTPUT_SCHEMA {len(OUTPUT_SCHEMA)} 산출물 키 일치"))
    return out


# ----------------------------------------------------------------------------
# Stage 1c — prompt-sync (audit [F]):
#   _PROMPT_REQUIRED_KEY_PATHS 의 키들이 prompts/config_writer.system.txt 에
#   word-boundary 로 등장하는지 검사. _ContractField.prompt_aliases 도 인정.
#   누락 = WARN (rename 잊었나 신호 — FAIL 차단은 안 함).
# ----------------------------------------------------------------------------
PROMPTS_DIR = ROOT / "prompts"


def stage1c_prompt_sync() -> list[Result]:
    target = PROMPTS_DIR / "config_writer.system.txt"
    if not target.exists():
        return [Result(1, "_prompt_sync", "SKIP", f"{target} 없음")]
    txt = target.read_text(encoding="utf-8")
    import re as _re
    missing: list[str] = []
    for key_id, candidates in prompt_required_keys().items():
        for name in candidates:
            # word-boundary — `id` / `url` 같은 짧은 키의 false positive 방지
            if _re.search(rf"\b{_re.escape(name)}\b", txt):
                break
        else:
            missing.append(key_id)
    if missing:
        return [Result(
            1, "_prompt_sync", "WARN",
            f"prompts/config_writer.system.txt 에 등장 안 함: {missing} (rename 잊었나)",
        )]
    return [Result(1, "_prompt_sync", "PASS",
                   f"{len(prompt_required_keys())} 핵심 키 모두 프롬프트 등장")]


# ----------------------------------------------------------------------------
# Stage 2 — digest integrity
# ----------------------------------------------------------------------------
DIGEST_ARTICLE_SAMPLE_KEYS = ("url", "source", "html", "api_candidates", "clicked_resolved_url", "clicked_note")


def stage2_digest_integrity(rep: Spec) -> Result:
    od = output_dir(rep.slug)
    if not od.exists():
        return Result(2, rep.name, "SKIP", "산출물 없음 (stage 1 WARN 참조)")

    try:
        digest = build_digest(slug=rep.slug)
    except Exception as e:
        return Result(2, rep.name, "FAIL", f"build_digest 예외: {type(e).__name__}: {e}")

    # 구조 단언
    if not digest.get("url"):
        return Result(2, rep.name, "FAIL", "digest.url 비어있음")
    if not digest.get("verdict"):
        return Result(2, rep.name, "FAIL", "digest.verdict 비어있음")
    em = digest.get("entry_matrix")
    if not isinstance(em, list) or not em:
        return Result(2, rep.name, "FAIL", "entry_matrix 비어있음")
    if not any(r.get("target") == "list" for r in em):
        return Result(2, rep.name, "FAIL", "entry_matrix 에 target=='list' 결과 없음")

    lh = digest.get("list_html") or {}
    html = lh.get("html") or ""
    if not html:
        return Result(2, rep.name, "FAIL", "list_html.html 비어있음")
    if len(html.encode("utf-8")) > int(DEFAULT_MAX_HTML_BYTES * 1.1):
        return Result(2, rep.name, "FAIL", f"list_html.html 비정상 크기: {len(html.encode('utf-8'))} bytes")

    lc = digest.get("list_candidates")
    if not isinstance(lc, dict):
        return Result(2, rep.name, "FAIL", "list_candidates 가 dict 아님")
    for k in LIST_CAND_KEYS:
        if k not in lc:
            return Result(2, rep.name, "FAIL", f"list_candidates: missing key {k!r}")

    rb = digest.get("robots")
    if not isinstance(rb, dict):
        return Result(2, rep.name, "FAIL", "robots 가 dict 아님")
    # digest 가 만드는 robots dict 는 3 키만 — 산출물 robots.json 의 부분집합
    # (engine/digest.py:275-279 는 status/crawl_delay/disallow 만 추출)
    for k in ("status", "crawl_delay", "disallow"):
        if k not in rb:
            return Result(2, rep.name, "FAIL", f"robots: missing key {k!r}")

    asp = digest.get("article_sample")
    if not isinstance(asp, dict):
        return Result(2, rep.name, "FAIL", "article_sample 가 dict 아님")
    for k in DIGEST_ARTICLE_SAMPLE_KEYS:
        if k not in asp:
            return Result(2, rep.name, "FAIL", f"article_sample: missing key {k!r}")

    fc = digest.get("feed_candidates")
    if not isinstance(fc, list):
        return Result(2, rep.name, "FAIL", f"feed_candidates 가 list 아님 (got {type(fc).__name__})")

    # ----- 값 의미 (slug-specific, audit #2 #3 #4) -----
    extras: dict[str, Any] = {
        "entry_matrix_n": len(em),
        "list_html_kb": len(html.encode("utf-8")) // 1024,
    }

    if rep.name == "skku":
        # httpx_html: 첫 글 URL 이 article_sample.url 로 흘러와야 함
        if asp.get("url") is None:
            return Result(2, rep.name, "FAIL", "article_sample.url=None (first_article_url 키 rename 회귀 의심)")
        extras["article_sample_url"] = "ok"

    if rep.name == "trickcal":
        # httpx_json: traffic JSON API 후보가 있어야 하고, 첫 후보 relevance_score>0.
        # SPA (Naver lounge) → 클라이언트가 comm-api.game.naver.com/.../feed 을 XHR 로 호출 →
        # HAR 캡처 → 점수화 휴리스틱이 광고/SDK 와 구분해 feed API 를 1위로.
        cands = lc.get("traffic_json_api_candidates") or []
        if not cands:
            return Result(2, rep.name, "FAIL", "traffic_json_api_candidates 비어있음 (점수화 회귀 의심)")
        score = cands[0].get("relevance_score")
        if not isinstance(score, (int, float)) or score <= 0:
            return Result(
                2, rep.name, "FAIL",
                f"traffic_json_api_candidates[0].relevance_score={score!r} (점수화 회귀 의심)",
            )
        extras["top_score"] = score

    if rep.name == "arca":
        # playwright_html: S4 prefix 가 entry_matrix 에 존재해야 함
        # _pick_list_result 가 startswith("S4") 로 헤드리스 우선순위 매김 → rename 시 회귀
        if not any(str(r.get("strategy", "")).startswith("S4") for r in em):
            return Result(
                2, rep.name, "FAIL",
                "entry_matrix 에 S4 prefix 전략 없음 (strategy 명명 회귀 의심: 'S4' → 'headless.click' 등)",
            )
        extras["s4_in_matrix"] = "ok"

    if rep.name == "mabinogi":
        # article_click 사이트: clicked_resolved_url 가 채워져야 함
        if not asp.get("clicked_resolved_url"):
            return Result(
                2, rep.name, "FAIL",
                "article_sample.clicked_resolved_url=None (article_click.json 미통합 회귀 의심)",
            )
        extras["clicked_resolved_url"] = "ok"

    return Result(2, rep.name, "PASS", f"em={extras.get('entry_matrix_n')} html={extras.get('list_html_kb')}KB", extras=extras)


# ----------------------------------------------------------------------------
# Stage 3 — configs validate + make_adapter
# ----------------------------------------------------------------------------
def stage3_configs_validate() -> list[Result]:
    out: list[Result] = []
    if not CONFIGS_DIR.exists():
        return [Result(3, "configs", "FAIL", f"{CONFIGS_DIR} 디렉토리 없음")]

    paths = sorted(CONFIGS_DIR.glob("*.json"))
    if not paths:
        return [Result(3, "configs", "WARN", "configs/*.json 없음")]

    fails = 0
    for cp in paths:
        try:
            cfg = load_config(cp)
        except Exception as e:
            out.append(Result(3, cp.name, "FAIL", f"load 실패: {e}"))
            fails += 1
            continue
        try:
            validate_config(cfg)
        except ConfigError as e:
            out.append(Result(3, cp.name, "FAIL", f"validate 실패: {e}"))
            fails += 1
            continue
        except Exception as e:
            out.append(Result(3, cp.name, "FAIL", f"validate 예외: {type(e).__name__}: {e}"))
            fails += 1
            continue
        try:
            adapter = make_adapter(cfg, validate=False)
        except Exception as e:
            out.append(Result(3, cp.name, "FAIL", f"make_adapter 실패: {type(e).__name__}: {e}"))
            fails += 1
            continue
        # handwritten 어댑터의 _client 가 None 단언 (네트워크 안 열렸음)
        if cfg.get("strategy") == "handwritten":
            client_attr = getattr(adapter, "_client", "<missing>")
            if client_attr not in (None, "<missing>"):
                out.append(Result(
                    3, cp.name, "WARN",
                    f"handwritten adapter._client 가 __init__ 에서 None 아님 (네트워크 회피 의심)",
                ))
                continue
        out.append(Result(3, cp.name, "PASS", f"strategy={cfg.get('strategy')}"))

    summary = Result(3, "_summary", "PASS" if fails == 0 else "FAIL",
                     f"{len(paths) - fails} / {len(paths)} OK")
    out.append(summary)
    return out


# ----------------------------------------------------------------------------
# Stage 5 — heuristic units (tests/probe_heuristics/test_*.py 자동 발견·실행)
# + engine regression units (tests/validate/test_*.py)
# ----------------------------------------------------------------------------
HEURISTIC_TESTS_DIR = ROOT / "tests" / "probe_heuristics"
EXTRA_UNIT_TEST_DIRS = [ROOT / "tests" / "validate",
                        ROOT / "tests" / "fail_taxonomy",
                        ROOT / "tests" / "state_lifecycle",
                        ROOT / "tests" / "recognizers"]  # 비-휴리스틱 engine 회귀 테스트


def _load_test_module(test_py: Path):
    """test_*.py 모듈 동적 로드. import 실패 시 raise."""
    spec = importlib.util.spec_from_file_location(f"probe_smoke_tests_{test_py.stem}", test_py)
    if spec is None or spec.loader is None:
        raise ImportError(f"spec_from_file_location 실패: {test_py}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _heuristic_coverage() -> tuple[list[str], list[str]]:
    """@heuristic 으로 등록된 함수 vs fixture 파일명 매칭.

    fixture 파일명 컨벤션:
      - `test_<함수명>.py` (private 함수의 _ 접두사 제거)
      - 합본은 `test_X_and_Y.py` (X 와 Y 둘 다 커버)

    반환: (covered_funcs, missing_funcs) — 둘 다 짧은 이름(밑줄 stripped) 리스트.
    """
    # probe 의 모든 휴리스틱 모듈 import (등록 트리거)
    import probe.extract  # noqa: F401
    import probe.hydration  # noqa: F401
    import probe.fetch_headless  # noqa: F401
    import probe.paths  # noqa: F401
    from probe._heuristic import HEURISTICS

    # 등록된 함수의 짧은 이름 (밑줄 접두사 제거)
    registered = {qn.lstrip("_") for _mod, qn in HEURISTICS}

    # fixture 파일명에서 커버된 함수 이름 추출
    if not HEURISTIC_TESTS_DIR.exists():
        return [], sorted(registered)
    covered: set[str] = set()
    for fp in HEURISTIC_TESTS_DIR.glob("test_*.py"):
        # 모듈 안에 covers = [...] 선언이 있으면 그것 우선 (한 fixture 가 여러 휴리스틱 커버 가능)
        explicit: Optional[list[str]] = None
        try:
            mod = _load_test_module(fp)
            cov = getattr(mod, "covers", None)
            if isinstance(cov, (list, tuple)):
                explicit = [str(x).lstrip("_") for x in cov]
        except Exception:
            explicit = None
        if explicit:
            covered.update(explicit)
            continue
        # fallback: 파일명 "test_X_and_Y" → "X", "Y"
        stem = fp.stem[len("test_"):]
        for piece in stem.split("_and_"):
            covered.add(piece)

    missing = sorted(registered - covered)
    found = sorted(registered & covered)
    return found, missing


def stage5_heuristic_units() -> list[Result]:
    out: list[Result] = []
    if not HEURISTIC_TESTS_DIR.exists():
        return [Result(5, "_dir", "WARN", f"{HEURISTIC_TESTS_DIR.relative_to(ROOT)} 없음 — 휴리스틱 unit 테스트 디렉토리")]
    files = sorted(HEURISTIC_TESTS_DIR.glob("test_*.py"))
    for extra_dir in EXTRA_UNIT_TEST_DIRS:
        if extra_dir.exists():
            files.extend(sorted(extra_dir.glob("test_*.py")))
    if not files:
        return [Result(5, "_dir", "WARN", f"{HEURISTIC_TESTS_DIR.relative_to(ROOT)}/test_*.py 없음")]

    n_files = 0
    n_cases = 0
    n_fail = 0
    for fp in files:
        n_files += 1
        try:
            mod = _load_test_module(fp)
        except Exception as e:
            out.append(Result(5, fp.stem, "FAIL",
                              f"import 실패: {type(e).__name__}: {e}",
                              extras={"traceback": traceback.format_exc()}))
            n_fail += 1
            continue
        run_fn = getattr(mod, "run", None)
        if not callable(run_fn):
            out.append(Result(5, fp.stem, "WARN", "run() 함수 없음 — protocol 미준수"))
            continue
        try:
            cases = run_fn()
        except Exception as e:
            out.append(Result(5, fp.stem, "FAIL",
                              f"run() 예외: {type(e).__name__}: {e}",
                              extras={"traceback": traceback.format_exc()}))
            n_fail += 1
            continue
        if not isinstance(cases, list):
            out.append(Result(5, fp.stem, "FAIL",
                              f"run() 반환 list 아님: {type(cases).__name__}"))
            n_fail += 1
            continue
        for c in cases:
            n_cases += 1
            try:
                case_name, ok, msg = c
            except Exception:
                out.append(Result(5, f"{fp.stem}:<bad-case>", "FAIL",
                                  f"case 튜플 형식 X: {c!r}"))
                n_fail += 1
                continue
            target = f"{fp.stem}:{case_name}"
            if ok:
                out.append(Result(5, target, "PASS", ""))
            else:
                out.append(Result(5, target, "FAIL", msg or "(no detail)"))
                n_fail += 1

    # coverage 검증 — @heuristic 등록 함수 vs fixture 파일명 매칭
    try:
        covered, missing = _heuristic_coverage()
    except Exception as e:
        out.append(Result(5, "_coverage", "WARN",
                          f"coverage 검사 실패: {type(e).__name__}: {e}"))
        covered, missing = [], []

    cov_total = len(covered) + len(missing)
    if missing:
        out.append(Result(
            5, "_coverage", "FAIL",
            f"{len(covered)}/{cov_total} @heuristic fixture 보유 — 누락: {missing}",
        ))
        n_fail += 1
    elif cov_total > 0:
        out.append(Result(5, "_coverage", "PASS", f"{cov_total}/{cov_total} @heuristic fixture 보유"))

    out.append(Result(5, "_summary", "PASS" if n_fail == 0 else "FAIL",
                      f"{n_files} 파일 · {n_cases} 케이스 · {n_fail} FAIL · coverage {len(covered)}/{cov_total}"))
    return out


# ----------------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------------
_STAGE_TITLES = {
    1: "artifacts schema",
    2: "digest integrity",
    3: "configs validate + make_adapter",
    4: "register --reuse-probe (Gemini)",
    5: "heuristic units (tests/probe_heuristics/)",
}


def render_summary(results: list[Result], *, elapsed: float, verbose: bool) -> str:
    out: list[str] = []
    out.append("==== probe smoke ====")

    by_stage: dict[int, list[Result]] = {}
    for r in results:
        by_stage.setdefault(r.stage, []).append(r)

    for stage in sorted(by_stage):
        title = _STAGE_TITLES.get(stage, f"stage {stage}")
        out.append(f"\n[stage {stage}] {title}")
        rs = by_stage[stage]
        # Stage 3·5 는 summary 라인만 강조; 개별 항목은 FAIL/WARN 만 노출
        if stage in (3, 5):
            summary = next((r for r in rs if r.target == "_summary"), None)
            non_pass = [r for r in rs if r.target != "_summary" and r.status != "PASS"]
            for r in non_pass:
                out.append(f"  {r.target:<48}: {r.status} {r.detail}")
                if verbose and r.extras.get("traceback"):
                    out.append("      " + r.extras["traceback"].rstrip().replace("\n", "\n      "))
            if summary:
                out.append(f"  {summary.detail}")
            continue
        for r in rs:
            line = f"  {r.target:<24}: {r.status} {r.detail}"
            out.append(line)
            if verbose and r.extras:
                out.append(f"      {r.extras}")

    # summary footer
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
    for r in results:
        if r.target == "_summary":
            continue
        counts[r.status] = counts.get(r.status, 0) + 1
    fail_n = counts["FAIL"]
    out.append(f"\n==== summary ====  PASS {counts['PASS']}  FAIL {counts['FAIL']}  "
               f"WARN {counts['WARN']}  SKIP {counts['SKIP']}  ({elapsed:.1f}s)  → exit {1 if fail_n else 0}")
    return "\n".join(out)


def render_json(results: list[Result], *, elapsed: float) -> str:
    payload = {
        "elapsed_sec": round(elapsed, 2),
        "results": [
            {"stage": r.stage, "target": r.target, "status": r.status, "detail": r.detail, "extras": r.extras}
            for r in results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="probe 산출물·digest·config 회귀 smoke test")
    p.add_argument("--verbose", action="store_true", help="FAIL detail / extras 길게")
    p.add_argument("--slug", action="append", help="특정 REPS 이름만 (반복 가능): skku/trickcal/arca/mabinogi")
    p.add_argument("--stage", type=int, action="append", choices=[1, 2, 3, 5],
                   help="특정 stage 만 실행 (반복 가능)")
    p.add_argument("--json", action="store_true", help="머신리더블 JSON 출력")
    args = p.parse_args(argv)

    started = time.time()
    stages = set(args.stage) if args.stage else {1, 2, 3, 5}

    reps = REPS
    if args.slug:
        names = set(args.slug)
        reps = [r for r in REPS if r.name in names]
        unknown = names - {r.name for r in REPS}
        if unknown:
            print(f"[probe-smoke] 알 수 없는 slug: {sorted(unknown)} — 무시", file=sys.stderr)
        if not reps:
            print("[probe-smoke] 매칭되는 slug 없음", file=sys.stderr)
            return 2

    results: list[Result] = []

    # stage 1 (+1b self-check, +1c prompt-sync — 항상 같이)
    if 1 in stages:
        h_mtime = _max_heuristic_mtime()
        for rep in reps:
            results.append(stage1_artifacts_schema(rep, heuristic_mtime=h_mtime))
        results.extend(stage1b_contract_self_check())
        results.extend(stage1c_prompt_sync())

    # stage 2
    if 2 in stages:
        for rep in reps:
            results.append(stage2_digest_integrity(rep))

    # stage 3 (slug 필터 무관 — configs 전체)
    if 3 in stages:
        results.extend(stage3_configs_validate())

    # stage 5 (slug 필터 무관 — 휴리스틱 unit 테스트 전수)
    if 5 in stages:
        results.extend(stage5_heuristic_units())

    elapsed = time.time() - started

    if args.json:
        print(render_json(results, elapsed=elapsed))
    else:
        print(render_summary(results, elapsed=elapsed, verbose=args.verbose))

    fail_n = sum(1 for r in results if r.status == "FAIL" and r.target != "_summary")
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
