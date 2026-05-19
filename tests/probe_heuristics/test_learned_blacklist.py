"""learned_blacklist — 자동 학습/회수 + url_gate 통합 회귀 테스트.

대상:
  - scripts/register.py: _extract_url_pattern, _pattern_id, _learn_pattern,
                          _unlearn_pattern_if_match, _clear_learned_by_id
  - bot/url_gate.py:    _normalize_groups path_prefix 검증,
                          _path_matches_prefix, _load_blacklist 가 config + learned merge,
                          _check_policy 의 host_suffix + path_prefix AND 매치
  - 통합: register 가 박은 패턴 → url_gate 가 즉시 mtime reload → 거부 메시지

LEARNED_PATH 는 임시 디렉토리로 redirect (실제 output/learned_blacklist.json 안 건드림).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


# coverage check 통과용 가상 식별자 — 실제 @heuristic 함수 매핑 X.
covers = ["learned_blacklist_register", "learned_blacklist_urlgate"]


def _redirect_paths(tmp_dir: Path) -> tuple[Path, dict]:
    """register.LEARNED_PATH, register.STATE_DIR, url_gate._LEARNED_PATH 를 tmp 로 redirect.
    원본 값을 dict 으로 돌려줘서 cleanup 에 사용. STATE_DIR redirect 가 빠지면 _save_failed
    호출이 실제 output/poll_state/ 에 .FAILED.json 박아 오염 — 반드시 redirect."""
    from scripts import register
    from bot import url_gate
    learned_tmp = tmp_dir / "learned_blacklist.json"
    state_tmp = tmp_dir / "poll_state"
    state_tmp.mkdir(parents=True, exist_ok=True)
    saved = {
        "register_learned": register.LEARNED_PATH,
        "register_state": register.STATE_DIR,
        "url_gate_learned": url_gate._LEARNED_PATH,
        "cache": url_gate._blacklist_cache,
    }
    register.LEARNED_PATH = learned_tmp
    register.STATE_DIR = state_tmp
    url_gate._LEARNED_PATH = learned_tmp
    url_gate._blacklist_cache = None
    return learned_tmp, saved


def _restore_paths(saved: dict) -> None:
    from scripts import register
    from bot import url_gate
    register.LEARNED_PATH = saved["register_learned"]
    register.STATE_DIR = saved["register_state"]
    url_gate._LEARNED_PATH = saved["url_gate_learned"]
    url_gate._blacklist_cache = saved["cache"]


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # ----- register helper unit ----- #
    from scripts.register import _extract_url_pattern, _pattern_id

    # 1. _extract_url_pattern — 다양한 URL 형태
    cases.append(("extract_google_search",
                  _extract_url_pattern("https://www.google.com/search?q=대나무") == ("www.google.com", "/search"),
                  ""))
    cases.append(("extract_scholar",
                  _extract_url_pattern("https://scholar.google.com/scholar?q=foo") == ("scholar.google.com", "/scholar"),
                  ""))
    cases.append(("extract_root_path",
                  _extract_url_pattern("https://example.com/") == ("example.com", ""),
                  ""))
    cases.append(("extract_no_path",
                  _extract_url_pattern("https://example.com") == ("example.com", ""),
                  ""))
    cases.append(("extract_deep_path",
                  _extract_url_pattern("https://cse.skku.edu/cse/notice.do") == ("cse.skku.edu", "/cse"),
                  ""))
    cases.append(("extract_uppercase_host",
                  _extract_url_pattern("https://EXAMPLE.COM/Foo") == ("example.com", "/Foo"),
                  "host 는 소문자, path 의 첫 segment 는 case 보존"))
    cases.append(("extract_invalid_none",
                  _extract_url_pattern("not a url") is None,
                  ""))

    # 2. _pattern_id — 결정성
    id1 = _pattern_id("www.google.com", "/search")
    id2 = _pattern_id("www.google.com", "/search")
    id3 = _pattern_id("www.google.com", "/forms")
    cases.append(("pattern_id_deterministic", id1 == id2 and len(id1) == 12, f"id1={id1} id2={id2}"))
    cases.append(("pattern_id_differs_by_path", id1 != id3, f"{id1} vs {id3}"))

    # ----- learn / unlearn (tmp 디렉토리) ----- #
    with tempfile.TemporaryDirectory(prefix="test_learned_") as td:
        tmp_dir = Path(td)
        learned_path, saved = _redirect_paths(tmp_dir)
        try:
            from scripts.register import (_learn_pattern, _unlearn_pattern_if_match,
                                          _list_learned, _clear_learned_by_id)

            # 3. _learn_pattern — 새 entry
            e1 = _learn_pattern("https://www.google.com/search?q=A", "rc=3 거부", slug="host_A")
            ok = (e1 is not None and e1["host_suffix"] == "www.google.com"
                  and e1["path_prefix"] == "/search" and e1["reject_count"] == 1)
            cases.append(("learn_new_entry", ok, f"e1={e1}"))

            # 4. _learn_pattern — 같은 패턴 → count 증가, last_* 갱신
            e2 = _learn_pattern("https://www.google.com/search?q=B", "rc=3 거부 다시", slug="host_B")
            ok = (e2 is not None and e2["id"] == e1["id"]
                  and e2["reject_count"] == 2 and e2["last_slug"] == "host_B")
            cases.append(("learn_same_pattern_increments", ok, f"e2={e2}"))

            # 5. _learn_pattern — 다른 path → 별 entry
            e3 = _learn_pattern("https://www.google.com/forms/d/123", "다른 거부", slug="host_F")
            ok = (e3 is not None and e3["id"] != e1["id"]
                  and e3["path_prefix"] == "/forms" and e3["reject_count"] == 1)
            cases.append(("learn_diff_path_new_entry", ok, f"e3={e3}"))

            # 6. 파일 atomic write — 실제 파일이 있어야 함, json 파싱 가능
            ok = learned_path.exists()
            if ok:
                try:
                    data = json.loads(learned_path.read_text(encoding="utf-8"))
                    ok = (data.get("version") == 1
                          and isinstance(data.get("patterns"), list)
                          and len(data["patterns"]) == 2)
                except Exception as e:
                    ok = False
                    cases.append(("atomic_write_json_valid", False, f"parse err: {e}"))
                else:
                    cases.append(("atomic_write_json_valid", ok, f"patterns={len(data['patterns'])}"))
            else:
                cases.append(("atomic_write_json_valid", False, "file missing"))

            # 7. _list_learned
            patterns = _list_learned()
            cases.append(("list_learned_count", len(patterns) == 2, f"got {len(patterns)}"))

            # 8. _unlearn_pattern_if_match — 정확 매치 → 제거
            removed = _unlearn_pattern_if_match("https://www.google.com/search?q=anything")
            cases.append(("unlearn_match_removes", removed == [e1["id"]], f"removed={removed}"))
            cases.append(("unlearn_remaining_count", len(_list_learned()) == 1, ""))

            # 9. _unlearn_pattern_if_match — 다른 path → 안 건드림
            removed2 = _unlearn_pattern_if_match("https://www.google.com/groups")  # 학습 안 된 path
            cases.append(("unlearn_no_match", removed2 == [], f"got {removed2}"))
            cases.append(("unlearn_remaining_intact", len(_list_learned()) == 1, ""))

            # 10. _clear_learned_by_id
            cases.append(("clear_by_id_present", _clear_learned_by_id(e3["id"]) is True, ""))
            cases.append(("clear_by_id_empties", len(_list_learned()) == 0, ""))
            cases.append(("clear_by_id_absent", _clear_learned_by_id("zzzzzzzzzzzz") is False, ""))

            # 10b. _save_failed 학습 hook — **2026-05-20 (4) 결정: _save_failed 자동 학습 X**.
            # gen_fail 은 board-specific (그 board 의 LLM 추출 실패). 같은 host 의 다른 board 영향 X.
            # STATE_DIR 도 redirect 됐으니 .FAILED.json 은 tmp 안에 박힘 (실제 poll_state 오염 X).
            from scripts.register import _save_failed
            _save_failed("host_test_failpath", "https://example-fail.com/board/list?p=1",
                         reason="gemini 생성+검증 3회 실패 (sim)",
                         last_config=None, last_feedback="[FAIL] posts_nonempty: 0건")
            patterns = _list_learned()
            ok = not any(p.get("host_suffix") == "example-fail.com" for p in patterns)
            cases.append(("save_failed_does_not_learn", ok,
                          f"after _save_failed, patterns={[(p['host_suffix'], p['path_prefix']) for p in patterns]}"))
            # cleanup learned (STATE_DIR 의 .FAILED.json 은 tmp 안이라 TemporaryDirectory 가 자동 정리)
            for p in _list_learned():
                _clear_learned_by_id(p["id"])

            # 10c. _save_rejected default (learn=False) — board-specific 거부 (board_shape /
            # nav_only 등 다수 경로 default). 학습 X.
            from scripts.register import _save_rejected
            _save_rejected("host_test_reject_default", "https://example-reject.com/board/12",
                           reason="board_shape_check 거부 (게시판 형식 아님)",
                           note="default learn=False")
            patterns = _list_learned()
            ok = not any(p.get("host_suffix") == "example-reject.com" for p in patterns)
            cases.append(("save_rejected_default_no_learn", ok,
                          f"patterns={[(p['host_suffix'], p['path_prefix']) for p in patterns]}"))
            for p in _list_learned():
                _clear_learned_by_id(p["id"])

            # 10c2. policy reject scope helper — target_not_found 만 url-specific.
            from scripts.register import _policy_reject_is_host_wide
            cases.append(("policy_scope_login_host_wide",
                          _policy_reject_is_host_wide("login_required") is True, ""))
            cases.append(("policy_scope_blocked_host_wide",
                          _policy_reject_is_host_wide("blocked_bot") is True, ""))
            cases.append(("policy_scope_cert_dns_host_wide",
                          _policy_reject_is_host_wide("cert_or_dns_broken") is True, ""))
            cases.append(("policy_scope_target_not_found_url_specific",
                          _policy_reject_is_host_wide("target_not_found") is False,
                          "URL 의 글이 사라졌을 뿐 — 같은 host 의 다른 URL 은 정상"))
            cases.append(("policy_scope_empty_verdict_host_wide",
                          _policy_reject_is_host_wide("") is True,
                          "verdict 비어있으면 보수적으로 host-wide (BLOCKED fallback path)"))

            # 10d. _save_rejected learn=True opt-in — host-wide reject (policy_check rc=2).
            # 학습 박혀 url_gate stage 2 에서 같은 host+path_prefix 차단.
            _save_rejected("host_test_policy_blocked", "https://example-blocked.com/board/99",
                           reason="policy_check 거부: LOGIN_REQUIRED",
                           note="host-wide login req",
                           learn=True)
            patterns = _list_learned()
            ok = any(p.get("host_suffix") == "example-blocked.com" and p.get("path_prefix") == "/board"
                     for p in patterns)
            cases.append(("save_rejected_learn_true_learns", ok,
                          f"patterns={[(p['host_suffix'], p['path_prefix']) for p in patterns]}"))
            for p in _list_learned():
                _clear_learned_by_id(p["id"])

            # ----- url_gate 통합 ----- #
            from bot import url_gate
            from bot.url_gate import (_normalize_groups, _path_matches_prefix,
                                       _load_blacklist, _check_policy, UrlRejected)

            # 11. _path_matches_prefix
            cases.append(("prefix_exact", _path_matches_prefix("/search", ("/search",)) is True, ""))
            cases.append(("prefix_subpath", _path_matches_prefix("/search/foo", ("/search",)) is True, ""))
            cases.append(("prefix_diff", _path_matches_prefix("/forms", ("/search",)) is False, ""))
            cases.append(("prefix_root", _path_matches_prefix("/", ("/search",)) is False, ""))

            # 12. _normalize_groups — path_prefix 검증
            try:
                gs = _normalize_groups([{"name": "g1", "message": "m", "path_prefix": ["search"]}], "t")
                # 'search' 가 '/search' 로 정규화돼야 함
                ok = gs[0]["path_prefix"] == ("/search",)
                cases.append(("normalize_path_prefix_adds_slash", ok, f"got {gs[0]['path_prefix']}"))
            except Exception as e:
                cases.append(("normalize_path_prefix_adds_slash", False, f"raised: {e}"))

            try:
                _normalize_groups([{"name": "g2", "message": "m"}], "t")
                cases.append(("normalize_empty_group_raises", False, "should have raised"))
            except ValueError:
                cases.append(("normalize_empty_group_raises", True, ""))

            # 13. _load_blacklist — learned merge.
            #     박은 패턴이 url_gate 에 즉시 보여야 함 (mtime reload).
            _learn_pattern("https://www.google.com/search?q=AGAIN", "rc=3 다시", slug="host_X")
            url_gate._blacklist_cache = None  # 캐시 강제 invalidate (실 운영에선 mtime 자동)
            groups, status = _load_blacklist()
            cases.append(("merge_loads_learned",
                          any(g["name"] == "learned_rejected" for g in groups),
                          f"groups={[g['name'] for g in groups]}"))

            # 14. _check_policy — host+path AND 매치
            def _reject_check(u: str) -> str:
                try:
                    _check_policy(u, "url")
                    return ""
                except UrlRejected as e:
                    return e.reason

            cases.append(("policy_serp_rejected",
                          _reject_check("https://www.google.com/search?q=anything") == "learned_rejected",
                          ""))
            cases.append(("policy_serp_diff_query_also_rejected",
                          _reject_check("https://www.google.com/search?q=somethingelse") == "learned_rejected",
                          "검색어 바뀌어도 같은 패턴이라 거부됨 (사용자 의도)"))
            # 메시지에서 운영 디테일 (pattern_id / unlearn 안내) 가 빠졌는지 — 사용자엔 노이즈.
            try:
                _check_policy("https://www.google.com/search?q=msg_test", "url")
                cases.append(("policy_msg_no_admin_detail", False, "should have raised"))
            except UrlRejected as e:
                msg = e.msg
                no_admin = ("/admin unlearn" not in msg) and ("운영자가" not in msg)
                cases.append(("policy_msg_no_admin_detail", no_admin,
                              f"msg leaked admin detail: {msg[:200]}"))
            cases.append(("policy_same_host_diff_path_passes",
                          _reject_check("https://www.google.com/forms/d/123") == "",
                          "host 같지만 path 다르면 통과"))
            cases.append(("policy_diff_host_passes",
                          _reject_check("https://groups.google.com/forum/foo") == "",
                          "host 다르면 통과"))

            # 15. 자동 회수 (등록 성공 시) — _save_state 시뮬: _unlearn_pattern_if_match 직접 호출
            _unlearn_pattern_if_match("https://www.google.com/search?q=ANY")
            url_gate._blacklist_cache = None
            cases.append(("auto_unlearn_after_register_success",
                          _reject_check("https://www.google.com/search?q=anything") == "",
                          "register --config 가 호출되면 작동 증거 → 같은 패턴 자동 회수 → 이후 통과"))

            # ----- root-only matching (path_prefix='' learned) ----- #
            # 16. root URL 학습 (path_prefix='') → root path 만 차단, 카테고리 path 통과.
            # CNN/Reuters/NatGeo/Vimeo root 학습 같은 부작용 (호스트 전체 차단) 회귀 차단.
            _learn_pattern("https://cnn-test.example.com/", "register failed: root marketing",
                           slug="host_cnn_test_root")
            url_gate._blacklist_cache = None

            cases.append(("root_only_root_rejected",
                          _reject_check("https://cnn-test.example.com/") == "learned_rejected",
                          "root URL 차단"))
            cases.append(("root_only_no_slash_rejected",
                          _reject_check("https://cnn-test.example.com") == "learned_rejected",
                          "trailing slash 없는 root 도 차단"))
            cases.append(("root_only_category_passes",
                          _reject_check("https://cnn-test.example.com/world/") == "",
                          "카테고리 path 통과 (호스트 전체 차단 아님)"))
            cases.append(("root_only_subpath_passes",
                          _reject_check("https://cnn-test.example.com/business") == "",
                          "subpath 통과"))
            cases.append(("root_only_deep_path_passes",
                          _reject_check("https://cnn-test.example.com/world/2026/05/article-x") == "",
                          "깊은 path 통과"))

            # 17. 운영자 host_suffix only 룰 (`_DEFAULT_BLACKLIST` 의 youtube 등) — host 전체 차단 의도 보존.
            # 내장 룰엔 match_root_only flag 없음 → 동작 그대로.
            cases.append(("default_blacklist_host_wide_youtube_root",
                          _reject_check("https://www.youtube.com/") == "blocked_platform",
                          "운영자 host_suffix only 룰 — root 차단"))
            cases.append(("default_blacklist_host_wide_youtube_subpath",
                          _reject_check("https://www.youtube.com/channel/UC_xyz") == "blocked_platform",
                          "운영자 host_suffix only 룰 — subpath 도 차단 (host 전체)"))

            # 18. root learned + 다른 path learned 공존 — 각자 정확히 작동.
            _learn_pattern("https://multi-test.example.com/search?q=A",
                           "policy fail: search blocked", slug="host_multi_search")
            url_gate._blacklist_cache = None
            cases.append(("root_and_path_coexist_root_rejected",
                          _reject_check("https://cnn-test.example.com/") == "learned_rejected",
                          "root learned 그대로"))
            cases.append(("root_and_path_coexist_search_rejected",
                          _reject_check("https://multi-test.example.com/search?q=anything") == "learned_rejected",
                          "path-specific learned 그대로"))
            cases.append(("root_and_path_coexist_multi_root_passes",
                          _reject_check("https://multi-test.example.com/") == "",
                          "multi-test host root 는 학습 X → 통과 (path-specific 만 학습됐음)"))

            # ----- (4) 결정 sibling URL 회귀 — 가장 중요한 회귀 차단 ----- #
            # 19. arca-style 시나리오: 한 채널 fail → 같은 host 의 다른 채널 *통과*.
            # _save_failed (학습 X) 가 박혔으니 sibling URL gate 통과해야 함.
            _save_failed("host_arca_wuthering", "https://arca-test.example.com/b/wuthering",
                         reason="posts_nonempty 0건 (채널 없음)",
                         last_config=None, last_feedback="[FAIL] posts_nonempty")
            url_gate._blacklist_cache = None
            cases.append(("sibling_unaffected_after_save_failed",
                          _reject_check("https://arca-test.example.com/b/maplestory") == "",
                          "wuthering fail 해도 maplestory 통과 — (4) 결정 핵심"))
            # _save_rejected board-specific (default learn=False) 도 sibling 영향 X
            _save_rejected("host_arca_nonboard", "https://arca-test.example.com/b/nonexistent",
                           reason="board_shape_check 거부", note="default learn=False")
            url_gate._blacklist_cache = None
            cases.append(("sibling_unaffected_after_save_rejected_board_specific",
                          _reject_check("https://arca-test.example.com/b/proseka") == "",
                          "nonexistent 거부해도 proseka 통과 — board-specific"))
            # 정리
            for p in _list_learned():
                _clear_learned_by_id(p["id"])
            url_gate._blacklist_cache = None
        finally:
            _restore_paths(saved)

    return cases
