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
         "examples/manifest.json + examples/*.json", "config_writer_rules.txt",
         "validate_config.py + run_validator.*", "candidate.json + last.json"}.issubset(files),
        f"files={sorted(files)}",
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
        and "har-signal-table" in html
        and "Published config summary" in html,
        html[:500],
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
