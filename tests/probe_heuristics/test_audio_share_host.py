"""Podcast RSS rows that point at audio share hosts should skip body extraction."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


covers = ["audio_share_host_detected"]


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import audio_share_host_detected, write_list_candidates

    cases: list[tuple[str, bool, str]] = []

    hit = audio_share_host_detected(
        base_url="https://feeds.transistor.fm/oxide-and-friends",
        first_article_url="https://share.transistor.fm/s/abc123",
        html_candidates=[],
    )
    cases.append(("transistor_share_host_detected",
                  bool(hit and hit.get("audio_share_host_detected") and hit.get("host") == "share.transistor.fm"),
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
                      bool(audio and audio.get("host") == "share.transistor.fm" and payload.get("body_empty_likely") is True),
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
                      bool(audio and audio.get("host") == "feeds.transistor.fm" and payload.get("body_empty_likely") is True),
                      f"got audio={audio!r} body_empty_likely={payload.get('body_empty_likely')!r}"))

    return cases
