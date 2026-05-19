"""engine.digest.build_digest 의 누락 휴리스틱 키 자동 보강 — 옛 artifact 호환.

대상:
  - engine/digest.py:_backfill_missing_heuristics — list_candidates 에 새 휴리스틱 키 없으면
    `probe/extract.py:<heuristic>` 재호출. digest 안에만 (artifact 파일 X).

미래 같은 자리 휴리스틱 추가 시: _backfill_missing_heuristics 에 한 줄 + 본 fixture 에 case 추가.

post-fix-cleanup 의 핵심 가정 = N100 의 옛 artifact 도 새 게이트로 잡힘. 이 보강이 그 자리.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


covers = ["digest_backfill_root_marketing_homepage"]


def _write_min_probe(out_dir: Path, list_cands: dict) -> None:
    """build_digest 호출에 필요한 최소 artifact set."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diagnosis.json").write_text(json.dumps({
        "slug": out_dir.name, "url": "https://example.test/",
        "verdict": "정적 HTTP로 충분", "recommended_strategy": "httpx",
        "recommended_headers": {}, "recommended_polling_interval_sec": 3600,
        "list_candidates_summary": "", "article_entry_ok": True,
        "notes": [], "results": [], "baseline": {},
    }), encoding="utf-8")
    (out_dir / "robots.json").write_text(json.dumps({
        "url": "https://example.test/robots.txt", "status": 200,
        "crawl_delay": None, "disallow": [], "sitemaps": [],
    }), encoding="utf-8")
    (out_dir / "list_candidates.json").write_text(
        json.dumps(list_cands), encoding="utf-8")


def run() -> list[tuple[str, bool, str]]:
    from engine.digest import build_digest

    cases: list[tuple[str, bool, str]] = []

    # 1. 옛 artifact (root_marketing_homepage 키 *없음*) → 보강 후 dict 가 박힘 (CNN-style).
    with tempfile.TemporaryDirectory(prefix="test_digest_backfill_") as td:
        out_dir = Path(td) / "host_test_cnn_style"
        # CNN-style: nav/header/dropdown 키워드 우세 + total_same_host=8.
        list_cands_old = {
            "first_article_url": "https://example.test/2026/05/article",
            "html_repeating_patterns": [
                {"selector": "ul.subnav__sections > li.subnav__section", "child_count": 21, "sample_url": None},
                {"selector": "div.header__nav-container > div.header__nav-item", "child_count": 16, "sample_url": None},
                {"selector": "div.header__nav-item-dropdown-inner > a", "child_count": 16, "sample_url": None},
                {"selector": "ul.container__field-links > li.card", "child_count": 25, "sample_url": None},
            ],
            "traffic_json_api_candidates": [],
            "hydration_list_candidates": [],
            "inline_js_data_candidates": [],
            "runtime_id_candidates": [],
            "row_external_host": None,
            "row_interactive_action": None,
            "body_empty_likely": False,
            "nav_only_same_host": {"base_host": "example.test", "total_same_host": 8,
                                    "in_nav": 5, "outside_nav": 3, "nav_only_same_host": False,
                                    "sample_nav_ancestors": ["nav"]},
            "article_meta_signals": None,
            # ⚠ root_marketing_homepage 키 없음 — 옛 artifact 시뮬
        }
        _write_min_probe(out_dir, list_cands_old)
        digest = build_digest(probe_dir=out_dir, url="https://example.test/")
        rm = (digest.get("list_candidates") or {}).get("root_marketing_homepage")
        ok = (isinstance(rm, dict) and rm.get("is_root_marketing_homepage") is True
              and rm.get("marketing_hits", 0) >= 2)
        cases.append(("backfill_root_marketing_old_artifact",
                      ok, f"got {rm!r}"))

        # artifact 파일은 *안 건드림* 확인 (root_marketing_homepage 키 디스크에 없어야)
        on_disk = json.loads((out_dir / "list_candidates.json").read_text(encoding="utf-8"))
        cases.append(("backfill_artifact_file_unchanged",
                      "root_marketing_homepage" not in on_disk,
                      f"on disk keys: {sorted(on_disk.keys())}"))

    # 2. 새 artifact (root_marketing_homepage 키 *이미 있음*) → 보강 안 건드림 (덮어쓰기 X).
    with tempfile.TemporaryDirectory(prefix="test_digest_backfill_") as td:
        out_dir = Path(td) / "host_test_already_set"
        list_cands_new = {
            "first_article_url": "https://example.test/2026/05/article",
            "html_repeating_patterns": [
                {"selector": "ul.subnav__sections > li.subnav__section", "child_count": 21, "sample_url": None},
                {"selector": "div.header__nav-container > div.header__nav-item", "child_count": 16, "sample_url": None},
            ],
            "traffic_json_api_candidates": [],
            "hydration_list_candidates": [],
            "inline_js_data_candidates": [],
            "runtime_id_candidates": [],
            "row_external_host": None,
            "row_interactive_action": None,
            "body_empty_likely": False,
            "nav_only_same_host": None,
            "article_meta_signals": None,
            "root_marketing_homepage": {"is_root_marketing_homepage": False,
                                          "preset_marker": "do_not_overwrite"},
        }
        _write_min_probe(out_dir, list_cands_new)
        digest = build_digest(probe_dir=out_dir, url="https://example.test/")
        rm = (digest.get("list_candidates") or {}).get("root_marketing_homepage")
        cases.append(("backfill_does_not_overwrite_existing",
                      isinstance(rm, dict) and rm.get("preset_marker") == "do_not_overwrite",
                      f"got {rm!r}"))

    # 3. 마케팅 키워드 부족 (root 아닌 board) → 보강 결과 = None.
    with tempfile.TemporaryDirectory(prefix="test_digest_backfill_") as td:
        out_dir = Path(td) / "host_test_plain_board"
        list_cands_plain = {
            "first_article_url": "https://example.test/posts/123",
            "html_repeating_patterns": [
                {"selector": "ul.posts > li.post", "child_count": 20, "sample_url": None},
                {"selector": "article.entry", "child_count": 10, "sample_url": None},
            ],
            "traffic_json_api_candidates": [],
            "hydration_list_candidates": [],
            "inline_js_data_candidates": [],
            "runtime_id_candidates": [],
            "row_external_host": None,
            "row_interactive_action": None,
            "body_empty_likely": False,
            "nav_only_same_host": None,
            "article_meta_signals": None,
            # root_marketing_homepage 키 없음
        }
        _write_min_probe(out_dir, list_cands_plain)
        digest = build_digest(probe_dir=out_dir, url="https://example.test/")
        rm = (digest.get("list_candidates") or {}).get("root_marketing_homepage")
        cases.append(("backfill_plain_board_returns_none",
                      rm is None, f"got {rm!r}"))

    return cases
