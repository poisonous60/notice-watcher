"""Public status site agentic-packet regression tests."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts import generate_site as site  # noqa: E402


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    detail = {
        "slug": "host_example-com_news_1234abcd",
        "host_label": "example.com",
        "path_label": "/news",
        "probe_url": "https://example.com/news/",
        "har_mtime": "2026-05-28T00:00:00+09:00",
        "verdict": "정적 HTTP로 충분",
        "probe_host": "https://example.com/news/",
        "article_host": "https://example.com/news/1",
        "config_strategy": "httpx_html",
        "summary": {
            "entry_count": 12,
            "json_count": 3,
            "xhr_count": 2,
            "status_error_count": 0,
            "content_types": [("application/json", 3)],
        },
        "sections": [
            {
                "key": "traffic_api_candidates",
                "total_rows": 2,
                "rows": [{
                    "key": "https://example.com/api/news",
                    "kind": "List JSON API",
                    "count": 2,
                    "type": "api",
                    "badge": "List JSON API",
                    "badge_class": "sig-api",
                    "host": "https://example.com/api/news",
                    "meta": "score=7 · GET 200",
                    "evidence": "list_hits=2",
                }],
                "raw_redacted": [{"url": "https://example.com/api/news"}],
            },
            {
                "key": "traffic_article_body_candidates",
                "total_rows": 1,
                "raw_redacted": [{"url": "https://example.com/api/news/1"}],
            },
            {
                "key": "rss_feed_urls",
                "total_rows": 1,
                "raw_redacted": [{"url": "https://example.com/feed.xml"}],
            },
            {"key": "pagination_hints", "total_rows": 0, "raw_redacted": []},
            {
                "key": "digest",
                "total_rows": 1,
                "raw_redacted": {
                    "list_candidates": {
                        "first_article_url": "https://example.com/news/1",
                        "html_repeating_patterns": [
                            {"selector": "article.card", "sample_url": "https://example.com/news/1"}
                        ],
                    },
                    "list_html": {"source": "list.html", "html": "<article>Post</article>"},
                },
                # model_facing = digest AFTER the agent-feed compressor (the exact
                # bytes codex reads). The packet must surface THIS, not raw_redacted.
                "model_facing": {
                    "list_candidates": {
                        "first_article_url": "https://example.com/news/1",
                        "html_repeating_patterns": [
                            {"selector": "article.card", "sample_url": "https://example.com/news/1"}
                        ],
                    },
                    "list_html": {
                        "source": "list.html",
                        "html": "<article>Post</article><!-- collapsed 9 similar <article.card> -->",
                        "prompt_compressed": True,
                    },
                },
            },
        ],
        "artifact_list_candidates": {"rows": []},
    }

    with tempfile.TemporaryDirectory(prefix="site_agentic_packet_") as td:
        run_dir = Path(td)
        (run_dir / "diagnosis.json").write_text(
            json.dumps({"url": "https://example.com/news/"}), encoding="utf-8"
        )
        (run_dir / "list_candidates.json").write_text(
            json.dumps({"first_article_url": "https://example.com/news/1"}), encoding="utf-8"
        )
        (run_dir / "traffic.har").write_text(
            json.dumps({"log": {"entries": []}}), encoding="utf-8"
        )
        packet = site.build_agentic_packet(detail, run_dir=run_dir)
        files = {f["path"]: f for f in packet["files"]}
        artifacts = {a["path"] for a in packet["artifacts"]}
        html = site.render_agentic_packet_html({
            "panels": [{
                "panel_id": "har-panel-0",
                "agentic_panel_id": "agentic-panel-0",
                "host_label": "example.com",
                "manifest": {},
                "detail": {**detail, "agentic_packet": packet},
            }]
        })
        manifest = site._manifest_for(run_dir, detail["slug"])
        manifest_names = {name for name, _, _ in manifest["items"]}

    cases.append((
        "packet_lists_model_inputs",
        {"AGENTS.md", "stdin prompt", "digest.json", "failure_packet.json",
         "examples/manifest.json", "examples/*.json (×2)", "config_writer_rules.txt",
         "validator_digest.json", "validate_config.py + run_validator.*",
         "candidate.json + last.json"}.issubset(files),
        f"files={sorted(files)}",
    ))
    expected_groups = {
        "AGENTS.md": "direct",
        "stdin prompt": "direct",
        "digest.json": "direct",
        "examples/manifest.json": "direct",
        "examples/*.json (×2)": "on_demand",
        "config_writer_rules.txt": "on_demand",
        "failure_packet.json": "on_demand",
        "validator_digest.json": "tooling",
        "validate_config.py + run_validator.*": "tooling",
        "candidate.json + last.json": "tooling",
    }
    group_mismatches = {
        path: files[path].get("group")
        for path, want in expected_groups.items()
        if path in files and files[path].get("group") != want
    }
    cases.append((
        "packet_classifies_inputs_into_buckets",
        not group_mismatches,
        f"mismatches={group_mismatches}",
    ))
    cases.append((
        "digest_shows_model_facing_compressed_html",
        # The packet must surface the post-compressor digest (model_facing),
        # not the clean raw_redacted view. The collapse marker only exists there.
        "collapsed 9 similar" in files["digest.json"].get("raw", ""),
        files["digest.json"].get("raw", "")[:400],
    ))
    cases.append((
        "packet_includes_selected_probe_artifacts",
        {"output/probe/host_example-com_news_1234abcd/traffic.har",
         "output/probe/host_example-com_news_1234abcd/diagnosis.json",
         "output/probe/host_example-com_news_1234abcd/list_candidates.json"}.issubset(artifacts),
        f"artifacts={sorted(artifacts)}",
    ))
    cases.append((
        "packet_keeps_public_urls_and_selectors_visible",
        "https://example.com/news/1" in files["digest.json"]["preview"]
        and "article.card" in files["digest.json"]["preview"],
        files["digest.json"]["preview"][:400],
    ))
    cases.append((
        "render_explains_agentic_flow",
        "probeAgentPicker" in html
        and "probeAgentSearch" in html
        and "probeAgentOpenUrl" in html
        and "Model input packet" in html
        and "packet-input-table" in html
        and "data-tip-html" in html
        and "traffic_api_candidates[0]" in html
        and "https://example.com/api/news" in html
        and "<td>2</td>" in html
        and "candidate.json" in html
        and "open raw packet" in html
        and "probe-agent-panel-0" in html
        and "probeAgentPanelHost" in html
        and "data-panel-url=\"probe-panels/probe-agent-panel-0.html\"" in html
        and "har-signal-table" in html
        and "Published config summary" in html,
        html[:500],
    ))
    cases.append((
        "packet_input_col3_is_byte_size",
        # Col 3 of packet-input-table reports byte size for BOTH bands —
        # probe artifacts (stat size) and staged files (len(raw)). No bare
        # numbers, no "fields"/"count" — one unit so the column is comparable.
        "<th>size</th>" in (table := html.split("packet-input-table", 1)[-1].split("</table>", 1)[0])
        and " bytes</td>" in table
        and " fields</td>" not in table
        and "<th>count</th>" not in table,
        html[html.find("packet-input-table"):html.find("packet-input-table") + 600],
    ))
    cases.append((
        "packet_examples_show_real_picks_not_placeholder",
        # examples/manifest.json + examples/*.json must surface the ACTUAL
        # picked configs (reproduced via _pick_examples), not the old hardcoded
        # shape/stub. The placeholder slug, the manifest_shape key, and the
        # static "2 closest configs staged" stub note must all be gone.
        "<example-slug>" not in html
        and "manifest_shape" not in html
        and "the 2 closest successful configs are staged here" not in html
        and '"selection_rule": "top 2 scored configs excluding the current slug"' in packet["raw_text"],
        next((f["raw"] for f in packet["files"] if f["path"] == "examples/manifest.json"), "")[:400],
    ))
    cases.append((
        "packet_has_clickable_raw_text_bundle",
        "COMMAND" in packet["raw_text"]
        and "===== AGENTS.md =====" in packet["raw_text"]
        and "===== digest.json =====" in packet["raw_text"]
        and "https://example.com/news/1" in packet["raw_text"],
        packet["raw_text"][:500],
    ))
    cases.append((
        "detail_overlays_are_raw_only",
        "WHAT IT CONTAINS" not in html
        and "RAW / PREVIEW" not in html
        and "FIELD\n" not in html,
        html[:800],
    ))
    cases.append((
        "manifest_tracks_agentic_source_files",
        "__agentic__generate/codex_agentic.py" in manifest_names
        and "__agentic__prompts/register_agent_AGENTS.md" in manifest_names
        and "__agentic__prompts/config_writer.system.txt" in manifest_names,
        f"manifest={sorted(manifest_names)}",
    ))
    cases.append((
        "manifest_json_round_trips_for_cache_compare",
        json.loads(json.dumps(manifest)) == manifest,
        f"manifest={manifest}",
    ))
    return cases


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {'' if ok else d[:300]}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
