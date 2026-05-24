"""D-layer retry recipe simulation — real digest + manual attempt_history fixture.

generate_config_validated 의 schema/validate 단계를 우회하고, retry feedback inject path
(_select_retry_recipes → _apply_recipe_patch → _build_recipe_feedback_section → build_retry_prompt)
만 real probe digest 로 호출. recipe inject 작동 + prompt 안 박힌 위치 직접 확인.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from engine.digest import build_digest
from generate.generator import (
    _select_retry_recipes,
    _apply_recipe_patch,
    _build_recipe_feedback_section,
    _enrich_retry_feedback,
)
from generate.prompt import build_retry_prompt


def _simulate(slug: str, prev_cfg: dict, fail_history: list[list[str]], label: str,
              digest_fixup: dict | None = None) -> None:
    print(f"\n{'=' * 70}\n  SIMULATION: {label}\n  slug = {slug}\n{'=' * 70}")
    digest = build_digest(slug=slug)
    if digest_fixup:
        digest.update(digest_fixup)
        print(f"  [fixup] applied: {list(digest_fixup.keys())}")
    sk = digest.get("site_kind") or {}
    feeds = digest.get("feed_candidates") or []
    validated = [f for f in feeds if isinstance(f, dict) and f.get("validated")]
    print(f"  site_kind  = {sk}")
    print(f"  validated_feeds = {len(validated)}")
    print(f"  prev_cfg.strategy = {prev_cfg.get('strategy')!r}  row_selector = {(prev_cfg.get('list') or {}).get('row_selector')!r}")

    # attempt_history fixture — fail history 그대로 변환
    history = [
        {
            "n": i + 1,
            "strategy": prev_cfg.get("strategy"),
            "rows": (prev_cfg.get("list") or {}).get("row_selector"),
            "fails": fails,
            "fails_detail": [f"{f}: simulated" for f in fails],
        }
        for i, fails in enumerate(fail_history)
    ]

    # Step 1: recipe selection
    recipes = _select_retry_recipes(prev_cfg, digest, history)
    print(f"\n  → _select_retry_recipes = {recipes!r}")
    if not recipes:
        print("  ❌ recipe 매칭 안 됨 — applies_to 조건 또는 fail count <2")
        return

    # Step 2: patch
    patched = _apply_recipe_patch(prev_cfg, recipes, digest)
    print(f"  → _apply_recipe_patch ok: strategy={patched.get('strategy')!r}")
    new_pid = (patched.get("list") or {}).get("fields", {}).get("post_id")
    if new_pid:
        print(f"    list.fields.post_id = {json.dumps(new_pid, ensure_ascii=False)[:200]}")
    new_wait = (patched.get("list") or {}).get("wait_selector")
    if new_wait:
        print(f"    list.wait_selector = {new_wait!r}")

    # R-H3 — prev_cfg mutation 확인
    prev_pid = (prev_cfg.get("list") or {}).get("fields", {}).get("post_id")
    print(f"    prev_cfg.list.fields.post_id 보존? {prev_pid == [{'from': 'css', 'selector': 'guid', 'text': True}] if prev_pid else 'N/A'}")

    # Step 3: recipe text section
    section = _build_recipe_feedback_section(recipes, patched)
    print(f"\n  → recipe_section ({len(section)} chars):")
    for ln in section.splitlines()[:8]:
        print(f"    {ln}")

    # Step 4: full prompt build with starting_candidate
    feedback = _enrich_retry_feedback(None, prev_cfg, digest, history, recipe_section=section)
    prompt = build_retry_prompt(digest, prev_cfg, feedback, starting_candidate=patched)

    has_starting_block = "### 추천 수정 starting point (D-layer recipe" in prompt
    has_recipe_section = "### D-layer recipe 발동" in prompt
    print(f"\n  → prompt verification:")
    print(f"    starting_candidate block 박힘 = {has_starting_block}  {'✅' if has_starting_block else '❌'}")
    print(f"    recipe text section 박힘    = {has_recipe_section}  {'✅' if has_recipe_section else '❌'}")
    print(f"    total prompt chars = {len(prompt)}")

    # prev_config block 과 starting_candidate block 이 *별개* 인지 (R-H3)
    if has_starting_block:
        # prev_config 의 selector 가 그대로 보존되는지
        prev_in_prompt = json.dumps(prev_cfg, ensure_ascii=False)[:120]
        patched_in_prompt = json.dumps(patched.get("list", {}), ensure_ascii=False)[:120]
        # 둘 다 prompt 안에 있어야 (각자 다른 block)
        prev_sel = (prev_cfg.get("list") or {}).get("row_selector")
        patched_strat = patched.get("strategy")
        print(f"    prev_cfg row_selector {prev_sel!r} 있음? {prev_sel in prompt if prev_sel else 'N/A'}")
        print(f"    patched strategy {patched_strat!r} starting block 안에?", end=" ")
        idx = prompt.find("### 추천 수정 starting point (D-layer recipe")
        starting_text = prompt[idx:idx + 1500] if idx >= 0 else ""
        print(patched_strat in starting_text)

        # 첫 50 lines 의 starting block snippet
        print(f"\n  ── starting_candidate block snippet ──")
        for ln in starting_text.splitlines()[:25]:
            print(f"    {ln}")


def main() -> int:
    # === TAL — Recipe 1 target ===
    # prev_cfg = guid 박은 RSS cfg (실제 thisamericanlife 가 LLM 이 박은 패턴)
    tal_prev = {
        "version": 1,
        "site": "thisamericanlife.org",
        "board": "talpodcast",
        "strategy": "httpx_html",
        "list": {
            "url_template": "https://feeds.thisamericanlife.org/talpodcast",
            "row_selector": "channel > item",
            "fields": {
                "post_id": [{"from": "css", "selector": "guid", "text": True}],
                "title": [{"from": "css", "selector": "title", "text": True}],
                "url": [{"from": "css", "selector": "link", "text": True}],
            },
        },
        "article": {"body_empty_acceptable": True},
    }
    # post_id_unique 2회 반복 (guid 가 같은 거 여러 개)
    # digest_fixup: 옛 probe artifact 가 feed validate 안 했음 (validated=False).
    # 진짜 register flow 에선 site_kind=rss 로 분류됐을 것 (LLM 이 channel>item 박은 게 증거).
    # 시뮬레이션 목적상 site_kind 강제 박음.
    _simulate("host_feeds-thisameri_talpodcast_c725ed7a", tal_prev,
              [["post_id_unique"], ["post_id_unique"]],
              "TAL — Recipe 1 (post_id_unique 2x)",
              digest_fixup={"site_kind": {"kind": "rss", "confidence": "high",
                                          "evidence": ["fixup:simulated-validated-feed"],
                                          "primary_feed_url": "https://feeds.thisamericanlife.org/talpodcast"}})

    # === Radiolab — Recipe 2 target ===
    rl_prev = {
        "version": 1,
        "site": "radiolab.org",
        "board": "podcast",
        "strategy": "httpx_html",
        "list": {
            "url_template": "https://radiolab.org/podcast",
            "row_selector": "div.col-12.mb-6",
            "fields": {
                "post_id": [{"from": "css", "selector": "a", "attr": "href"}],
                "title": [{"from": "css", "selector": "h2", "text": True}],
                "url": [{"from": "css", "selector": "a", "attr": "href"}],
            },
        },
        "article": {"body_empty_acceptable": True},
    }
    _simulate("host_radiolab-org_podcast_0080db5b", rl_prev,
              [["posts_nonempty"], ["title_nonempty"]],
              "Radiolab — Recipe 2 (posts_nonempty + title_nonempty)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
