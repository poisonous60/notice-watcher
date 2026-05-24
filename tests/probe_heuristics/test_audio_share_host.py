"""Podcast RSS rows that point at audio share hosts should skip body extraction."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


covers = ["audio_share_host_detected"]


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import audio_share_host_detected, write_list_candidates
    from scripts.register import _enforce_audio_share_config

    cases: list[tuple[str, bool, str]] = []

    def write_har(path: Path, url: str, content_type: str, body: str = "") -> None:
        path.write_text(json.dumps({
            "log": {"entries": [{
                "request": {"url": url},
                "response": {
                    "headers": [{"name": "content-type", "value": content_type}],
                    "content": {"mimeType": content_type, "text": body},
                },
            }]}
        }), encoding="utf-8")

    hit = audio_share_host_detected(
        base_url="https://feeds.transistor.fm/oxide-and-friends",
        first_article_url="https://share.transistor.fm/s/abc123",
        html_candidates=[],
    )
    cases.append(("transistor_share_host_detected",
                  bool(hit and hit.get("audio_share_host_detected") and hit.get("host") == "share.transistor.fm"
                       and hit.get("confidence") == "structural"),
                  f"got {hit!r}"))

    miss_same_host = audio_share_host_detected(
        base_url="https://oxide.computer/podcast/rss.xml",
        first_article_url="https://oxide.computer/podcast/episode-1",
        html_candidates=[],
    )
    cases.append(("same_host_not_detected", miss_same_host is None, f"got {miss_same_host!r}"))

    miss_blog = audio_share_host_detected(
        base_url="https://example.com/feed.xml",
        first_article_url="https://blog.example.net/posts/episode-1",
        html_candidates=[],
    )
    cases.append(("non_audio_external_host_not_detected", miss_blog is None, f"got {miss_blog!r}"))

    with tempfile.TemporaryDirectory(prefix="test_audio_share_structural_") as td:
        har_path = Path(td) / "traffic.har"
        write_har(har_path, "https://www.spreaker.com/episode/new-show--123", "audio/mpeg", "ID3")
        structural = audio_share_host_detected(
            base_url="https://example.com/podcast/rss.xml",
            first_article_url="https://www.spreaker.com/episode/new-show--123",
            html_candidates=[],
            har_path=har_path,
        )
        cases.append(("unknown_audio_host_detected_by_har_mime",
                      bool(structural and structural.get("host") == "www.spreaker.com"
                           and structural.get("confidence") == "structural"
                           and structural.get("evidence") == "har_content_type_audio"),
                      f"got {structural!r}"))

    with tempfile.TemporaryDirectory(prefix="test_audio_share_same_host_har_") as td:
        har_path = Path(td) / "traffic.har"
        write_har(har_path, "https://example.com/episodes/1.mp3", "audio/mpeg", "ID3")
        same_host_audio = audio_share_host_detected(
            base_url="https://example.com/podcast/rss.xml",
            first_article_url="https://example.com/episodes/1.mp3",
            html_candidates=[],
            har_path=har_path,
        )
        cases.append(("same_host_audio_not_detected", same_host_audio is None, f"got {same_host_audio!r}"))

    with tempfile.TemporaryDirectory(prefix="test_audio_share_host_") as td:
        out_dir = Path(td)
        write_list_candidates(
            out_dir,
            base_url="https://feeds.transistor.fm/oxide-and-friends",
            page_html="<rss><channel></channel></rss>",
            html_candidates=[],
            json_api_candidates=[],
            hydration_candidates=[],
            first_article_url="https://share.transistor.fm/s/abc123",
        )
        payload = json.loads((out_dir / "list_candidates.json").read_text(encoding="utf-8"))
        audio = payload.get("audio_share_host_detected")
        cases.append(("write_list_candidates_sets_audio_share_signal",
                      bool(audio and audio.get("host") == "share.transistor.fm"
                           and audio.get("confidence") == "structural"
                           and payload.get("body_empty_likely") is True),
                      f"got audio={audio!r} body_empty_likely={payload.get('body_empty_likely')!r}"))

    with tempfile.TemporaryDirectory(prefix="test_audio_share_feed_") as td:
        out_dir = Path(td)
        write_list_candidates(
            out_dir,
            base_url="https://oxide.computer/podcast/rss.xml",
            page_html='<html><head><link rel="alternate" type="application/rss+xml" href="https://feeds.transistor.fm/oxide-and-friends"></head></html>',
            html_candidates=[],
            json_api_candidates=[],
            hydration_candidates=[],
            first_article_url="https://oxide.computer/episodes/the-tale-of-reverso",
        )
        payload = json.loads((out_dir / "list_candidates.json").read_text(encoding="utf-8"))
        audio = payload.get("audio_share_host_detected")
        cases.append(("transistor_feed_host_sets_audio_share_signal",
                      bool(audio and audio.get("host") == "feeds.transistor.fm"
                           and audio.get("confidence") == "host_known"
                           and payload.get("body_empty_likely") is True),
                      f"got audio={audio!r} body_empty_likely={payload.get('body_empty_likely')!r}"))

    enforced = _enforce_audio_share_config(
        {"site": "example.com", "article": {"content": [{"selector": "main"}]}},
        {"list_candidates": {"audio_share_host_detected": {
            "audio_share_host_detected": True,
            "confidence": "structural",
            "host": "www.spreaker.com",
        }}},
    )
    cases.append(("register_enforces_structural_body_empty",
                  bool((enforced.get("article") or {}).get("body_empty_acceptable") is True
                       and (enforced.get("article") or {}).get("skip_status") == [200]
                       and (enforced.get("article") or {}).get("content") == [{"selector": "main"}]),
                  f"got {enforced!r}"))

    host_known = _enforce_audio_share_config(
        {"site": "example.com", "article": {}},
        {"list_candidates": {"audio_share_host_detected": {
            "audio_share_host_detected": True,
            "confidence": "host_known",
            "host": "feeds.transistor.fm",
        }}},
    )
    cases.append(("register_does_not_enforce_host_known",
                  not (host_known.get("article") or {}).get("body_empty_acceptable"),
                  f"got {host_known!r}"))

    return cases
