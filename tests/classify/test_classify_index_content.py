"""LLM index/content 분류기 + register veto 헬퍼 단위 테스트 (offline, mock client).

분류 *정확도* 는 PoC(scripts/_exp_classify_*.py, board recall 0.905)로 검증됨 — 여기선
배선만 본다: HTML source 읽기·prompt 조립·temperature=0·JSON 파싱·실패 fallback·struct hint,
그리고 register 의 veto override 임계·memoize·gate-only skip·마커/learn 경로.
스타일: 다른 stage5 테스트와 동일 `run()` 반환 + `__main__`.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from generate.llm_base import LLMClient, LLMResponse, LLMQuotaError  # noqa: E402
import generate.classify as classify_mod  # noqa: E402
from generate.classify import classify_index_content, _struct_hint  # noqa: E402


class _FakeClient(LLMClient):
    provider = "fake"

    def __init__(self, text='{"class":"index","confidence":0.9,"reason":"r"}',
                 raise_exc: Optional[Exception] = None) -> None:
        super().__init__(model="fake")
        self._text = text
        self._raise = raise_exc
        self.calls: list[dict] = []

    def _do_request(self, *, system_instruction, user_text, temperature, json_mode):
        self.calls.append({"temperature": temperature, "json_mode": json_mode,
                           "user_text": user_text, "system": system_instruction})
        if self._raise is not None:
            raise self._raise
        return LLMResponse(text=self._text)


_BOARD_HTML = """<html><head><title>Forum Latest</title></head><body>
<ul><li><a href="/t/topic-one/1">Topic One</a></li>
<li><a href="/t/topic-two/2">Topic Two</a></li>
<li><a href="/t/topic-three/3">Topic Three</a></li></ul></body></html>"""

_ARTICLE_HTML = """<html><head><title>A Single Post</title></head><body>
<article><h1>A Single Post</h1><p>""" + ("본문 내용이 길게 이어진다. " * 80) + "</p></article></body></html>"


def _digest_with_html(html: str, *, source: bool = True) -> dict:
    """list_html.source(raw 파일) 가진 digest. source=False 면 cleaned html 만."""
    d: dict = {"list_candidates": {}, "feed_candidates": []}
    if source:
        f = Path(tempfile.mkdtemp()) / "list.html"
        f.write_text(html, encoding="utf-8")
        d["list_html"] = {"source": str(f), "html": ""}
    else:
        d["list_html"] = {"html": html}
    return d


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # 1. board → fake 가 index 반환, source 파일에서 읽기 OK
    fc = _FakeClient('{"class":"index","confidence":0.92,"reason":"목록"}')
    r = classify_index_content(url="https://x.org/latest", digest=_digest_with_html(_BOARD_HTML), client=fc)
    cases.append(("board_index", r["class"] == "index" and r["confidence"] == 0.92,
                  f"got {r}"))

    # 2. content 반환 파싱
    fc = _FakeClient('{"class":"content","confidence":0.8,"reason":"단일글"}')
    r = classify_index_content(url="https://x.org/post/1", digest=_digest_with_html(_ARTICLE_HTML), client=fc)
    cases.append(("content_parse", r["class"] == "content", f"got {r}"))

    # 2b. not_found / login 4-class 파싱 (ADR 0007 §확장)
    fc = _FakeClient('{"class":"not_found","confidence":0.85,"reason":"없는 페이지"}')
    r = classify_index_content(url="https://x.org/x", digest=_digest_with_html(_ARTICLE_HTML), client=fc)
    cases.append(("not_found_parse", r["class"] == "not_found" and r["confidence"] == 0.85, f"got {r}"))
    fc = _FakeClient('{"class":"login","confidence":0.9,"reason":"로그인 게이트"}')
    r = classify_index_content(url="https://x.org/x", digest=_digest_with_html(_ARTICLE_HTML), client=fc)
    cases.append(("login_parse", r["class"] == "login", f"got {r}"))
    # 미지원 class 는 '?' 로 (어휘 밖)
    fc = _FakeClient('{"class":"paywall","confidence":0.9,"reason":"x"}')
    r = classify_index_content(url="https://x.org/x", digest=_digest_with_html(_ARTICLE_HTML), client=fc)
    cases.append(("unknown_class_to_qmark", r["class"] == "?", f"got {r}"))

    # 3. temperature=0 + json_mode 전달 확인
    fc = _FakeClient()
    classify_index_content(url="https://x.org/latest", digest=_digest_with_html(_BOARD_HTML), client=fc)
    call = fc.calls[0] if fc.calls else {}
    cases.append(("temperature_zero", call.get("temperature") == 0.0 and call.get("json_mode") is True,
                  f"call={call.get('temperature')},{call.get('json_mode')}"))

    # 4. prompt 에 URL·struct·body 슬롯 포함
    fc = _FakeClient()
    classify_index_content(url="https://x.org/latest", digest=_digest_with_html(_BOARD_HTML), client=fc)
    ut = fc.calls[0]["user_text"]
    cases.append(("prompt_slots", "https://x.org/latest" in ut and "구조 신호" in ut and "본문 추출" in ut,
                  f"ut head={ut[:60]!r}"))

    # 5. garbage 응답 → class '?'
    fc = _FakeClient("not json at all")
    r = classify_index_content(url="https://x.org/latest", digest=_digest_with_html(_BOARD_HTML), client=fc)
    cases.append(("parse_fail_unknown", r["class"] == "?", f"got {r}"))

    # 6. LLM 예외 → retry 후 '?' (fail-safe)
    fc = _FakeClient(raise_exc=LLMQuotaError("quota"))
    r = classify_index_content(url="https://x.org/latest", digest=_digest_with_html(_BOARD_HTML), client=fc)
    cases.append(("llm_fail_unknown", r["class"] == "?", f"got {r}"))
    cases.append(("llm_fail_retried", len(fc.calls) == classify_mod._RETRY,
                  f"calls={len(fc.calls)} expect={classify_mod._RETRY}"))

    # 7. list_html 부재 → client 호출 없이 '?'
    fc = _FakeClient()
    r = classify_index_content(url="https://x.org/latest", digest={"list_html": {}}, client=fc)
    cases.append(("no_html_no_call", r["class"] == "?" and len(fc.calls) == 0,
                  f"got {r} calls={len(fc.calls)}"))

    # 8. cleaned html fallback (source 없음) 도 동작
    fc = _FakeClient('{"class":"index","confidence":0.7,"reason":"r"}')
    r = classify_index_content(url="https://x.org/latest",
                               digest=_digest_with_html(_BOARD_HTML, source=False), client=fc)
    cases.append(("cleaned_fallback", r["class"] == "index" and len(fc.calls) == 1, f"got {r}"))

    # 9. struct hint — same-host 반복 행 있으면 언급, 없으면 SPA
    d_rows = {"list_candidates": {"html_repeating_patterns": [
        {"child_count": 9, "href_pattern_guess": "https://x.org/t/{n}"}]}, "feed_candidates": [1, 2]}
    h = _struct_hint(d_rows, "https://x.org/latest")
    cases.append(("struct_rows", "반복 글-링크 행" in h and "피드 2건" in h, f"h={h}"))
    h2 = _struct_hint({"list_candidates": {}}, "https://x.org/latest")
    cases.append(("struct_spa", "SPA" in h2, f"h2={h2}"))

    # 10. register veto override 임계 (_veto_override / _classify_veto memoize / gate_only)
    import importlib.util
    rp = Path(__file__).resolve().parent.parent.parent / "scripts" / "register.py"
    spec = importlib.util.spec_from_file_location("reg_under_test", rp)
    reg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reg)

    cases.append(("override_index_high", reg._veto_override({"class": "index", "confidence": 0.9}) is True, ""))
    cases.append(("override_index_low", reg._veto_override({"class": "index", "confidence": 0.3}) is False, ""))
    cases.append(("override_content", reg._veto_override({"class": "content", "confidence": 0.9}) is False, ""))
    cases.append(("override_none", reg._veto_override(None) is False, ""))
    cases.append(("override_unknown", reg._veto_override({"class": "?", "confidence": 0.0}) is False, ""))

    # _classify_decisive_rc: content→3 / not_found→4 / login→2 (모두 ≥0.7), index/?/저신뢰 → None
    cases.append(("decisive_content", reg._classify_decisive_rc({"class": "content", "confidence": 0.8}) == 3, ""))
    cases.append(("decisive_not_found", reg._classify_decisive_rc({"class": "not_found", "confidence": 0.8}) == 4, ""))
    cases.append(("decisive_login", reg._classify_decisive_rc({"class": "login", "confidence": 0.8}) == 2, ""))
    cases.append(("decisive_index_none", reg._classify_decisive_rc({"class": "index", "confidence": 0.99}) is None, ""))
    cases.append(("decisive_low_conf_none", reg._classify_decisive_rc({"class": "content", "confidence": 0.6}) is None, ""))
    cases.append(("decisive_unknown_none", reg._classify_decisive_rc({"class": "?", "confidence": 0.0}) is None, ""))
    cases.append(("decisive_nil_none", reg._classify_decisive_rc(None) is None, ""))

    # gate_only=True → 분류 skip (None)
    cases.append(("gate_only_skip", reg._classify_veto({}, "u", "s", True) is None, ""))

    # memoize: classify_index_content 1회만 — monkeypatch
    calln = {"n": 0}
    def _fake_classify(*, url, digest, slug=None):
        calln["n"] += 1
        return {"class": "index", "confidence": 0.9, "reason": "x"}
    orig = classify_mod.classify_index_content
    classify_mod.classify_index_content = _fake_classify
    try:
        dd: dict = {}
        reg._classify_veto(dd, "u", "s", False)
        reg._classify_veto(dd, "u", "s", False)  # 같은 (slug,url) → 캐시
    finally:
        classify_mod.classify_index_content = orig
    cases.append(("memoize_one_call", calln["n"] == 1, f"calls={calln['n']}"))

    # 11. _gate_reject_or_veto: override → None(거부취소), 마커 미생성
    saved: list = []
    orig_save = reg._save_rejected
    reg._save_rejected = lambda *a, **k: saved.append((a, k))
    classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "index", "confidence": 0.95, "reason": "board"}
    try:
        out = reg._gate_reject_or_veto({}, "u", "s", False, reason="rsn", note="gate: x", learn=False)
        cases.append(("veto_override_proceeds", out is None and len(saved) == 0, f"out={out} saved={len(saved)}"))
        # content → reject(3), 마커 1회 + learn=False 보존
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "content", "confidence": 0.9, "reason": "art"}
        saved.clear()
        out2 = reg._gate_reject_or_veto({}, "u2", "s2", False, reason="rsn", note="gate: x", learn=False)
        ok = out2 == 3 and len(saved) == 1 and saved[0][1].get("learn") is False
        cases.append(("veto_content_rejects", ok, f"out={out2} saved={saved}"))
        # gate_only → reject(3), 마커에 skip 표기, classify 호출 안 함
        saved.clear()
        out3 = reg._gate_reject_or_veto({}, "u3", "s3", True, reason="rsn", note="gate: x", learn=False)
        cases.append(("gate_only_rejects", out3 == 3 and len(saved) == 1, f"out={out3} saved={len(saved)}"))

        # 12. accept-path content-reject (ADR 0007 대칭) — 게이트 통과 후 분류기 content 고신뢰 → 거부
        saved.clear()
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "content", "confidence": 0.9, "reason": "단일글"}
        out_a = reg._accept_path_content_reject({}, "ua", "sa", False)
        cases.append(("accept_reject_content_high", out_a == 3 and len(saved) == 1 and saved[0][1].get("learn") is False,
                      f"out={out_a} saved={len(saved)}"))
        # content 저신뢰(< 0.7) → 수락 유지 (None, 마커 X)
        saved.clear()
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "content", "confidence": 0.6, "reason": "약함"}
        out_b = reg._accept_path_content_reject({}, "ub", "sb", False)
        cases.append(("accept_keep_content_low", out_b is None and len(saved) == 0, f"out={out_b}"))
        # index → 수락 (None)
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "index", "confidence": 0.95, "reason": "board"}
        cases.append(("accept_keep_index", reg._accept_path_content_reject({}, "uc", "sc", False) is None, ""))
        # '?' → 수락 (fail-safe, recall 우선)
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "?", "confidence": 0.0, "reason": "x"}
        cases.append(("accept_keep_unknown", reg._accept_path_content_reject({}, "ud", "sd", False) is None, ""))
        # gate_only → classify skip → 수락 (None, cheap 모드 보존)
        saved.clear()
        cases.append(("accept_gate_only_skip", reg._accept_path_content_reject({}, "ue", "se", True) is None and len(saved) == 0, ""))

        # accept-path multi-class (ADR 0007 §확장): not_found→rc4, login→rc2 (learn=False, note 클래스별)
        saved.clear()
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "not_found", "confidence": 0.85, "reason": "없음"}
        out_nf = reg._accept_path_content_reject({}, "unf", "snf", False)
        cases.append(("accept_reject_not_found", out_nf == 4 and len(saved) == 1
                      and saved[0][1].get("note") == "classifier: accept_path_not_found"
                      and saved[0][1].get("learn") is False, f"out={out_nf} saved={saved}"))
        saved.clear()
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "login", "confidence": 0.9, "reason": "로그인"}
        out_lg = reg._accept_path_content_reject({}, "ulg", "slg", False)
        cases.append(("accept_reject_login", out_lg == 2 and len(saved) == 1
                      and saved[0][1].get("note") == "classifier: accept_path_login", f"out={out_lg} saved={saved}"))

        # gate reclassify (ADR 0007 §확장): 게이트 거부를 분류기가 login/not_found 로 재분류 → rc 바뀜
        saved.clear()
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "not_found", "confidence": 0.85, "reason": "없음"}
        out_gnf = reg._gate_reject_or_veto({}, "ug", "sg", False, reason="rsn", note="gate: x", learn=False)
        cases.append(("gate_reclassify_not_found", out_gnf == 4 and len(saved) == 1, f"out={out_gnf} saved={len(saved)}"))
        saved.clear()
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "login", "confidence": 0.9, "reason": "로그인"}
        out_glg = reg._gate_reject_or_veto({}, "ug2", "sg2", False, reason="rsn", note="gate: x", learn=False)
        cases.append(("gate_reclassify_login", out_glg == 2 and len(saved) == 1, f"out={out_glg} saved={len(saved)}"))
        # content 재분류는 게이트 rc(3)와 동일 → 공통 경로 유지
        saved.clear()
        classify_mod.classify_index_content = lambda *, url, digest, slug=None: {"class": "content", "confidence": 0.9, "reason": "글"}
        out_gct = reg._gate_reject_or_veto({}, "ug3", "sg3", False, reason="rsn", note="gate: x", learn=False)
        cases.append(("gate_content_stays_3", out_gct == 3 and len(saved) == 1, f"out={out_gct}"))
    finally:
        reg._save_rejected = orig_save
        classify_mod.classify_index_content = orig

    return cases


if __name__ == "__main__":
    results = run()
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    failed = [r for r in results if not r[1]]
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
