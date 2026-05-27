"""Dashboard view-model for inspecting probe HAR extraction."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from dashboard import state
from engine.digest import build_digest
from probe.paths import url_to_slug
from probe.extract import (
    audio_share_signal,
    pagination_hints,
    rss_feed_urls,
    traffic_api_candidates,
    traffic_article_body_candidates,
)

ROOT = Path(__file__).resolve().parent.parent
PROBE_DIR = ROOT / "output" / "probe"
PROBE_MODES = ("lite", "full")
RUN_KINDS = ("probe", "register_gate", "register")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _short(value: object, limit: int = 160) -> str:
    s = "" if value is None else str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def normalize_probe_mode(mode: str | None) -> str:
    return mode if mode in PROBE_MODES else "lite"


def normalize_run_kind(kind: str | None) -> str:
    return kind if kind in RUN_KINDS else "probe"


def is_probe_url(value: str) -> bool:
    try:
        sp = urlsplit((value or "").strip())
    except ValueError:
        return False
    return sp.scheme in {"http", "https"} and bool(sp.netloc)


def slug_for_url(url: str) -> str:
    return url_to_slug(url.strip())


def probe_command(url: str, *, mode: str) -> list[str]:
    cmd = [sys.executable, str(ROOT / "scripts" / "probe.py"), url.strip(), "--no-paid", "--no-crawl4ai"]
    if normalize_probe_mode(mode) == "lite":
        cmd.append("--lite")
    return cmd


def register_command(url: str, *, mode: str, gate_only: bool) -> list[str]:
    cmd = [sys.executable, str(ROOT / "scripts" / "register.py"), url.strip()]
    if normalize_probe_mode(mode) == "full":
        cmd.append("--full-probe")
    if gate_only:
        cmd.extend(["--reuse-probe", "--gate-only"])
    return cmd


def probe_env(*, force_har: bool) -> dict[str, str]:
    if not force_har:
        return {}
    return {"PROBE_STATIC_OK_SKIP_HEADLESS": "0"}


def _probe_dir(slug: str, *, probe_root: Path = PROBE_DIR) -> Optional[Path]:
    if not state.safe_slug(slug) or ".." in slug:
        return None
    path = (probe_root / slug).resolve()
    try:
        path.relative_to(probe_root.resolve())
    except ValueError:
        return None
    return path if path.is_dir() else None


def list_probe_runs(*, probe_root: Path = PROBE_DIR, q: str = "", limit: int = 300) -> list[dict[str, Any]]:
    if not probe_root.exists():
        return []
    query = (q or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for path in probe_root.iterdir():
        if not path.is_dir() or not state.safe_slug(path.name):
            continue
        h_paths = sorted(path.glob("traffic*.har"))
        diag = _read_json(path / "diagnosis.json")
        list_candidates = _read_json(path / "list_candidates.json")
        if not h_paths and not diag and not list_candidates:
            continue
        first_article_url = str(list_candidates.get("first_article_url") or "")
        haystack = "\n".join([
            path.name,
            str(diag.get("url") or ""),
            str(diag.get("verdict") or ""),
            str(diag.get("recommended_strategy") or ""),
            first_article_url,
        ]).lower()
        if query and query not in haystack:
            continue
        rows.append({
            "slug": path.name,
            "url": diag.get("url") or "",
            "verdict": diag.get("verdict") or "",
            "first_article_url": first_article_url,
            "har_count": len(h_paths),
            "has_har": bool(h_paths),
            "mtime": path.stat().st_mtime,
            "mtime_str": _mtime_str(path),
        })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[:limit]


def _mtime_str(path: Path) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def har_choices(slug: str, *, probe_root: Path = PROBE_DIR) -> list[str]:
    out_dir = _probe_dir(slug, probe_root=probe_root)
    if out_dir is None:
        return []
    return [p.name for p in sorted(out_dir.glob("traffic*.har"), key=_har_sort_key)]


def _har_sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.name == "traffic.har" else 1, path.name)


def build_har_detail(
    slug: str,
    har_name: str,
    *,
    probe_root: Path = PROBE_DIR,
) -> Optional[dict[str, Any]]:
    out_dir = _probe_dir(slug, probe_root=probe_root)
    if out_dir is None or "/" in har_name or "\\" in har_name or not har_name.endswith(".har"):
        return None
    har_path = out_dir / har_name
    if not har_path.exists():
        return None

    diagnosis = _read_json(out_dir / "diagnosis.json")
    list_candidates = _read_json(out_dir / "list_candidates.json")
    digest = _build_digest_safe(slug, base_url_hint=str(diagnosis.get("url") or ""), probe_root=probe_root)
    base_url = str(diagnosis.get("url") or "")
    first_article_url = str(list_candidates.get("first_article_url") or "")
    html_candidates = list_candidates.get("html_repeating_patterns") or []
    if not isinstance(html_candidates, list):
        html_candidates = []
    page_html = _read_page_html(out_dir, diagnosis)

    feeds = rss_feed_urls(html=page_html, base_url=base_url, har_path=har_path) if base_url else []
    page_hints = pagination_hints(html=page_html, base_url=base_url, har_path=har_path) if base_url else []
    audio = audio_share_signal(
        base_url=base_url,
        first_article_url=first_article_url or None,
        html_candidates=html_candidates,
        feeds=feeds,
        har_path=har_path,
    ) if base_url else None

    raw_api = traffic_api_candidates(har_path, page_url=base_url)
    raw_body = traffic_article_body_candidates(har_path, article_url=first_article_url)
    summary = _har_summary(har_path)

    return {
        "slug": slug,
        "out_dir": str(out_dir),
        "har_name": har_name,
        "har_path": str(har_path),
        "har_mtime": _mtime_str(har_path),
        "base_url": base_url,
        "first_article_url": first_article_url,
        "diagnosis_verdict": diagnosis.get("verdict") or "",
        "summary": summary,
        "choices": har_choices(slug, probe_root=probe_root),
        "sections": [
            {
                "key": "traffic_json_api_candidates",
                "title": "목록 JSON API 후보",
                "source": "traffic_api_candidates(har_path, page_url)",
                "items": [_api_row(c) for c in raw_api],
                "raw": raw_api,
            },
            {
                "key": "traffic_article_body_candidates",
                "title": "글 본문 JSON API 후보",
                "source": "traffic_article_body_candidates(har_path, article_url)",
                "items": [_body_row(c) for c in raw_body],
                "raw": raw_body,
            },
            {
                "key": "rss_feed_urls",
                "title": "RSS/Atom 후보",
                "source": "rss_feed_urls(html, base_url, har_path)",
                "items": [_simple_row(c, ["url", "source", "type"]) for c in feeds],
                "raw": feeds,
            },
            {
                "key": "pagination_hints",
                "title": "페이지네이션 후보",
                "source": "pagination_hints(html, base_url, har_path)",
                "items": [_simple_row(c, ["kind", "param", "source", "url_template", "evidence_url"]) for c in page_hints],
                "raw": page_hints,
            },
            {
                "key": "audio_share_host_detected",
                "title": "오디오 share/player host 신호",
                "source": "audio_share_signal(..., har_path)",
                "items": [_simple_row(audio, ["host", "base_host", "confidence", "evidence", "sample_url"])] if audio else [],
                "raw": audio,
            },
        ],
        "artifact_sections": _artifact_sections(list_candidates=list_candidates, digest=digest),
    }


def _build_digest_safe(slug: str, *, base_url_hint: str, probe_root: Path) -> dict[str, Any]:
    try:
        if probe_root == PROBE_DIR:
            return build_digest(slug=slug, url=base_url_hint or None)
        return build_digest(slug=slug, url=base_url_hint or None, probe_dir=probe_root / slug)
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}"}


def _artifact_sections(*, list_candidates: dict[str, Any], digest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "title": "저장된 probe 요약",
            "source": "list_candidates.json",
            "rows": _summary_rows(list_candidates),
            "raw": list_candidates,
        },
        {
            "title": "register digest 요약",
            "source": "engine.digest.build_digest(...)",
            "rows": _summary_rows(_digest_summary(digest)),
            "raw": _redact_digest_for_display(digest),
        },
    ]


def _summary_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(data):
        value = data.get(key)
        rows.append({
            "key": key,
            "kind": _kind(value),
            "count": _count(value),
            "preview": _preview(value),
        })
    return rows


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _count(value: Any) -> str:
    if isinstance(value, (list, dict, str)):
        return str(len(value))
    return ""


def _preview(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "[]"
        return _short(json.dumps(value[:2], ensure_ascii=False), 260)
    if isinstance(value, dict):
        if not value:
            return "{}"
        sample = {k: value[k] for k in list(value)[:6]}
        return _short(json.dumps(sample, ensure_ascii=False), 260)
    return _short(value, 260)


def _digest_summary(digest: dict[str, Any]) -> dict[str, Any]:
    if digest.get("_error"):
        return {"_error": digest.get("_error")}
    out: dict[str, Any] = {}
    for key in (
        "verdict",
        "recommended_strategy",
        "recommended_headers",
        "article_entry_ok",
        "notes",
        "entry_matrix",
        "static_ok_request_headers",
        "captured_headers",
        "list_candidates",
        "feed_candidates",
        "sitemap_candidates",
        "mdr_candidates",
        "sitemap_only_fit_signal",
        "site_kind",
    ):
        if key in digest:
            out[key] = digest.get(key)
    article = digest.get("article_sample")
    if isinstance(article, dict):
        out["article_sample"] = {
            k: v for k, v in article.items()
            if k not in {"html"}
        }
    list_html = digest.get("list_html")
    if isinstance(list_html, dict):
        out["list_html"] = {
            "source": list_html.get("source"),
            "truncated": list_html.get("truncated"),
            "html_bytes": len(str(list_html.get("html") or "").encode("utf-8")),
        }
    return out


def _redact_digest_for_display(digest: dict[str, Any]) -> dict[str, Any]:
    if digest.get("_error"):
        return digest
    out = dict(digest)
    for key in ("list_html", "article_sample"):
        section = out.get(key)
        if isinstance(section, dict) and "html" in section:
            section = dict(section)
            section["html"] = f"[omitted: {len(str(section.get('html') or '').encode('utf-8'))} bytes]"
            out[key] = section
    return out


def _read_page_html(out_dir: Path, diagnosis: dict[str, Any]) -> str:
    for result in diagnosis.get("results") or []:
        if not isinstance(result, dict) or result.get("target") != "list":
            continue
        body_path = str(result.get("body_path") or "")
        if not body_path:
            continue
        local = out_dir / Path(body_path).name
        if local.exists():
            return local.read_text(encoding="utf-8", errors="replace")
    for local in sorted(out_dir.glob("s1.*.html")):
        return local.read_text(encoding="utf-8", errors="replace")
    return ""


def _har_summary(har_path: Path) -> dict[str, Any]:
    try:
        har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {"entry_count": 0, "json_count": 0, "xhr_count": 0, "status_error_count": 0, "content_types": []}
    entries = ((har.get("log") or {}).get("entries") or []) if isinstance(har, dict) else []
    cts: Counter[str] = Counter()
    json_count = 0
    xhr_count = 0
    status_error_count = 0
    for entry in entries:
        req = entry.get("request") or {}
        resp = entry.get("response") or {}
        rtype = str(entry.get("_resourceType") or entry.get("resourceType") or req.get("_resourceType") or "")
        if rtype in ("xhr", "fetch"):
            xhr_count += 1
        try:
            status = int(resp.get("status") or 0)
        except (TypeError, ValueError):
            status = 0
        if status >= 400:
            status_error_count += 1
        ct = _content_type(resp)
        if ct:
            cts[ct.split(";", 1)[0].strip().lower()] += 1
        content = resp.get("content") or {}
        if "json" in (ct.lower() + " " + str(content.get("mimeType") or "").lower()):
            json_count += 1
    return {
        "entry_count": len(entries),
        "json_count": json_count,
        "xhr_count": xhr_count,
        "status_error_count": status_error_count,
        "content_types": cts.most_common(8),
    }


def _content_type(resp: dict[str, Any]) -> str:
    for h in resp.get("headers") or []:
        if str(h.get("name") or "").lower() == "content-type":
            return str(h.get("value") or "")
    return str((resp.get("content") or {}).get("mimeType") or "")


def _api_row(c: dict[str, Any]) -> dict[str, Any]:
    hits = c.get("list_hits") or []
    first = hits[0] if hits else {}
    return {
        "badge": f"score {c.get('relevance_score')}",
        "main": c.get("url") or "",
        "meta": f"{c.get('method') or '?'} {c.get('status') or '?'} · {c.get('resource_type') or '-'} · {_short(c.get('content_type'), 80)}",
        "evidence": f"list_hits={len(hits)} · best_count={first.get('count') or 0} · keys={', '.join(str(k) for k in (first.get('sample_keys') or [])[:8])}",
    }


def _body_row(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "badge": f"len {c.get('body_len') or 0}",
        "main": c.get("url") or "",
        "meta": f"{c.get('method') or '?'} {c.get('status') or '?'} · key={c.get('body_key') or '-'} · path={c.get('body_field_path')}",
        "evidence": _short(c.get("sample"), 220),
    }


def _simple_row(c: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {
        "badge": str(c.get(keys[0]) or keys[0]) if c else "",
        "main": str(c.get("url") or c.get("sample_url") or c.get("url_template") or ""),
        "meta": " · ".join(f"{k}={_short(c.get(k), 80)}" for k in keys if c.get(k) not in (None, "")),
        "evidence": str(c.get("evidence_url") or c.get("evidence") or ""),
    }
